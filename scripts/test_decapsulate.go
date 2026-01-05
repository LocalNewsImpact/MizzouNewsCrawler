package main

import (
	"crypto/mlkem"
	"encoding/hex"
	"flag"
	"fmt"
	"os"
)

func main() {
	seedFile := flag.String("seed", "/tmp/probe_mlkem_seed.bin", "path to mlkem seed file")
	ctFile := flag.String("ciphertext", "/tmp/probe_ciphertext.bin", "path to ciphertext file (mlkem ciphertext)")
	flag.Parse()

	seed, err := os.ReadFile(*seedFile)
	if err != nil {
		fmt.Fprintf(os.Stderr, "failed reading seed file: %v\n", err)
		os.Exit(2)
	}
	ct, err := os.ReadFile(*ctFile)
	if err != nil {
		fmt.Fprintf(os.Stderr, "failed reading ciphertext file: %v\n", err)
		os.Exit(2)
	}
	dec, err := mlkem.NewDecapsulationKey768(seed)
	if err != nil {
		fmt.Fprintf(os.Stderr, "failed creating decapsulation key: %v\n", err)
		os.Exit(2)
	}
	secret, err := dec.Decapsulate(ct)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Decapsulate failed: %v\n", err)
		os.Exit(3)
	}
	fmt.Printf("Decapsulation success: secret_len=%d prefix=%s\n", len(secret), hex.EncodeToString(secret)[:64])
}
