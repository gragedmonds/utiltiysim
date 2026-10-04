package main

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"time"
)

// The path is passed as environment data, never interpolated into PowerShell.
const folderPickerScript = `
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = 'Choose where Utility Studio stores the engine and simulation files'
$dialog.ShowNewFolderButton = $true
$dialog.SelectedPath = $env:UTILSIM_PICKER_FOLDER
$owner = New-Object System.Windows.Forms.Form
$owner.TopMost = $true
$owner.ShowInTaskbar = $false
try {
 if ($dialog.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) {
  [Console]::Write($dialog.SelectedPath)
 }
} finally { $dialog.Dispose(); $owner.Dispose() }
`

func chooseFolder(initial string) (string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
	defer cancel()
	powershell := filepath.Join(os.Getenv("SystemRoot"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
	cmd := exec.CommandContext(ctx, powershell, "-NoProfile", "-STA", "-Command", folderPickerScript)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	cmd.Env = append(os.Environ(), "UTILSIM_PICKER_FOLDER="+initial)
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
