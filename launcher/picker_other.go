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
return POSIX path of (choose folder with prompt "Choose where Utility Studio keeps its files")
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

func fatal(message string) { fmt.Println(message) }

// The terminal this launcher was started from, on macOS and Linux.
func banner(url string) {
	fmt.Print(`
  _   _ _   _ _ _ _          ____  _             _ _
 | | | | |_(_) (_) |_ _   _ / ___|| |_ _   _  __| (_) ___
 | | | | __| | | | __| | | |\___ \| __| | | |/ _` + "`" + ` | |/ _ \
 | |_| | |_| | | | |_| |_| | ___) | |_| |_| | (_| | | (_) |
  \___/ \__|_|_|_|\__|\__, ||____/ \__|\__,_|\__,_|_|\___/
                      |___/

`)
	fmt.Println("Utility Studio is open in your browser:", url)
	fmt.Println("Keep this window open while you use it. Closing it, or Quit in the page, stops Utility Studio.")
}
