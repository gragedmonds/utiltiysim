package main

import (
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"encoding/binary"
	"os"
	"path/filepath"
	"testing"
)

// An OpenSSH public key line for a key, as ssh-keygen writes it.
func sshLine(pub ed25519.PublicKey) string {
	blob := []byte{}
	for _, part := range [][]byte{[]byte("ssh-ed25519"), pub} {
		n := make([]byte, 4)
		binary.BigEndian.PutUint32(n, uint32(len(part)))
		blob = append(append(blob, n...), part...)
	}
	return "ssh-ed25519 " + base64.StdEncoding.EncodeToString(blob) + " utility-studio-release\n"
}

func TestReleaseKeyAndTrustedManifests(t *testing.T) {
	pub, priv, _ := ed25519.GenerateKey(rand.Reader)
	key, err := parseReleaseKey(sshLine(pub))
	if err != nil || !key.Equal(pub) {
		t.Fatal(err)
	}
	for _, bad := range []string{"", "ssh-rsa AAAA", "ssh-ed25519 notbase64", "ssh-ed25519 " + base64.StdEncoding.EncodeToString([]byte("short"))} {
		if _, err := parseReleaseKey(bad); err == nil {
			t.Fatal("accepted", bad)
		}
	}
	sha := "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
	m := manifest{RuntimeSHA: sha, RuntimePublicKey: base64.StdEncoding.EncodeToString(pub),
		RuntimeSignature: base64.StdEncoding.EncodeToString(ed25519.Sign(priv, []byte(sha)))}
	if !trusted(m, key) {
		t.Fatal("a manifest signed by the release key is trusted")
	}
	other, otherPriv, _ := ed25519.GenerateKey(rand.Reader)
	ephemeral := manifest{RuntimeSHA: sha, RuntimePublicKey: base64.StdEncoding.EncodeToString(other),
		RuntimeSignature: base64.StdEncoding.EncodeToString(ed25519.Sign(otherPriv, []byte(sha)))}
	if trusted(ephemeral, key) {
		t.Fatal("a manifest signed by another key (a throwaway build key) must not be trusted")
	}
	tampered := m
	tampered.RuntimeSHA = "f" + sha[1:]
	if trusted(tampered, key) || trusted(m, nil) {
		t.Fatal("a changed digest, or no release key, must not be trusted")
	}
}

func TestNewestPublishedReleaseWithThisPlatformsManifest(t *testing.T) {
	releases := []ghRelease{
		{Tag: "runner-old", PublishedAt: "2026-10-04T14:17:08Z", HTMLURL: "old", Assets: []releaseAsset{{Name: "manifest-windows-x64.json", URL: "u-old"}}},
		{Tag: "runner-draft", Draft: true, PublishedAt: "2026-10-05T00:00:00Z", Assets: []releaseAsset{{Name: "manifest-windows-x64.json", URL: "u-draft"}}},
		{Tag: "runner-new", PublishedAt: "2026-10-04T16:54:03Z", HTMLURL: "new", Assets: []releaseAsset{{Name: "manifest-windows-x64.json", URL: "u-new"}, {Name: "manifest-linux-x64.json", URL: "l-new"}}},
		{Tag: "runner-mac-only", PublishedAt: "2026-10-04T17:00:00Z", HTMLURL: "mac", Assets: []releaseAsset{{Name: "manifest-macos-arm64.json", URL: "m"}}},
	}
	if url, page := newestManifestURL(releases, "windows-x64"); url != "u-new" || page != "new" {
		t.Fatal(url, page)
	}
	if url, _ := newestManifestURL(releases, "linux-arm64"); url != "" {
		t.Fatal("a platform no release carries:", url)
	}
}

func TestStagedRuntimeIsPromotedOnTheNextStart(t *testing.T) {
	root := t.TempDir()
	base := filepath.Join(root, "runtime")
	install := func(version, sha string) {
		os.MkdirAll(filepath.Join(base, version), 0700)
		os.WriteFile(filepath.Join(base, version, ".ready"), []byte(sha), 0600)
		os.WriteFile(runtimeExe(root, version), []byte("exe"), 0700)
	}
	if exe, version := chooseRuntime(root); exe != "" || version != "" {
		t.Fatal("nothing installed yet:", exe)
	}
	install("runner-a", "sha-a")
	writeRef(filepath.Join(base, "current.json"), runtimeRef{"runner-a", "sha-a"})
	if exe, version := chooseRuntime(root); version != "runner-a" || exe != runtimeExe(root, "runner-a") {
		t.Fatal(exe, version)
	}
	// A staged update that is not actually installed is dropped; an installed one becomes current.
	writeRef(filepath.Join(base, "staged.json"), runtimeRef{"runner-b", "sha-b"})
	if _, version := chooseRuntime(root); version != "runner-a" {
		t.Fatal("promoted a missing runtime")
	}
	if _, err := os.Stat(filepath.Join(base, "staged.json")); err == nil {
		t.Fatal("a useless staged.json is removed")
	}
	install("runner-b", "sha-b")
	writeRef(filepath.Join(base, "staged.json"), runtimeRef{"runner-b", "sha-b"})
	if _, version := chooseRuntime(root); version != "runner-b" {
		t.Fatal("the staged runtime runs next")
	}
	if current, _ := readRef(filepath.Join(base, "current.json")); current.Version != "runner-b" {
		t.Fatal(current)
	}
	// A runtime whose .ready digest does not match is never run.
	os.WriteFile(filepath.Join(base, "runner-b", ".ready"), []byte("other"), 0600)
	if exe, _ := chooseRuntime(root); exe != "" {
		t.Fatal("ran a runtime whose digest changed:", exe)
	}
}
