package main

import (
	"os"
	"os/exec"
	"testing"
)

func TestWindowsPickerScriptParses(t *testing.T) {
	// Parse the actual script without opening a modal dialog on a CI worker.
	cmd := exec.Command("powershell.exe", "-NoProfile", "-Command", `$tokens=$null; $errors=$null; [void][System.Management.Automation.Language.Parser]::ParseInput($env:UTILSIM_TEST_SCRIPT,[ref]$tokens,[ref]$errors); if ($errors.Count) { $errors | Out-String | Write-Error; exit 1 }`)
	cmd.Env = append(os.Environ(), "UTILSIM_TEST_SCRIPT="+folderPickerScript)
	if output, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("%v: %s", err, output)
	}
}
