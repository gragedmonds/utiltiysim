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
		fmt.Fprint(w, `{"schemaVersion":"local-status/1.0"}`)
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
