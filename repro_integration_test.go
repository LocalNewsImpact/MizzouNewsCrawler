package main

import (
	"os"
	"testing"
	tlsmod "github.com/refraction-networking/utls"
)

func TestReproFromTestdataWrapper(t *testing.T) {
	// Run only when artifacts exist in repo-root testdata/
	if _, err := os.Stat("testdata/probe_mlkem_seed.bin"); err != nil {
		t.Skip("probe seed artifact not present; skip reproduction test")
	}
	if _, err := os.Stat("testdata/probe_client_x25519_priv.bin"); err != nil {
		t.Skip("probe client private not present; run a sweep with --save-ephemeral to capture it")
	}
	if _, err := os.Stat("testdata/probe_response.bin"); err != nil {
		t.Skip("probe response not present; skip reproduction test")
	}

	if err := tlsmod.ReproFromTestdata(); err != nil {
		t.Fatalf("ReproFromTestdata failed: %v", err)
	}
}
