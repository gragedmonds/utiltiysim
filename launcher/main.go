// A small bootstrapper. The user selects storage before any runtime download.
package main

import (
	"archive/zip"
	"crypto/ed25519"
	"crypto/rand"
	"crypto/sha256"
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
var message = "Choose a folder for the engine and your simulations."
var busy bool

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
	req, err := http.NewRequest("GET", runtimeURL, nil)
	if err != nil {
		return "", err
	}
	if offset > 0 {
		req.Header.Set("Range", fmt.Sprintf("bytes=%d-", offset))
	}
	response, err := (&http.Client{Timeout: 30 * time.Minute}).Do(req)
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

const page = `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Utility Studio · Install</title><style>body{font:16px system-ui;background:#f4f7f5;color:#153c3c;max-width:680px;margin:60px auto;padding:24px}h1{font-size:42px;letter-spacing:-2px}label,input,button{display:block;margin:16px 0}input{box-sizing:border-box;width:100%;padding:14px;font:inherit}button{padding:14px 22px;border:0;border-radius:10px;background:#196b61;color:white;font:inherit}p{line-height:1.6}#status{background:white;padding:20px;border-radius:12px}</style></head><body><small>UTILITY STUDIO · LOCAL RUNNER</small><h1>A home for your simulations.</h1><p>Choose a folder for the engine, cached towns and full results, such as <strong>P:\UtilitySim</strong>. The engine downloads once. Later launches use the cached copy.</p><label for="folder">Storage folder</label><input id="folder"><button id="start">Start local engine</button><p id="status" role="status"></p><p>To open another library, change the folder before starting. Existing libraries stay where they are. To move a library, stop the runner, copy the complete folder and select the copy; saved archives are verified when reopened.</p><script>const token=new URLSearchParams(location.hash.slice(1)).get('token');history.replaceState(null,'','/');async function call(path,data){const r=await fetch(path,{method:data?'POST':'GET',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:data?JSON.stringify(data):undefined});const v=await r.json();if(!r.ok)throw Error(v.error);return v;}call('/status').then(v=>document.getElementById('folder').value=v.folder);document.getElementById('start').onclick=async()=>{try{await call('/start',{folder:document.getElementById('folder').value});}catch(e){document.getElementById('status').textContent=e.message;}};setInterval(async()=>{try{const v=await call('/status');document.getElementById('status').textContent=v.message;document.getElementById('start').disabled=v.busy;}catch{}},800);</script></body></html>`

func main() {
	config, err := os.UserConfigDir()
	if err != nil {
		fmt.Println(err)
		return
	}
	pref := filepath.Join(config, "UtilityStudio", "storage.json")
	home, _ := os.UserHomeDir()
	chosen := filepath.Join(home, "UtilitySim")
	if data, err := os.ReadFile(pref); err == nil {
		_ = json.Unmarshal(data, &chosen)
	}
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		fmt.Println(err)
		return
	}
	origin := "http://" + listener.Addr().String()
	random := make([]byte, 32)
	if _, err = rand.Read(random); err != nil {
		panic(err)
	}
	token := hex.EncodeToString(random)
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
			json.NewEncoder(w).Encode(map[string]any{"message": message, "busy": busy, "folder": chosen})
			mu.Unlock()
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
		if busy {
			mu.Unlock()
			w.WriteHeader(409)
			fmt.Fprint(w, `{"error":"The engine is already starting or running."}`)
			return
		}
		busy = true
		chosen = filepath.Clean(value.Folder)
		root := chosen
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
			setMessage("Engine ready. Opening pairing and status…")
			cmd := exec.Command(exe, "--store", root)
			cmd.Dir = root
			log, err := os.OpenFile(filepath.Join(root, "runner.log"), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0600)
			if err != nil {
				setMessage(err.Error())
				return
			}
			defer log.Close()
			cmd.Stdout = log
			cmd.Stderr = log
			if err = cmd.Run(); err != nil {
				setMessage("Engine stopped. See runner.log in your storage folder. " + err.Error())
			} else {
				setMessage("Engine stopped. Your library is ready for next time.")
			}
		}()
	})
	openBrowser(origin + "/#token=" + token)
	fmt.Println("Utility Studio launcher is running. Keep this window open while using the engine.")
	_ = http.Serve(listener, mux)
}
