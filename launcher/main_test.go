package main

import (
	"crypto/ed25519"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"
	"testing"
)

func TestArchivePaths(t *testing.T) {
	root := t.TempDir()
	for _, s := range []string{"../escape", "/absolute", "C:/bad", "x\\evil"} {
		if _, err := validPath(root, s); err == nil {
			t.Fatal(s)
		}
	}
	if p, err := validPath(root, "assets/file"); err != nil || p != filepath.Join(root, "assets", "file") {
		t.Fatal(p, err)
	}
}
func TestRuntimeVerification(t *testing.T) {
	pub, priv, _ := ed25519.GenerateKey(rand.Reader)
	data := []byte("runtime")
	h := sha256.Sum256(data)
	runtimeSHA = hex.EncodeToString(h[:])
	runtimeBytes = fmt.Sprint(len(data))
	runtimePublicKey = base64.StdEncoding.EncodeToString(pub)
	runtimeSignature = base64.StdEncoding.EncodeToString(ed25519.Sign(priv, []byte(runtimeSHA)))
	p := filepath.Join(t.TempDir(), "runtime")
	os.WriteFile(p, data, 0600)
	if err := verify(p, pinned()); err != nil {
		t.Fatal(err)
	}
	os.WriteFile(p, []byte("tampered"), 0600)
	if err := verify(p, pinned()); err == nil {
		t.Fatal("accepted modified runtime")
	}
}
