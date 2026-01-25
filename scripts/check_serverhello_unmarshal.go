package main

import (
	"encoding/hex"
	"fmt"
	"io/ioutil"
	"log"

	"golang.org/x/crypto/cryptobyte"
)

func main() {
	p, _ := ioutil.ReadFile("testdata/probe_response.bin")
	if len(p) < 10 {
		log.Fatalf("response too short: %d", len(p))
	}
	fmt.Printf("first 8 bytes: %x\n", p[:8])
	data := p[5:]
	fmt.Printf("handshake first bytes: %x\n", data[:8])
	s := cryptobyte.String(data)
	if ok := s.Skip(4); !ok {
		log.Fatalf("Skip(4) failed")
	}
	var vers uint16
	if !s.ReadUint16(&vers) {
		log.Fatalf("ReadUint16 failed")
	}
	fmt.Printf("vers: 0x%04x\n", vers)
	var random []byte
	if !s.ReadBytes(&random, 32) {
		log.Fatalf("ReadBytes(random) failed, len remaining=%d", len(data))
	}
	fmt.Printf("random prefix: %s\n", hex.EncodeToString(random[:8]))
	var sessionId []byte
	if !readUint8LengthPrefixed(&s, &sessionId) {
		log.Fatalf("read session id failed")
	}
	fmt.Printf("sessionId len=%d\n", len(sessionId))
	var cipher uint16
	if !s.ReadUint16(&cipher) {
		log.Fatalf("read cipher failed")
	}
	fmt.Printf("cipher: 0x%04x\n", cipher)
	var comp uint8
	if !s.ReadUint8(&comp) {
		log.Fatalf("read compression failed")
	}
	fmt.Printf("compression: %d\n", comp)
	if s.Empty() {
		fmt.Println("No extensions")
		return
	}
	// Peek next 8 bytes to understand ext length field
	remaining := s
	b, _ := remaining.ReadBytes(8)
	fmt.Printf("next 8 bytes after compression: %x\n", b)

	var exts cryptobyte.String
	if !s.ReadUint16LengthPrefixed(&exts) || !s.Empty() {
		log.Fatalf("read extensions failed; afterReadFirst8=%x", b)
	}
	fmt.Printf("extensions bytes len=%d\n", len(exts))
	for !exts.Empty() {
		var ext uint16
		var ed cryptobyte.String
		if !exts.ReadUint16(&ext) || !exts.ReadUint16LengthPrefixed(&ed) {
			log.Fatalf("read ext failed")
		}
		fmt.Printf("ext id=0x%04x len=%d\n", ext, len(ed))
	}
}

func readUint8LengthPrefixed(s *cryptobyte.String, out *[]byte) bool {
	var l uint8
	if !s.ReadUint8(&l) {
		return false
	}
	var tmp []byte
	if !s.ReadBytes(&tmp, int(l)) {
		return false
	}
	*out = tmp
	return true
}
