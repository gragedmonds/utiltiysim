package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestReadinessRequiresAuthenticatedLiveRunner(t *testing.T) {
	token := strings.Repeat("r", 40)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/local/status" || r.Header.Get("Authorization") != "Bearer "+token {
			w.WriteHeader(401)
			return
		}
		fmt.Fprint(w, `{"schemaVersion":"local-status/2.0"}`)
	}))
	defer server.Close()
	file := filepath.Join(t.TempDir(), "ready.json")
	address := server.URL + "/#token=" + token
	data, _ := json.Marshal(map[string]string{"url": address})
	os.WriteFile(file, data, 0600)
	got, err := waitForRunner(file, make(chan struct{}), 2*time.Second)
	if err != nil || got != address {
		t.Fatal(got, err)
	}
	data, _ = json.Marshal(map[string]string{"url": server.URL + "/#token=" + strings.Repeat("x", 40)})
	os.WriteFile(file, data, 0600)
	if _, err = waitForRunner(file, make(chan struct{}), 450*time.Millisecond); err == nil {
		t.Fatal("accepted another process's session")
	}
}

func TestReadinessReportsExitAndTimeout(t *testing.T) {
	file := filepath.Join(t.TempDir(), "missing.json")
	done := make(chan struct{})
	close(done)
	if _, err := waitForRunner(file, done, time.Second); !errors.Is(err, errRunnerExited) {
		t.Fatal(err)
	}
	if _, err := waitForRunner(file, make(chan struct{}), 50*time.Millisecond); err == nil {
		t.Fatal("claimed readiness without a server")
	}
}

func TestReadinessRejectsExternalURLs(t *testing.T) {
	file := filepath.Join(t.TempDir(), "ready.json")
	os.WriteFile(file, []byte(`{"url":"https://example.com/#token=external"}`), 0600)
	if _, err := waitForRunner(file, make(chan struct{}), 250*time.Millisecond); err == nil {
		t.Fatal("accepted external runner URL")
	}
}

func TestOpeningTheExecutableAgainFindsTheRunningLauncher(t *testing.T) {
	token := strings.Repeat("t", 64)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/status" || r.Header.Get("Authorization") != "Bearer "+token {
			w.WriteHeader(401)
			return
		}
		fmt.Fprint(w, `{"message":"ok"}`)
	}))
	defer server.Close()
	file := filepath.Join(t.TempDir(), "launcher.json")
	if got := runningLauncher(file); got != "" {
		t.Fatal("no file, yet a launcher was found:", got)
	}
	address := server.URL + "/#token=" + token
	os.WriteFile(file, []byte(`{"url":"`+address+`"}`), 0600)
	if got := runningLauncher(file); got != address {
		t.Fatal(got)
	}
	// A stale file (the launcher it names is gone, or the credential is wrong) is ignored and a new launcher starts.
	os.WriteFile(file, []byte(`{"url":"`+server.URL+`/#token=wrong"}`), 0600)
	if got := runningLauncher(file); got != "" {
		t.Fatal("accepted a stale credential:", got)
	}
	server.Close()
	os.WriteFile(file, []byte(`{"url":"`+address+`"}`), 0600)
	if got := runningLauncher(file); got != "" {
		t.Fatal("accepted a launcher that is gone:", got)
	}
}

func TestRememberedFolderRequiresValidExplicitPreference(t *testing.T) {
	file := filepath.Join(t.TempDir(), "storage.json")
	if _, ok := savedFolder(file); ok {
		t.Fatal("missing preference skipped setup")
	}
	for _, raw := range []string{`null`, `""`, `"relative/path"`, `{}`, `broken`} {
		os.WriteFile(file, []byte(raw), 0600)
		if _, ok := savedFolder(file); ok {
			t.Fatal("invalid preference skipped setup:", raw)
		}
	}
	folder := t.TempDir()
	raw, _ := json.Marshal(folder)
	os.WriteFile(file, raw, 0600)
	if got, ok := savedFolder(file); !ok || got != folder {
		t.Fatal(got, ok)
	}
}

func TestReopeningRunningLauncherGoesStraightToStudio(t *testing.T) {
	engine := "http://127.0.0.1:51234/#token=" + strings.Repeat("e", 64)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(map[string]string{"engineURL": engine})
	}))
	defer server.Close()
	file := filepath.Join(t.TempDir(), "launcher.json")
	pageURL := server.URL + "/#token=" + strings.Repeat("l", 64)
	raw, _ := json.Marshal(map[string]string{"url": pageURL})
	os.WriteFile(file, raw, 0600)
	if got := runningLauncher(file); got != engine {
		t.Fatal(got)
	}
	for _, address := range []string{"", "https://example.com/", "http://localhost:51234/#token=bad"} {
		engine = address
		if got := runningLauncher(file); got != pageURL {
			t.Fatal("unsafe/not-ready URL did not fall back:", got)
		}
	}
}

func TestOlderEngineKeepsLauncherControlsReachableDuringUpgrade(t *testing.T) {
	token := strings.Repeat("e", 64)
	pageURL := "http://127.0.0.1:51234/#token=" + strings.Repeat("l", 64)
	settings := ""
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/local/status" || r.Header.Get("Authorization") != "Bearer "+token {
			w.WriteHeader(401)
			return
		}
		json.NewEncoder(w).Encode(map[string]string{"launcherURL": settings})
	}))
	defer server.Close()
	address := server.URL + "/#token=" + token
	if runnerHasLauncherSettings(address, pageURL) {
		t.Fatal("older engine without a settings link would hide update controls")
	}
	settings = pageURL
	if !runnerHasLauncherSettings(address, pageURL) {
		t.Fatal("current engine should bypass the launcher page")
	}
	if runnerHasLauncherSettings(server.URL+"/#token="+strings.Repeat("x", 64), pageURL) {
		t.Fatal("settings support was accepted without authentication")
	}
}
