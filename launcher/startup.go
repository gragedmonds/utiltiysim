package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

var errRunnerExited = errors.New("the local engine stopped before it was ready")

func validStudioURL(address string) bool {
	u, err := url.Parse(address)
	if err != nil || u.Scheme != "http" || u.Hostname() != "127.0.0.1" || u.Port() == "" || u.User != nil || u.Path != "/" || u.RawQuery != "" {
		return false
	}
	fragment, err := url.ParseQuery(u.Fragment)
	return err == nil && len(fragment.Get("token")) >= 32
}

// Older engines have no in-app link back to the launcher. Keep the update/quit
// page available during that first upgrade instead of hiding its only controls.
func runnerHasLauncherSettings(address, pageURL string) bool {
	if !validStudioURL(address) || pageURL == "" {
		return false
	}
	u, _ := url.Parse(address)
	fragment, _ := url.ParseQuery(u.Fragment)
	req, _ := http.NewRequest("GET", "http://"+u.Host+"/local/status", nil)
	req.Header.Set("Authorization", "Bearer "+fragment.Get("token"))
	response, err := (&http.Client{Timeout: time.Second}).Do(req)
	if err != nil {
		return false
	}
	defer response.Body.Close()
	var status struct {
		LauncherURL string `json:"launcherURL"`
	}
	return response.StatusCode == 200 && json.NewDecoder(io.LimitReader(response.Body, 65536)).Decode(&status) == nil && status.LauncherURL == pageURL
}

// A readiness file supplies the per-launch URL. Confirm its authenticated API is
// reachable before presenting success; a port in use must never count as our engine.
func waitForRunner(path string, done <-chan struct{}, timeout time.Duration) (string, error) {
	timer := time.NewTimer(timeout)
	defer timer.Stop()
	tick := time.NewTicker(200 * time.Millisecond)
	defer tick.Stop()
	client := &http.Client{Timeout: time.Second}
	for {
		select {
		case <-done:
			return "", errRunnerExited
		case <-timer.C:
			return "", errors.New("the local engine did not respond in time")
		case <-tick.C:
			raw, err := os.ReadFile(path)
			if err != nil {
				continue
			}
			var ready struct {
				URL string `json:"url"`
			}
			if json.Unmarshal(raw, &ready) != nil {
				continue
			}
			u, err := url.Parse(ready.URL)
			if err != nil || u.Scheme != "http" || u.Hostname() != "127.0.0.1" || u.Port() == "" || u.User != nil || u.Path != "/" || u.RawQuery != "" {
				continue
			}
			fragment, err := url.ParseQuery(u.Fragment)
			if err != nil || len(fragment.Get("token")) < 32 {
				continue
			}
			req, _ := http.NewRequest("GET", "http://"+u.Host+"/local/status", nil)
			req.Header.Set("Authorization", "Bearer "+fragment.Get("token"))
			response, err := client.Do(req)
			if err != nil {
				continue
			}
			var status struct {
				Schema string `json:"schemaVersion"`
			}
			err = json.NewDecoder(io.LimitReader(response.Body, 65536)).Decode(&status)
			response.Body.Close()
			if response.StatusCode == 200 && err == nil && status.Schema == "local-status/2.0" {
				return ready.URL, nil
			}
		}
	}
}

func logTail(path string) string {
	f, err := os.Open(path)
	if err != nil {
		return ""
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil {
		return ""
	}
	if info.Size() > 1800 {
		_, _ = f.Seek(-1800, io.SeekEnd)
	}
	data, _ := io.ReadAll(f)
	return strings.TrimSpace(string(data))
}

func runEngine(exe, root string) {
	setMessage("Starting the local server…")
	ready, err := os.CreateTemp(root, ".runner-ready-*.json")
	if err != nil {
		setMessage("Could not create the startup receipt: " + err.Error())
		return
	}
	readyPath := ready.Name()
	ready.Close()
	defer os.Remove(readyPath)
	logName := filepath.Join(root, "runner.log")
	log, err := os.OpenFile(logName, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0600)
	if err != nil {
		setMessage("Could not open the engine log: " + err.Error())
		return
	}
	defer log.Close()
	fmt.Fprintln(log, "\n--- Starting local engine", time.Now().Format(time.RFC3339), "---")
	cmd := exec.Command(exe, "--store", root, "--port", "0", "--ready-file", readyPath)
	cmd.Dir, cmd.Stdout, cmd.Stderr = root, log, log
	cmd.Env = append(os.Environ(), "UTILITY_STUDIO_LAUNCHER_URL="+launcherPageURL)
	if err = cmd.Start(); err != nil {
		setMessage("Could not start the engine: " + err.Error() + ". Log: " + logName)
		return
	}
	mu.Lock()
	engineCmd = cmd
	mu.Unlock()
	defer func() { mu.Lock(); engineCmd = nil; mu.Unlock() }()
	done := make(chan struct{})
	var processError error
	go func() { processError = cmd.Wait(); close(done) }()
	address, err := waitForRunner(readyPath, done, 90*time.Second)
	if err != nil {
		if !errors.Is(err, errRunnerExited) {
			_ = cmd.Process.Kill()
		}
		<-done
		setMessage("Engine could not start: " + err.Error() + ". Log: " + logName + "\n" + logTail(logName))
		return
	}
	os.Remove(readyPath)
	mu.Lock()
	engineURL = address
	message = "Utility Studio is running. You can close this settings tab while you use it."
	mu.Unlock()
	if rememberedLaunch && !runnerHasLauncherSettings(address, launcherPageURL) {
		openBrowser(launcherPageURL)
	}
	openBrowser(address)
	<-done
	mu.Lock()
	engineURL = ""
	closed := quitting
	mu.Unlock()
	if closed {
		setMessage("Utility Studio has closed. Your files are saved.")
	} else if processError != nil {
		setMessage("Engine stopped: " + processError.Error() + ". Log: " + logName + "\n" + logTail(logName))
	} else {
		setMessage("Utility Studio has stopped. Your files are saved. Start it again when you’re ready.")
	}
}
