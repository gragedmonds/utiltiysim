package main

import (
	"crypto/ed25519"
	"crypto/sha256"
	_ "embed"
	"encoding/base64"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"time"
)

// Automatic updates. A release's manifest names its runtime: where it is, its size, its SHA-256 and a signature of
// that digest. The launcher trusts a manifest signed with the release key (release_key.pub, committed and embedded;
// the private half lives only in the release workflow's secret). When Utility Studio starts with an engine already
// installed, it runs that engine at once and looks for a newer release in the background; a trusted one is
// downloaded and verified into its own folder and used from the next start (or Restart on the page). Without a
// release key, or offline, nothing changes: the launcher's own pinned runtime is all it ever installs.

//go:embed release_key.pub
var releaseKeyFile string

// The platform this launcher was built for (windows-x64, macos-arm64, …); set by the release build.
var platformTag string

const releasesAPI = "https://api.github.com/repos/gragedmonds/utiltiysim/releases?per_page=12"

type manifest struct {
	RuntimeURL       string `json:"runtimeURL"`
	RuntimeSHA       string `json:"runtimeSHA"`
	RuntimeSignature string `json:"runtimeSignature"`
	RuntimePublicKey string `json:"runtimePublicKey"`
	RuntimeBytes     string `json:"runtimeBytes"`
	ReleaseVersion   string `json:"releaseVersion"`
	Platform         string `json:"platform"`
	LauncherSha256   string `json:"launcherSha256"`
	ReleaseURL       string `json:"-"`
}

// The runtime this launcher was built with.
func pinned() manifest {
	return manifest{RuntimeURL: runtimeURL, RuntimeSHA: runtimeSHA, RuntimeSignature: runtimeSignature,
		RuntimePublicKey: runtimePublicKey, RuntimeBytes: runtimeBytes, ReleaseVersion: releaseVersion, Platform: platformTag}
}

// parseReleaseKey reads an OpenSSH public key line ("ssh-ed25519 AAAA… comment", as ssh-keygen writes it).
func parseReleaseKey(text string) (ed25519.PublicKey, error) {
	fields := strings.Fields(text)
	if len(fields) < 2 || fields[0] != "ssh-ed25519" {
		return nil, errors.New("not an ssh-ed25519 public key")
	}
	blob, err := base64.StdEncoding.DecodeString(fields[1])
	if err != nil {
		return nil, err
	}
	// Two length-prefixed strings: the key type, then the 32 raw key bytes.
	read := func() ([]byte, error) {
		if len(blob) < 4 {
			return nil, errors.New("short key")
		}
		n := int(binary.BigEndian.Uint32(blob))
		blob = blob[4:]
		if n < 0 || n > len(blob) {
			return nil, errors.New("short key")
		}
		part := blob[:n]
		blob = blob[n:]
		return part, nil
	}
	kind, err := read()
	if err != nil || string(kind) != "ssh-ed25519" {
		return nil, errors.New("not an ssh-ed25519 public key")
	}
	key, err := read()
	if err != nil || len(key) != ed25519.PublicKeySize {
		return nil, errors.New("not an ed25519 key")
	}
	return ed25519.PublicKey(key), nil
}

func releaseKey() ed25519.PublicKey {
	key, err := parseReleaseKey(releaseKeyFile)
	if err != nil {
		return nil
	}
	return key
}

// trusted says whether a fetched manifest is signed by the release key: its public key is that key and its
// signature covers its digest.
func trusted(m manifest, key ed25519.PublicKey) bool {
	pub, err := base64.StdEncoding.DecodeString(m.RuntimePublicKey)
	if err != nil || key == nil || !ed25519.PublicKey(pub).Equal(key) {
		return false
	}
	sig, err := base64.StdEncoding.DecodeString(m.RuntimeSignature)
	return err == nil && len(m.RuntimeSHA) == 64 && ed25519.Verify(key, []byte(m.RuntimeSHA), sig)
}

type releaseAsset struct {
	Name string `json:"name"`
	URL  string `json:"browser_download_url"`
}

type ghRelease struct {
	Tag         string         `json:"tag_name"`
	Draft       bool           `json:"draft"`
	Prerelease  bool           `json:"prerelease"`
	PublishedAt string         `json:"published_at"`
	HTMLURL     string         `json:"html_url"`
	Assets      []releaseAsset `json:"assets"`
}

// newestManifestURL picks, from the releases list, the most recently published release that carries this
// platform's manifest, and returns the manifest's address and the release page.
func newestManifestURL(releases []ghRelease, platform string) (string, string) {
	name := "manifest-" + platform + ".json"
	sort.SliceStable(releases, func(i, j int) bool { return releases[i].PublishedAt > releases[j].PublishedAt })
	for _, r := range releases {
		if r.Draft || r.Prerelease {
			continue
		}
		for _, a := range r.Assets {
			if a.Name == name {
				return a.URL, r.HTMLURL
			}
		}
	}
	return "", ""
}

func fetchJSON(client *http.Client, url string, into any) error {
	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return err
	}
	req.Header.Set("User-Agent", "UtilityStudio-launcher")
	req.Header.Set("Accept", "application/json")
	response, err := client.Do(req)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	if response.StatusCode != 200 {
		return fmt.Errorf("%s answered %d", url, response.StatusCode)
	}
	return json.NewDecoder(io.LimitReader(response.Body, 2<<20)).Decode(into)
}

// latestManifest asks GitHub for the newest published release's manifest for this platform.
func latestManifest(platform string) (manifest, error) {
	client := &http.Client{Timeout: 20 * time.Second}
	var releases []ghRelease
	if err := fetchJSON(client, releasesAPI, &releases); err != nil {
		return manifest{}, err
	}
	url, page := newestManifestURL(releases, platform)
	if url == "" {
		return manifest{}, errors.New("no release carries a manifest for " + platform)
	}
	var m manifest
	if err := fetchJSON(client, url, &m); err != nil {
		return manifest{}, err
	}
	m.ReleaseURL = page
	return m, nil
}

// ---- which runtime runs: current.json names it, staged.json the one ready for the next start -------------------
type runtimeRef struct {
	Version string `json:"version"`
	SHA     string `json:"sha"`
}

func readRef(path string) (runtimeRef, bool) {
	var ref runtimeRef
	data, err := os.ReadFile(path)
	if err != nil || json.Unmarshal(data, &ref) != nil || ref.Version == "" || ref.SHA == "" {
		return runtimeRef{}, false
	}
	return ref, true
}

func writeRef(path string, ref runtimeRef) error {
	data, _ := json.Marshal(ref)
	return os.WriteFile(path, data, 0600)
}

func runtimeExe(root, version string) string {
	exe := filepath.Join(root, "runtime", version, "utility-runner")
	if runtime.GOOS == "windows" {
		exe += ".exe"
	}
	return exe
}

// installedRuntime is the executable of an installed, verified runtime version, or "".
func installedRuntime(root string, ref runtimeRef) string {
	folder := filepath.Join(root, "runtime", ref.Version)
	if data, err := os.ReadFile(filepath.Join(folder, ".ready")); err != nil || string(data) != ref.SHA {
		return ""
	}
	exe := runtimeExe(root, ref.Version)
	if _, err := os.Stat(exe); err != nil {
		return ""
	}
	return exe
}

// chooseRuntime promotes a staged update if there is one and returns the runtime to run (its exe and version), or
// "" when nothing usable is installed yet.
func chooseRuntime(root string) (string, string) {
	base := filepath.Join(root, "runtime")
	current, _ := readRef(filepath.Join(base, "current.json"))
	if staged, ok := readRef(filepath.Join(base, "staged.json")); ok {
		if installedRuntime(root, staged) != "" {
			current = staged
			_ = writeRef(filepath.Join(base, "current.json"), current)
		}
		os.Remove(filepath.Join(base, "staged.json"))
	}
	if exe := installedRuntime(root, current); exe != "" {
		return exe, current.Version
	}
	return "", ""
}

func fileSHA256(path string) string {
	f, err := os.Open(path)
	if err != nil {
		return ""
	}
	defer f.Close()
	h := sha256.New()
	if _, err = io.Copy(h, f); err != nil {
		return ""
	}
	return hex.EncodeToString(h.Sum(nil))
}

// ---- the background check -----------------------------------------------------------------------------------------
type updateState struct {
	State       string `json:"state"` // off, checking, current, downloading, ready, untrusted, failed
	Version     string `json:"version,omitempty"`
	Message     string `json:"message,omitempty"`
	LauncherURL string `json:"launcherURL,omitempty"`
}

var update = updateState{State: "off"}

func setUpdate(fn func(u *updateState)) {
	mu.Lock()
	fn(&update)
	mu.Unlock()
}

// checkForUpdate looks for a newer trusted release and stages it. “running“ is the version in use.
func checkForUpdate(root, running string) {
	key := releaseKey()
	if key == nil || platformTag == "" {
		return
	}
	setUpdate(func(u *updateState) { *u = updateState{State: "checking"} })
	m, err := latestManifest(platformTag)
	if err != nil {
		setUpdate(func(u *updateState) {
			*u = updateState{State: "failed", Message: "Could not check for updates: " + err.Error()}
		})
		return
	}
	launcherURL := ""
	if self, err := os.Executable(); err == nil && m.LauncherSha256 != "" && m.ReleaseVersion != releaseVersion && fileSHA256(self) != m.LauncherSha256 {
		launcherURL = m.ReleaseURL
	}
	if m.ReleaseVersion == running {
		setUpdate(func(u *updateState) { *u = updateState{State: "current", Version: running, LauncherURL: launcherURL} })
		return
	}
	if !trusted(m, key) {
		setUpdate(func(u *updateState) {
			*u = updateState{State: "untrusted", Version: m.ReleaseVersion, LauncherURL: launcherURL,
				Message: "Release " + m.ReleaseVersion + " is not signed for this launcher."}
		})
		return
	}
	if base := filepath.Join(root, "runtime"); installedRuntime(root, runtimeRef{m.ReleaseVersion, m.RuntimeSHA}) != "" {
		_ = writeRef(filepath.Join(base, "staged.json"), runtimeRef{m.ReleaseVersion, m.RuntimeSHA})
		setUpdate(func(u *updateState) {
			*u = updateState{State: "ready", Version: m.ReleaseVersion, LauncherURL: launcherURL}
		})
		return
	}
	setUpdate(func(u *updateState) {
		*u = updateState{State: "downloading", Version: m.ReleaseVersion, LauncherURL: launcherURL}
	})
	_, err = installRuntime(root, m, func(text string) { setUpdate(func(u *updateState) { u.Message = text }) })
	if err != nil {
		setUpdate(func(u *updateState) {
			*u = updateState{State: "failed", Version: m.ReleaseVersion, Message: "Update paused: " + err.Error(), LauncherURL: launcherURL}
		})
		return
	}
	_ = writeRef(filepath.Join(root, "runtime", "staged.json"), runtimeRef{m.ReleaseVersion, m.RuntimeSHA})
	setUpdate(func(u *updateState) {
		*u = updateState{State: "ready", Version: m.ReleaseVersion, LauncherURL: launcherURL}
	})
}
