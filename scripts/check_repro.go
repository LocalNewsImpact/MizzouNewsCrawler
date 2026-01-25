package main

import (
	"encoding/hex"
	"fmt"
	"io/ioutil"
	"log"
	"os"

	"crypto/ecdh"
	"crypto/mlkem"
)

func mustReadAny(paths ...string) (string, []byte) {
	for _, p := range paths {
		if _, err := os.Stat(p); err == nil {
			b, err := ioutil.ReadFile(p)
			if err != nil {
				log.Fatalf("read %s: %v", p, err)
			}
			return p, b
		}
	}
	log.Fatalf("none of the candidate paths found: %v", paths)
	return "", nil
}

func parseServerHelloKeyShare(resp []byte) (ciphertext []byte, serverPub []byte, err error) {
	if len(resp) < 20 {
		return nil, nil, fmt.Errorf("response too short")
	}
	if resp[0] != 0x16 || resp[5] != 0x02 {
		return nil, nil, fmt.Errorf("not a ServerHello record")
	}
	hsStart := 5 + 4
	off := hsStart + 2 + 32
	if off >= len(resp) {
		return nil, nil, fmt.Errorf("truncated after offsets")
	}
	sidlen := int(resp[off])
	off += 1 + sidlen
	// skip cipher (2) and compression (1)
	off += 2
	off += 1
	if off+2 > len(resp) {
		return nil, nil, fmt.Errorf("no ext length")
	}
	extTotal := int(resp[off])<<8 | int(resp[off+1])
	off += 2
	endExt := off + extTotal
	for off+4 <= endExt && off+4 <= len(resp) {
		if off+4 > len(resp) {
			break
		}
		eid := int(resp[off])<<8 | int(resp[off+1])
		elen := int(resp[off+2])<<8 | int(resp[off+3])
		if off+4+elen > len(resp) {
			break
		}
		data := resp[off+4 : off+4+elen]
		if eid == 51 {
			if len(data) < 4 {
				return nil, nil, fmt.Errorf("malformed keyshare ext")
			}
			group := int(data[0])<<8 | int(data[1])
			klen := int(data[2])<<8 | int(data[3])
			if 4+klen > len(data) {
				return nil, nil, fmt.Errorf("key share length mismatch")
			}
			keybytes := data[4 : 4+klen]
			if group == 0x11ec {
				if klen < 32 {
					return nil, nil, fmt.Errorf("keybytes too small")
				}
				ciphertext = keybytes[:len(keybytes)-32]
				serverPub = keybytes[len(keybytes)-32:]
				return ciphertext, serverPub, nil
			}
		}
		off += 4 + elen
	}
	return nil, nil, fmt.Errorf("no ML-KEM KeyShare found")
}

func hexPref(b []byte, n int) string {
	if len(b) < n {
		n = len(b)
	}
	return hex.EncodeToString(b[:n])
}

func main() {
	// candidate paths (prefer package-local testdata where tests expect them)
	seedPath, seed := mustReadAny("testdata/probe_mlkem_seed.bin", "utls/testdata/probe_mlkem_seed.bin", "third_party/utls/testdata/probe_mlkem_seed.bin")
	fmt.Println("Using seed from:", seedPath)
	ctPath, _ := mustReadAny("testdata/probe_ciphertext.bin", "utls/testdata/probe_ciphertext.bin", "third_party/utls/testdata/probe_ciphertext.bin")
	fmt.Println("Using ciphertext from:", ctPath)
	privPath, priv := mustReadAny("testdata/probe_client_x25519_priv.bin", "utls/testdata/probe_client_x25519_priv.bin", "third_party/utls/testdata/probe_client_x25519_priv.bin")
	fmt.Println("Using client priv from:", privPath)
	respPath, resp := mustReadAny("testdata/probe_response.bin", "utls/testdata/probe_response.bin", "third_party/utls/testdata/probe_response.bin")
	fmt.Println("Using response from:", respPath)

	// parse server pub from response
	ciphertext, serverPub, err := parseServerHelloKeyShare(resp)
	if err != nil {
		log.Fatalf("failed to parse ServerHello keyshare: %v", err)
	}
	fmt.Printf("parsed ciphertext len=%d serverPub_len=%d\n", len(ciphertext), len(serverPub))

	// Decapsulate
	dec, err := mlkem.NewDecapsulationKey768(seed)
	if err != nil {
		log.Fatalf("mlkem.NewDecapsulationKey768: %v", err)
	}
	mlShared, err := dec.Decapsulate(ciphertext)
	if err != nil {
		log.Fatalf("Decapsulate failed: %v", err)
	}
	fmt.Printf("mlkemShared len=%d prefix=%s\n", len(mlShared), hexPref(mlShared, 16))

	// ECDHE shared
	clientPriv, err := ecdh.X25519().NewPrivateKey(priv)
	if err != nil {
		log.Fatalf("NewPrivateKey failed: %v", err)
	}
	peerPubKey, err := ecdh.X25519().NewPublicKey(serverPub)
	if err != nil {
		log.Fatalf("NewPublicKey failed: %v", err)
	}
	ecdheShared, err := clientPriv.ECDH(peerPubKey)
	if err != nil {
		log.Fatalf("ECDH failed: %v", err)
	}
	fmt.Printf("ecdheShared len=%d prefix=%s\n", len(ecdheShared), hexPref(ecdheShared, 16))

	combined := append(mlShared, ecdheShared...)
	fmt.Printf("combined len=%d prefix=%s\n", len(combined), hexPref(combined, 16))
	fmt.Println("Success: decap + ECDHE produced combined secret")
}
