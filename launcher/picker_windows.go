package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

// The folder selector is Windows' own (IFileOpenDialog in folder mode), opened from this process and owned by the
// window in front, the browser showing the launcher page, so it appears on top of it and the page is never left
// waiting behind an invisible dialog. COM is used through the vtables directly; no cgo. PowerShell's dialog is the
// fallback if the shell refuses, owned by the same window.

var (
	ole32   = syscall.NewLazyDLL("ole32.dll")
	shell32 = syscall.NewLazyDLL("shell32.dll")
	user32  = syscall.NewLazyDLL("user32.dll")

	procCoInitializeEx          = ole32.NewProc("CoInitializeEx")
	procCoUninitialize          = ole32.NewProc("CoUninitialize")
	procCoCreateInstance        = ole32.NewProc("CoCreateInstance")
	procCoTaskMemFree           = ole32.NewProc("CoTaskMemFree")
	procSHCreateItemFromParsing = shell32.NewProc("SHCreateItemFromParsingName")
	procGetForegroundWindow     = user32.NewProc("GetForegroundWindow")
	procMessageBoxW             = user32.NewProc("MessageBoxW")
	errCancelled                = errors.New("cancelled")
	clsidFileOpenDialog         = guid{0xDC1C5A9C, 0xE88A, 0x4DDE, [8]byte{0xA5, 0xA1, 0x60, 0xF8, 0x2A, 0x20, 0xAE, 0xF7}}
	iidIFileOpenDialog          = guid{0xD57C7288, 0xD4AD, 0x4768, [8]byte{0xBE, 0x02, 0x9D, 0x96, 0x95, 0x32, 0xD9, 0x60}}
	iidIShellItem               = guid{0x43826D1E, 0xE718, 0x42EE, [8]byte{0xBC, 0x55, 0xA1, 0xE2, 0x61, 0xC3, 0x7B, 0xFE}}
)

type guid struct {
	Data1 uint32
	Data2 uint16
	Data3 uint16
	Data4 [8]byte
}

const (
	coinitApartmentThreaded = 0x2
	clsctxInprocServer      = 0x1
	fosNoChangeDir          = 0x8
	fosPickFolders          = 0x20
	fosForceFileSystem      = 0x40
	fosPathMustExist        = 0x800
	sigdnFileSysPath        = 0x80058000
	hrCancelled             = 0x800704C7 // HRESULT_FROM_WIN32(ERROR_CANCELLED)
	sFalse                  = 1
)

// COM objects are reached through their vtables, in interface order. IFileOpenDialog: IUnknown, IModalWindow,
// IFileDialog, IFileOpenDialog.
type unknown struct{ vtbl *[3]uintptr } // QueryInterface, AddRef, Release

type fileOpenDialogVtbl struct {
	QueryInterface, AddRef, Release uintptr
	Show                            uintptr
	SetFileTypes, SetFileTypeIndex, GetFileTypeIndex, Advise, Unadvise, SetOptions, GetOptions, SetDefaultFolder,
	SetFolder, GetFolder, GetCurrentSelection, SetFileName, GetFileName, SetTitle, SetOkButtonLabel,
	SetFileNameLabel, GetResult, AddPlace, SetDefaultExtension, Close, SetClientGuid, ClearClientData, SetFilter uintptr
	GetResults, GetSelectedItems uintptr
}

type fileOpenDialog struct{ vtbl *fileOpenDialogVtbl }

type shellItemVtbl struct {
	QueryInterface, AddRef, Release                                  uintptr
	BindToHandler, GetParent, GetDisplayName, GetAttributes, Compare uintptr
}

type shellItem struct{ vtbl *shellItemVtbl }

func foregroundWindow() uintptr {
	hwnd, _, _ := procGetForegroundWindow.Call()
	return hwnd
}

func utf16(s string) *uint16 {
	p, _ := syscall.UTF16PtrFromString(s)
	return p
}

func release(obj unsafe.Pointer) {
	if obj != nil {
		syscall.SyscallN((*unknown)(obj).vtbl[2], uintptr(obj))
	}
}

// nativeFolderDialog shows the shell's folder picker owned by “owner“ and returns the chosen folder, errCancelled
// when the person closed it, or another error when the dialog could not be used at all (the caller falls back).
func nativeFolderDialog(owner uintptr, initial string) (string, error) {
	runtime.LockOSThread()
	defer runtime.UnlockOSThread()
	hr, _, _ := procCoInitializeEx.Call(0, coinitApartmentThreaded)
	if int32(hr) < 0 {
		return "", fmt.Errorf("COM initialisation failed (0x%08X)", uint32(hr))
	}
	if hr != sFalse {
		defer procCoUninitialize.Call()
	}
	var dialog *fileOpenDialog
	hr, _, _ = procCoCreateInstance.Call(uintptr(unsafe.Pointer(&clsidFileOpenDialog)), 0, clsctxInprocServer,
		uintptr(unsafe.Pointer(&iidIFileOpenDialog)), uintptr(unsafe.Pointer(&dialog)))
	if int32(hr) < 0 || dialog == nil {
		return "", fmt.Errorf("the folder dialog is unavailable (0x%08X)", uint32(hr))
	}
	defer release(unsafe.Pointer(dialog))
	vt, this := dialog.vtbl, uintptr(unsafe.Pointer(dialog))
	syscall.SyscallN(vt.SetOptions, this, fosPickFolders|fosForceFileSystem|fosPathMustExist|fosNoChangeDir)
	syscall.SyscallN(vt.SetTitle, this, uintptr(unsafe.Pointer(utf16("Choose where Utility Studio keeps its files"))))
	syscall.SyscallN(vt.SetOkButtonLabel, this, uintptr(unsafe.Pointer(utf16("Use this folder"))))
	if initial != "" {
		var item *shellItem
		if h, _, _ := procSHCreateItemFromParsing.Call(uintptr(unsafe.Pointer(utf16(initial))), 0,
			uintptr(unsafe.Pointer(&iidIShellItem)), uintptr(unsafe.Pointer(&item))); int32(h) >= 0 && item != nil {
			syscall.SyscallN(vt.SetFolder, this, uintptr(unsafe.Pointer(item)))
			release(unsafe.Pointer(item))
		}
	}
	hr, _, _ = syscall.SyscallN(vt.Show, this, owner)
	if uint32(hr) == hrCancelled {
		return "", errCancelled
	}
	if int32(hr) < 0 {
		return "", fmt.Errorf("the folder dialog could not open (0x%08X)", uint32(hr))
	}
	var result *shellItem
	hr, _, _ = syscall.SyscallN(vt.GetResult, this, uintptr(unsafe.Pointer(&result)))
	if int32(hr) < 0 || result == nil {
		return "", fmt.Errorf("the folder dialog returned nothing (0x%08X)", uint32(hr))
	}
	defer release(unsafe.Pointer(result))
	var name *uint16
	hr, _, _ = syscall.SyscallN(result.vtbl.GetDisplayName, uintptr(unsafe.Pointer(result)), sigdnFileSysPath, uintptr(unsafe.Pointer(&name)))
	if int32(hr) < 0 || name == nil {
		return "", fmt.Errorf("the chosen folder has no file system path")
	}
	defer procCoTaskMemFree.Call(uintptr(unsafe.Pointer(name)))
	return syscall.UTF16ToString(unsafe.Slice(name, 32768)), nil
}

// The fallback: PowerShell's dialog, owned by the same window. The path and owner are passed as environment data,
// never interpolated into the script.
const folderPickerScript = `
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = 'Choose where Utility Studio keeps its files'
$dialog.ShowNewFolderButton = $true
$dialog.SelectedPath = $env:UTILSIM_PICKER_FOLDER
$owner = New-Object System.Windows.Forms.NativeWindow
$handle = [IntPtr]::Zero
if ($env:UTILSIM_PICKER_OWNER) { $handle = [IntPtr][int64]$env:UTILSIM_PICKER_OWNER }
if ($handle -ne [IntPtr]::Zero) { $owner.AssignHandle($handle) }
try {
 if ($dialog.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) {
  [Console]::Write($dialog.SelectedPath)
 }
} finally { $dialog.Dispose(); if ($handle -ne [IntPtr]::Zero) { $owner.ReleaseHandle() } }
`

func powershellFolderDialog(owner uintptr, initial string) (string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
	defer cancel()
	powershell := filepath.Join(os.Getenv("SystemRoot"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
	cmd := exec.CommandContext(ctx, powershell, "-NoProfile", "-STA", "-Command", folderPickerScript)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	cmd.Env = append(os.Environ(), "UTILSIM_PICKER_FOLDER="+initial, fmt.Sprintf("UTILSIM_PICKER_OWNER=%d", owner))
	raw, err := cmd.Output()
	if err != nil {
		return "", fmt.Errorf("Windows could not open the folder selector. Use ‘Type a path’ instead. %w", err)
	}
	folder := strings.TrimSpace(strings.TrimPrefix(string(raw), "\ufeff"))
	if folder != "" && !filepath.IsAbs(folder) {
		return "", fmt.Errorf("Windows returned an invalid storage folder")
	}
	return folder, nil
}

func chooseFolder(initial string) (string, error) {
	owner := foregroundWindow()
	folder, err := nativeFolderDialog(owner, initial)
	if err == nil {
		return folder, nil
	}
	if errors.Is(err, errCancelled) {
		return "", nil
	}
	return powershellFolderDialog(owner, initial)
}

// A fatal error before the page exists has nowhere else to go: the launcher has no console window on Windows.
func fatal(message string) {
	procMessageBoxW.Call(0, uintptr(unsafe.Pointer(utf16(message))), uintptr(unsafe.Pointer(utf16("Utility Studio"))), 0x10)
}

func banner(_ string) {}
