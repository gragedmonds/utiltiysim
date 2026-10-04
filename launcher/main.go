// A small bootstrapper: it keeps the signed runtime up to date in the storage folder, starts the app's server there
// and opens Utility Studio in the browser. The storage folder is chosen before any download.
package main

import (
	"archive/zip"
	"crypto/ed25519"
	"crypto/rand"
	"crypto/sha256"
	_ "embed"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"time"
)

// Release build pins the runtime identity, verification key and signed digest.
var runtimeURL, runtimeSHA, runtimeSignature, runtimePublicKey, runtimeBytes, releaseVersion string
var mu sync.Mutex
var message = "Ready to open Utility Studio."
var busy, picking bool
var engineURL, logPath string
var engineCmd *exec.Cmd
var quitting bool

func validPath(root, name string) (string, error) {
	if strings.ContainsAny(name, "\\:") || strings.HasPrefix(name, "/") || filepath.IsAbs(name) {
		return "", errors.New("unsafe runtime filename")
	}
	clean := filepath.Clean(filepath.FromSlash(name))
	if clean == ".." || strings.HasPrefix(clean, ".."+string(os.PathSeparator)) {
		return "", errors.New("runtime archive escapes its folder")
	}
	return filepath.Join(root, clean), nil
}
func extract(archive, destination string) error {
	z, err := zip.OpenReader(archive)
	if err != nil {
		return err
	}
	defer z.Close()
	var expanded uint64
	for _, f := range z.File {
		expanded += f.UncompressedSize64
		if expanded > 3<<30 {
			return errors.New("runtime archive exceeds size limit")
		}
		path, err := validPath(destination, f.Name)
		if err != nil {
			return err
		}
		if f.Mode()&os.ModeSymlink != 0 {
			return errors.New("runtime contains symbolic links")
		}
		if f.FileInfo().IsDir() {
			if err = os.MkdirAll(path, 0700); err != nil {
				return err
			}
			continue
		}
		if err = os.MkdirAll(filepath.Dir(path), 0700); err != nil {
			return err
		}
		input, err := f.Open()
		if err != nil {
			return err
		}
		mode := os.FileMode(0600)
		if f.Mode()&0111 != 0 {
			mode = 0700
		}
		output, err := os.OpenFile(path, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, mode)
		if err != nil {
			input.Close()
			return err
		}
		_, err = io.Copy(output, io.LimitReader(input, int64(f.UncompressedSize64)+1))
		input.Close()
		end := output.Close()
		if err != nil {
			return err
		}
		if end != nil {
			return end
		}
	}
	return nil
}
func setMessage(s string) { mu.Lock(); message = s; mu.Unlock() }
func verify(path string) error {
	f, err := os.Open(path)
	if err != nil {
		return err
	}
	defer f.Close()
	h := sha256.New()
	n, err := io.Copy(h, f)
	if err != nil {
		return err
	}
	if fmt.Sprint(n) != runtimeBytes || hex.EncodeToString(h.Sum(nil)) != runtimeSHA {
		return errors.New("runtime size or checksum failed")
	}
	pub, err := base64.StdEncoding.DecodeString(runtimePublicKey)
	if err != nil || len(pub) != ed25519.PublicKeySize {
		return errors.New("invalid verification key")
	}
	sig, err := base64.StdEncoding.DecodeString(runtimeSignature)
	if err != nil || !ed25519.Verify(pub, []byte(runtimeSHA), sig) {
		return errors.New("runtime signature failed")
	}
	return nil
}
func install(root string) (string, error) {
	if runtimeURL == "" || releaseVersion == "" {
		return "", errors.New("this development launcher has no published runtime")
	}
	folder := filepath.Join(root, "runtime", releaseVersion)
	exe := filepath.Join(folder, "utility-runner")
	if runtime.GOOS == "windows" {
		exe += ".exe"
	}
	if data, err := os.ReadFile(filepath.Join(folder, ".ready")); err == nil && string(data) == runtimeSHA {
		if _, err = os.Stat(exe); err == nil {
			setMessage("Using the engine already saved on this drive…")
			return exe, nil
		}
	}
	if err := os.MkdirAll(filepath.Dir(folder), 0700); err != nil {
		return "", err
	}
	temp := folder + ".download"
	var offset int64
	if stat, err := os.Stat(temp); err == nil {
		offset = stat.Size()
	}
	setMessage("Connecting to the engine download…")
	req, err := http.NewRequest("GET", runtimeURL, nil)
	if err != nil {
		return "", err
	}
	if offset > 0 {
		req.Header.Set("Range", fmt.Sprintf("bytes=%d-", offset))
	}
	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.ResponseHeaderTimeout = 30 * time.Second
	response, err := (&http.Client{Timeout: 30 * time.Minute, Transport: transport}).Do(req)
	if err != nil {
		return "", err
	}
	defer response.Body.Close()
	if response.StatusCode != 200 && response.StatusCode != 206 {
		return "", fmt.Errorf("download returned %d; reconnect and retry", response.StatusCode)
	}
	flags := os.O_CREATE | os.O_TRUNC | os.O_WRONLY
	if response.StatusCode == 206 && offset > 0 {
		if !strings.HasPrefix(response.Header.Get("Content-Range"), fmt.Sprintf("bytes %d-", offset)) {
			return "", errors.New("invalid resumed download")
		}
		flags = os.O_CREATE | os.O_APPEND | os.O_WRONLY
	} else {
		offset = 0
	}
	out, err := os.OpenFile(temp, flags, 0600)
	if err != nil {
		return "", err
	}
	buffer := make([]byte, 128*1024)
	received := offset
	for {
		n, e := response.Body.Read(buffer)
		if n > 0 {
			if _, err = out.Write(buffer[:n]); err != nil {
				out.Close()
				return "", err
			}
			received += int64(n)
			if received > 2<<30 {
				out.Close()
				return "", errors.New("download exceeds size limit")
			}
			setMessage(fmt.Sprintf("Downloading the engine: %.1f MB received. Storage: %s", float64(received)/1e6, root))
		}
		if e == io.EOF {
			break
		}
		if e != nil {
			out.Close()
			return "", e
		}
	}
	if err = out.Close(); err != nil {
		return "", err
	}
	setMessage("Verifying the engine’s checksum and signature…")
	if err = verify(temp); err != nil {
		os.Remove(temp)
		return "", err
	}
	setMessage("Installing the verified engine…")
	staging := folder + ".installing"
	os.RemoveAll(staging)
	if err = os.MkdirAll(staging, 0700); err != nil {
		return "", err
	}
	if err = extract(temp, staging); err != nil {
		return "", err
	}
	if err = os.WriteFile(filepath.Join(staging, ".ready"), []byte(runtimeSHA), 0600); err != nil {
		return "", err
	}
	if _, err = os.Stat(folder); err == nil {
		os.RemoveAll(folder)
	} // Incomplete copy of this release only; other versions remain.
	if err = os.Rename(staging, folder); err != nil {
		return "", err
	}
	os.Remove(temp)
	return exe, nil
}
func openBrowser(url string) {
	var cmd *exec.Cmd
	switch runtime.GOOS {
	case "windows":
		cmd = exec.Command("rundll32", "url.dll,FileProtocolHandler", url)
	case "darwin":
		cmd = exec.Command("open", url)
	default:
		cmd = exec.Command("xdg-open", url)
	}
	_ = cmd.Start()
}

//go:embed page.html
var page string

// A launcher already running for this user: its page's address, so opening the executable again shows that page
// instead of starting a second launcher.
func runningLauncher(path string) string {
	data, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	var saved struct {
		URL string `json:"url"`
	}
	if json.Unmarshal(data, &saved) != nil || saved.URL == "" {
		return ""
	}
	address, token, _ := strings.Cut(saved.URL, "/#token=")
	req, err := http.NewRequest("GET", address+"/status", nil)
	if err != nil || token == "" {
		return ""
	}
	req.Header.Set("Authorization", "Bearer "+token)
	response, err := (&http.Client{Timeout: time.Second}).Do(req)
	if err != nil {
		return ""
	}
	response.Body.Close()
	if response.StatusCode != 200 {
		return ""
	}
	return saved.URL
}

func main() {
	config, err := os.UserConfigDir()
	if err != nil {
		fatal(err.Error())
		return
	}
	pref := filepath.Join(config, "UtilityStudio", "storage.json")
	running := filepath.Join(config, "UtilityStudio", "launcher.json")
	if url := runningLauncher(running); url != "" {
		openBrowser(url)
		return
	}
	home, _ := os.UserHomeDir()
	chosen := filepath.Join(home, "UtilitySim")
	if data, err := os.ReadFile(pref); err == nil {
		_ = json.Unmarshal(data, &chosen)
	}
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		fatal("Utility Studio could not open a local port: " + err.Error())
		return
	}
	origin := "http://" + listener.Addr().String()
	random := make([]byte, 32)
	if _, err = rand.Read(random); err != nil {
		panic(err)
	}
	token := hex.EncodeToString(random)
	pageURL := origin + "/#token=" + token
	os.MkdirAll(filepath.Dir(running), 0700)
	if data, err := json.Marshal(map[string]string{"url": pageURL}); err == nil {
		_ = os.WriteFile(running, data, 0600)
	}
	quit := func() {
		mu.Lock()
		quitting = true
		if engineCmd != nil && engineCmd.Process != nil {
			_ = engineCmd.Process.Kill()
		}
		mu.Unlock()
		os.Remove(running)
		time.Sleep(400 * time.Millisecond)
		os.Exit(0)
	}
	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Referrer-Policy", "no-referrer")
		w.Header().Set("Cache-Control", "no-store")
		if r.Host != listener.Addr().String() {
			http.Error(w, "Loopback access only", 403)
			return
		}
		if r.URL.Path == "/" {
			w.Header().Set("Content-Type", "text/html")
			fmt.Fprint(w, page)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		if r.Header.Get("Authorization") != "Bearer "+token {
			w.WriteHeader(401)
			fmt.Fprint(w, `{"error":"Reopen the launcher."}`)
			return
		}
		if r.URL.Path == "/status" {
			mu.Lock()
			json.NewEncoder(w).Encode(map[string]any{"message": message, "busy": busy, "picking": picking, "folder": chosen, "engineURL": engineURL, "logPath": logPath, "quitting": quitting})
			mu.Unlock()
			return
		}
		if r.URL.Path == "/quit" && r.Method == "POST" {
			fmt.Fprint(w, `{"ok":true}`)
			go quit()
			return
		}
		if r.URL.Path == "/browse" && r.Method == "POST" {
			mu.Lock()
			if busy || picking {
				mu.Unlock()
				w.WriteHeader(409)
				fmt.Fprint(w, `{"error":"Finish the current action before choosing another folder."}`)
				return
			}
			picking = true
			initial := chosen
			mu.Unlock()
			folder, err := chooseFolder(initial)
			mu.Lock()
			picking = false
			if err == nil && folder != "" {
				chosen = folder
			}
			selected := chosen
			mu.Unlock()
			if err != nil {
				w.WriteHeader(422)
				json.NewEncoder(w).Encode(map[string]string{"error": err.Error()})
				return
			}
			json.NewEncoder(w).Encode(map[string]any{"folder": selected, "cancelled": folder == ""})
			return
		}
		if r.URL.Path != "/start" || r.Method != "POST" {
			http.NotFound(w, r)
			return
		}
		var value struct {
			Folder string `json:"folder"`
		}
		if err := json.NewDecoder(io.LimitReader(r.Body, 8192)).Decode(&value); err != nil || !filepath.IsAbs(value.Folder) {
			w.WriteHeader(422)
			fmt.Fprint(w, `{"error":"Choose an absolute storage folder."}`)
			return
		}
		mu.Lock()
		if busy || picking {
			mu.Unlock()
			w.WriteHeader(409)
			fmt.Fprint(w, `{"error":"The engine is already starting or running."}`)
			return
		}
		busy = true
		engineURL = ""
		message = "Starting the engine: checking your storage folder…"
		chosen = filepath.Clean(value.Folder)
		root := chosen
		logPath = filepath.Join(root, "runner.log")
		mu.Unlock()
		fmt.Fprint(w, `{"ok":true}`)
		go func() {
			defer func() { mu.Lock(); busy = false; mu.Unlock() }()
			if err := os.MkdirAll(root, 0700); err != nil {
				setMessage("Storage drive unavailable: " + err.Error())
				return
			}
			probe, err := os.CreateTemp(root, ".write-check-")
			if err != nil {
				setMessage(err.Error())
				return
			}
			probe.Close()
			os.Remove(probe.Name())
			exe, err := install(root)
			if err != nil {
				setMessage("Setup paused: " + err.Error())
				return
			}
			os.MkdirAll(filepath.Dir(pref), 0700)
			data, _ := json.Marshal(root)
			if err = os.WriteFile(pref, data, 0600); err != nil {
				setMessage(err.Error())
				return
			}
			runEngine(exe, root)
		}()
	})
	openBrowser(pageURL)
	banner(pageURL)
	_ = http.Serve(listener, mux)
}
