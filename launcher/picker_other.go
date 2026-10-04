//go:build !windows

package main

import (
	"context"
	"errors"
	"fmt"
	"os/exec"
	"runtime"
	"strings"
	"time"
)

func chooseFolder(initial string) (string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
	defer cancel()
	var cmd *exec.Cmd
	if runtime.GOOS == "darwin" {
		cmd = exec.CommandContext(ctx, "osascript", "-e", `try
return POSIX path of (choose folder with prompt "Choose storage for Utility Studio")
on error number -128
return ""
end try`)
	} else if tool, err := exec.LookPath("zenity"); err == nil {
		cmd = exec.CommandContext(ctx, tool, "--file-selection", "--directory", "--title=Utility Studio storage", "--filename="+initial+"/")
	} else if tool, err := exec.LookPath("kdialog"); err == nil {
		cmd = exec.CommandContext(ctx, tool, "--getexistingdirectory", initial, "--title", "Utility Studio storage")
	} else {
		return "", fmt.Errorf("No desktop folder selector is available. Use ‘Type a path’ instead.")
	}
	raw, err := cmd.Output()
	var exit *exec.ExitError
	if errors.As(err, &exit) && exit.ExitCode() == 1 && runtime.GOOS != "darwin" {
		return "", nil
	}
	if err != nil {
		return "", fmt.Errorf("Could not open the folder selector. Use ‘Type a path’ instead. %w", err)
	}
	return strings.TrimSpace(string(raw)), nil
}
