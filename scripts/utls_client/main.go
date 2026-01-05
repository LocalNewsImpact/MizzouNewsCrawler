package main

import (
	"bufio"
	"crypto/md5"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"reflect"
	"strconv"
	"strings"
	"time"

	"crypto/ecdh"
	"crypto/mlkem"
	"crypto/rand"
	"golang.org/x/crypto/curve25519"

	utls "github.com/refraction-networking/utls"
)

var preparedKeyShare *utls.KeySharePrivateKeys
var forceMLKEM bool
var forceMLKEMOnly bool
var probeOutDir string
var saveEphemeral bool

func parseJA3(s string) (version uint16, ciphers []uint16, exts []int, curves []utls.CurveID, points []uint8, err error) {
	parts := strings.Split(s, ",")
	if len(parts) != 5 {
		err = fmt.Errorf("invalid ja3 format")
		return
	}
	vi, _ := strconv.Atoi(parts[0])
	version = uint16(vi)
	for _, p := range strings.Split(parts[1], "-") {
		if p == "" {
			continue
		}
		v, _ := strconv.Atoi(p)
		ciphers = append(ciphers, uint16(v))
	}
	for _, p := range strings.Split(parts[2], "-") {
		if p == "" {
			continue
		}
		v, _ := strconv.Atoi(p)
		exts = append(exts, v)
	}
	for _, p := range strings.Split(parts[3], "-") {
		if p == "" {
			continue
		}
		v, _ := strconv.Atoi(p)
		curves = append(curves, utls.CurveID(v))
	}
	for _, p := range strings.Split(parts[4], "-") {
		if p == "" {
			continue
		}
		v, _ := strconv.Atoi(p)
		points = append(points, uint8(v))
	}
	return
}

func extByID(id int, serverName string, curves []utls.CurveID) utls.TLSExtension {
	switch id {
	case 0:
		return &utls.SNIExtension{ServerName: serverName}
	case 5:
		// status_request: empty struct
		return &utls.StatusRequestExtension{}
	case 10:
		// Prepend GREASE groups (0x0a0a, 0x11ec) to match Chrome's supported_groups ordering
		grease := []utls.CurveID{utls.CurveID(0x0a0a), utls.CurveID(0x11ec)}
		var combined []utls.CurveID
		combined = append(combined, grease...)
		if forceMLKEMOnly {
			// Strict ML-KEM only: remove plain X25519 from the supported groups entirely
			seen := map[utls.CurveID]bool{}
			for _, g := range combined {
				seen[g] = true
			}
			if !seen[utls.X25519MLKEM768] {
				combined = append(combined, utls.X25519MLKEM768)
				seen[utls.X25519MLKEM768] = true
			}
			for _, c := range curves {
				if c == utls.X25519 {
					// omit plain X25519 in strict mode
					continue
				}
				if !seen[c] {
					combined = append(combined, c)
					seen[c] = true
				}
			}
		} else if forceMLKEM {
			// Bias supported groups toward ML-KEM first (avoid duplicates)
			seen := map[utls.CurveID]bool{}
			for _, g := range combined {
				seen[g] = true
			}
			if !seen[utls.X25519MLKEM768] {
				combined = append(combined, utls.X25519MLKEM768)
				seen[utls.X25519MLKEM768] = true
			}
			for _, c := range curves {
				if !seen[c] {
					combined = append(combined, c)
					seen[c] = true
				}
			}
		} else {
			combined = append(combined, curves...)
		}
		return &utls.SupportedCurvesExtension{Curves: combined}
	case 11:
		return &utls.SupportedPointsExtension{SupportedPoints: []uint8{0}}
	case 13:
		// signature_algorithms -- provide a minimal, valid payload: length(2) + algorithm(0x0403)
		// encoded as uint16 length followed by algorithms
		return &utls.GenericExtension{Id: uint16(13), Data: []byte{0x00, 0x02, 0x04, 0x03}}
	case 16:
		return &utls.ALPNExtension{AlpnProtocols: []string{"h2", "http/1.1"}}
	case 23:
		return &utls.ExtendedMasterSecretExtension{}
	case 27:
		// compress certificate: send empty list
		return &utls.GenericExtension{Id: uint16(27), Data: []byte{0x00}}
	case 35:
		return &utls.SessionTicketExtension{}
	case 65037:
		// ECH placeholder to match JA3 presence (empty payload)
		return &utls.GenericExtension{Id: uint16(65037), Data: []byte{}}
	case 17613:
		// Application settings (BoringSSL codepoint) placeholder
		return &utls.GenericExtension{Id: uint16(17613), Data: []byte{}}
	case 43:
		// Include GREASE version 0xfafa before real versions to match Chrome observed behavior
		return &utls.SupportedVersionsExtension{Versions: []uint16{uint16(0xfafa), utls.VersionTLS13, utls.VersionTLS12}}
	case 45:
		// psk_key_exchange_modes: 1 byte length + mode 1 (psk_dhe_ke)
		return &utls.GenericExtension{Id: uint16(45), Data: []byte{0x01, 0x01}}
	case 51:
		// Build key shares to mimic Chrome: prepend GREASE key shares (0x0a0a, 0x11ec) as 1-byte placeholders,
		// then include the requested curves (X25519 with a real public, others with 32-byte placeholders).
		var keyShares []utls.KeyShare
		// GREASE groups observed in Chrome
		keyShares = append(keyShares, utls.KeyShare{Group: utls.CurveID(0x0a0a), Data: []byte{0x00}})
		keyShares = append(keyShares, utls.KeyShare{Group: utls.CurveID(0x11ec), Data: []byte{0x00}}) // When forcing ML-KEM, add an explicit ML-KEM keyshare early to bias server selection
		if forceMLKEM {
			seed := make([]byte, mlkem.SeedSize)
			if _, err := rand.Read(seed); err == nil {
				if mlkemKey, err := mlkem.NewDecapsulationKey768(seed); err == nil {
					if ecdhePriv, err := ecdh.X25519().GenerateKey(rand.Reader); err == nil {
						encKey := mlkemKey.EncapsulationKey().Bytes()
						ecdhePub := ecdhePriv.PublicKey().Bytes()
						log.Println("Generated ML-KEM keyshare (force-mlkem): encKey_len=", len(encKey), "ecdhePub_len=", len(ecdhePub), "total=", len(encKey)+len(ecdhePub))
						keyShares = append(keyShares, utls.KeyShare{Group: utls.X25519MLKEM768, Data: append(encKey, ecdhePub...)})
						if preparedKeyShare == nil {
							preparedKeyShare = &utls.KeySharePrivateKeys{
								CurveID:    utls.X25519MLKEM768,
								Ecdhe:      ecdhePriv,
								Mlkem:      mlkemKey,
								MlkemEcdhe: ecdhePriv,
							}
						} else {
							preparedKeyShare.CurveID = utls.X25519MLKEM768
							preparedKeyShare.Ecdhe = ecdhePriv
							preparedKeyShare.Mlkem = mlkemKey
							preparedKeyShare.MlkemEcdhe = ecdhePriv
						}
						// Persist seed for offline decapsulation reproduction
						if err := os.WriteFile("/tmp/probe_mlkem_seed.bin", seed, 0600); err == nil {
							log.Println("Wrote mlkem seed to /tmp/probe_mlkem_seed.bin")
							// Optionally persist ephemeral private key for reproducibility (debug only)
							if saveEphemeral {
								if err := os.WriteFile("/tmp/probe_client_x25519_priv.bin", ecdhePriv.Bytes(), 0600); err == nil {
									log.Println("Wrote client ephemeral private key to /tmp/probe_client_x25519_priv.bin")
								}
							}

								// Optionally persist ephemeral private key for reproducibility (debug only)
								if saveEphemeral {
									if err := os.WriteFile("/tmp/probe_client_x25519_priv.bin", ecdhePriv.Bytes(), 0600); err == nil {
										log.Println("Wrote client ephemeral private key to /tmp/probe_client_x25519_priv.bin")
									}
								}

							// Optionally persist ephemeral private key for reproducibility (debug only)
							if saveEphemeral {
								if err := os.WriteFile("/tmp/probe_client_x25519_priv.bin", ecdhePriv.Bytes(), 0600); err == nil {
									log.Println("Wrote client ephemeral private key to /tmp/probe_client_x25519_priv.bin")
								}
							}

						}
					}
				}
			}
		}
		for _, c := range curves {
			switch c {
			case utls.X25519MLKEM768:
				// Generate ML-KEM decapsulation key and an X25519 ephemeral key for the hybrid share
				seed := make([]byte, mlkem.SeedSize)
				if _, err := rand.Read(seed); err == nil {
					if mlkemKey, err := mlkem.NewDecapsulationKey768(seed); err == nil {
						if ecdhePriv, err := ecdh.X25519().GenerateKey(rand.Reader); err == nil {
							encKey := mlkemKey.EncapsulationKey().Bytes()
							ecdhePub := ecdhePriv.PublicKey().Bytes()
							log.Println("Generated ML-KEM keyshare: encKey_len=", len(encKey), "ecdhePub_len=", len(ecdhePub), "total=", len(encKey)+len(ecdhePub))
							keyShares = append(keyShares, utls.KeyShare{Group: c, Data: append(encKey, ecdhePub...)})
							// record private keys so the handshake can decapsulate server key shares
							if preparedKeyShare == nil {
								preparedKeyShare = &utls.KeySharePrivateKeys{
									CurveID:    utls.X25519MLKEM768,
									Mlkem:      mlkemKey,
									MlkemEcdhe: ecdhePriv,
								}
								// Persist seed alongside probe artifacts for deterministic offline decapsulation
								if probeOutDir != "" {
									seedPath := filepath.Join(probeOutDir, "probe_mlkem_seed.bin")
									if err := os.WriteFile(seedPath, seed, 0600); err == nil {
										log.Println("Wrote mlkem seed to", seedPath)
									}
								}
								// Persist seed for offline decapsulation reproduction
								if err := os.WriteFile("/tmp/probe_mlkem_seed.bin", seed, 0600); err == nil {
									log.Println("Wrote mlkem seed to /tmp/probe_mlkem_seed.bin")
							// Optionally persist ephemeral private key for reproducibility (debug only)
							if saveEphemeral {
								if err := os.WriteFile("/tmp/probe_client_x25519_priv.bin", ecdhePriv.Bytes(), 0600); err == nil {
									log.Println("Wrote client ephemeral private key to /tmp/probe_client_x25519_priv.bin")
								}
							}

								// Optionally persist ephemeral private key for reproducibility (debug only)
								if saveEphemeral {
									if err := os.WriteFile("/tmp/probe_client_x25519_priv.bin", ecdhePriv.Bytes(), 0600); err == nil {
										log.Println("Wrote client ephemeral private key to /tmp/probe_client_x25519_priv.bin")
									}
								}

								}
							} else {
								preparedKeyShare.CurveID = utls.X25519MLKEM768
								preparedKeyShare.Mlkem = mlkemKey
								preparedKeyShare.MlkemEcdhe = ecdhePriv
							}
							// Persist seed for offline decapsulation reproduction
							if err := os.WriteFile("/tmp/probe_mlkem_seed.bin", seed, 0600); err == nil {
								log.Println("Wrote mlkem seed to /tmp/probe_mlkem_seed.bin")
							// Optionally persist ephemeral private key for reproducibility (debug only)
							if saveEphemeral {
								if err := os.WriteFile("/tmp/probe_client_x25519_priv.bin", ecdhePriv.Bytes(), 0600); err == nil {
									log.Println("Wrote client ephemeral private key to /tmp/probe_client_x25519_priv.bin")
								}
							}

							}
						}
					}
				}
			case utls.X25519:
				if forceMLKEM {
					log.Println("force-mlkem: skipping X25519 key share")
					continue
				}
				pub, err := makeX25519Pub()
				if err != nil {
					keyShares = append(keyShares, utls.KeyShare{Group: c, Data: nil})
				} else {
					keyShares = append(keyShares, utls.KeyShare{Group: c, Data: pub})
				}
			default:
				// fallback to 32-byte random placeholder for unknown groups
				b := make([]byte, 32)
				if _, err := rand.Read(b); err != nil {
					b = []byte{0x00}
				}
				keyShares = append(keyShares, utls.KeyShare{Group: c, Data: b})
			}
		}
		return &utls.KeyShareExtension{KeyShares: keyShares}
	default:
		// Generic extension with empty payload (safe fallback)
		return &utls.GenericExtension{Id: uint16(id), Data: []byte{}}
	}
}

func makeX25519Pub() ([]byte, error) {
	priv := make([]byte, 32)
	if _, err := rand.Read(priv); err != nil {
		return nil, err
	}
	pub, err := curve25519.X25519(priv, curve25519.Basepoint)
	if err != nil {
		return nil, err
	}
	return pub, nil
}

// patchFirstCipher sets the first cipher suite in the ClientHello to GREASE 0x9a9a
func patchFirstCipher(raw []byte) ([]byte, bool) {
	b := make([]byte, len(raw))
	copy(b, raw)
	var innerOff int
	var inner []byte
	if len(b) >= 5 && b[0] == 0x16 && b[1] == 0x03 {
		recLen := int(b[3])<<8 | int(b[4])
		if 5+recLen <= len(b) {
			innerOff = 5
			inner = b[innerOff : innerOff+recLen]
		} else {
			// fallback to treating b as handshake-only
			inner = b
			innerOff = 0
		}
	} else {
		inner = b
		innerOff = 0
	}
	// validate handshake
	if len(inner) < 4 || inner[0] != 0x01 {
		return b, false
	}
	off := 4
	if off+2+32 >= len(inner) {
		return b, false
	}
	off += 2 + 32
	if off >= len(inner) {
		return b, false
	}
	sidlen := int(inner[off])
	off += 1 + sidlen
	if off+2 > len(inner) {
		return b, false
	}
	_ = int(inner[off])<<8 | int(inner[off+1])
	csOff := off + 2
	if csOff+2 > len(inner) {
		return b, false
	}
	current := uint16(inner[csOff])<<8 | uint16(inner[csOff+1])
	if current == 0x9a9a {
		return b, false
	}
	absIdx := innerOff + csOff
	b[absIdx] = 0x9a
	b[absIdx+1] = 0x9a
	return b, true
}

// wrapTLSRecordIfNeeded wraps a handshake-only ClientHello in a TLS record header if necessary
func wrapTLSRecordIfNeeded(b []byte) []byte {
	if len(b) >= 5 && b[0] == 0x16 && b[1] == 0x03 {
		return b
	}
	n := len(b)
	header := []byte{0x16, 0x03, 0x03, byte((n >> 8) & 0xff), byte(n & 0xff)}
	return append(header, b...)
}

// parseServerHelloSummary inspects the server response and returns a short human-readable summary
func parseServerHelloSummary(resp []byte) string {
	if len(resp) < 5 {
		return fmt.Sprintf("short response (%d bytes)", len(resp))
	}
	recType := resp[0]
	switch recType {
	case 0x15:
		if len(resp) >= 7 {
			return fmt.Sprintf("Alert level=%d desc=%d", resp[5], resp[6])
		}
		return "Alert (short)"
	case 0x16:
		if len(resp) < 9 {
			return "Handshake (too short)"
		}
		hsType := resp[5]
		if hsType != 0x02 {
			return fmt.Sprintf("Handshake type 0x%02x", hsType)
		}
		hsStart := 5 + 4
		if hsStart+2+32 >= len(resp) {
			return "ServerHello truncated"
		}
		off := hsStart + 2 + 32
		if off >= len(resp) {
			return "ServerHello truncated"
		}
		sidlen := int(resp[off])
		off += 1 + sidlen
		if off+2 > len(resp) {
			return "ServerHello truncated"
		}
		cipher := int(resp[off])<<8 | int(resp[off+1])
		off += 2
		if off+1 > len(resp) {
			return fmt.Sprintf("ServerHello: cipher=0x%04x", cipher)
		}
		_ = resp[off]
		off += 1
		if off+2 > len(resp) {
			return fmt.Sprintf("ServerHello: cipher=0x%04x comp=??", cipher)
		}
		extTotal := int(resp[off])<<8 | int(resp[off+1])
		off += 2
		endExt := off + extTotal
		selectedKS := -1
		for off+4 <= endExt && off+4 <= len(resp) {
			eid := int(resp[off])<<8 | int(resp[off+1])
			elen := int(resp[off+2])<<8 | int(resp[off+3])
			if eid == 51 && off+4+elen <= len(resp) {
				d := resp[off+4 : off+4+elen]
				if len(d) >= 2 {
					selectedKS = int(d[0])<<8 | int(d[1])
				}
			}
			off += 4 + elen
		}
		if selectedKS != -1 {
			return fmt.Sprintf("ServerHello cipher=0x%04x selected_key_share=0x%04x", cipher, selectedKS)
		}
		return fmt.Sprintf("ServerHello cipher=0x%04x", cipher)
	default:
		return fmt.Sprintf("Record type 0x%02x", recType)
	}
}

// extractKeyShareFromServerHello parses a raw TLS record sequence and tries to locate a
// ServerHello and its key_share extension. Returns (found, group, keyExchange, summary, truncated)
// - found: true if key_share extension present and keyExchange returned
// - group: group id of key_share (if found, else -1)
// - keyExchange: raw key_exchange bytes from ServerHello key_share
// - summary: a short human-readable summary (like parseServerHelloSummary)
// - truncated: true if the input appears incomplete and more bytes might be needed
func extractKeyShareFromServerHello(resp []byte) (bool, int, []byte, string, bool) {
	pos := 0
	for pos+5 <= len(resp) {
		recType := int(resp[pos])
		recLen := int(resp[pos+3])<<8 | int(resp[pos+4])
		if pos+5+recLen > len(resp) {
			// truncated record
			return false, -1, nil, parseServerHelloSummary(resp), true
		}
		payload := resp[pos+5 : pos+5+recLen]
		switch recType {
		case 0x15:
			// Alert
			if len(payload) >= 2 {
				return false, -1, nil, fmt.Sprintf("Alert level=%d desc=%d", payload[0], payload[1]), false
			}
			return false, -1, nil, "Alert (short)", false
		case 0x16:
			hsPos := 0
			for hsPos+4 <= len(payload) {
				hsType := payload[hsPos]
				hsLen := int(payload[hsPos+1])<<16 | int(payload[hsPos+2])<<8 | int(payload[hsPos+3])
				if hsPos+4+hsLen > len(payload) {
					return false, -1, nil, parseServerHelloSummary(resp), true
				}
				if hsType == 0x02 { // ServerHello
					sh := payload[hsPos+4 : hsPos+4+hsLen]
					// minimal ServerHello: legacy_version(2) + random(32) + session_id_len(1)
					if len(sh) < 38 {
						return false, -1, nil, "ServerHello truncated", true
					}
					off := 2 + 32
					if off+1 > len(sh) {
						return false, -1, nil, "ServerHello truncated", true
					}
					sidLen := int(sh[off])
					off += 1 + sidLen
					if off+2 > len(sh) {
						return false, -1, nil, "ServerHello truncated", true
					}
					cipher := int(sh[off])<<8 | int(sh[off+1])
					off += 2
					if off+1 > len(sh) {
						return false, -1, nil, fmt.Sprintf("ServerHello: cipher=0x%04x", cipher), true
					}
					off += 1 // compression
					if off+2 > len(sh) {
						return false, -1, nil, fmt.Sprintf("ServerHello: cipher=0x%04x", cipher), true
					}
					extTotal := int(sh[off])<<8 | int(sh[off+1])
					off += 2
					if off+extTotal > len(sh) {
						return false, -1, nil, "ServerHello truncated", true
					}
					endExt := off + extTotal
					extPos := off
					for extPos+4 <= endExt {
						eid := int(sh[extPos])<<8 | int(sh[extPos+1])
						elen := int(sh[extPos+2])<<8 | int(sh[extPos+3])
						if extPos+4+elen > endExt {
							return false, -1, nil, "ServerHello truncated", true
						}
						ed := sh[extPos+4 : extPos+4+elen]
						if eid == 51 {
							// KeyShare extension (ServerHello contains a single KeyShareEntry)
							if len(ed) < 4 {
								return false, -1, nil, "ServerHello key_share truncated", true
							}
							grp := int(ed[0])<<8 | int(ed[1])
							klen := int(ed[2])<<8 | int(ed[3])
							if 4+klen > len(ed) {
								return false, grp, nil, "ServerHello key_exchange truncated", true
							}
							keyex := ed[4 : 4+klen]
							summary := fmt.Sprintf("ServerHello cipher=0x%04x selected_key_share=0x%04x", cipher, grp)
							return true, grp, keyex, summary, false
						}
						extPos += 4 + elen
					}
					// No key_share present in this ServerHello
					summary := fmt.Sprintf("ServerHello cipher=0x%04x", cipher)
					return false, -1, nil, summary, false
				}
				hsPos += 4 + hsLen
			}
		default:
			// ignore other record types
		}
		pos += 5 + recLen
	}
	// If we reach here, the buffer may be incomplete
	return false, -1, nil, parseServerHelloSummary(resp), true
}


func buildSpecFromJA3(ja3 string, serverName string) (*utls.ClientHelloSpec, error) {
	_, ciphers, exts, curves, _, err := parseJA3(ja3)
	if err != nil {
		return nil, err
	}

	var cipherSuites []uint16
	for _, c := range ciphers {
		cipherSuites = append(cipherSuites, c)
	}

	spec := &utls.ClientHelloSpec{
		TLSVersMin:   utls.VersionTLS12,
		TLSVersMax:   utls.VersionTLS13,
		CipherSuites: cipherSuites,
		Extensions:   []utls.TLSExtension{},
	}

	// add extensions in the order given by JA3 (do not filter ECH/renegotiation)
	for _, e := range exts {
		ext := extByID(e, serverName, curves)
		if ext != nil {
			spec.Extensions = append(spec.Extensions, ext)
		}
	}

	// ensure SNI present if not declared in JA3 (prepend)
	hasSNI := false
	for _, e := range exts {
		if e == 0 {
			hasSNI = true
			break
		}
	}
	if !hasSNI {
		spec.Extensions = append([]utls.TLSExtension{&utls.SNIExtension{ServerName: serverName}}, spec.Extensions...)
	}

	return spec, nil
}

func main() {
	var ja3 string
	var extsFlag string
	var targetURL string
	var server string
	var debug bool
	var noSpec bool
	var helloPreset string
	var applyPreset string

	flag.StringVar(&ja3, "ja3", "", "JA3 string to apply (version,ciphers,extensions,curves,points)")
	flag.StringVar(&extsFlag, "exts", "", "optional: comma/dash-separated extension IDs to use instead of JA3 extensions")
	flag.StringVar(&targetURL, "url", "https://tools.scrapfly.io/api/fp/ja3", "URL to GET after handshake")
	flag.StringVar(&server, "server", "", "server name for SNI (default from URL)")
	flag.BoolVar(&debug, "debug", false, "print debug info")
	// Default to noSpec=true so running the binary with no flags uses a builtin Hello preset
	flag.BoolVar(&noSpec, "no-spec", true, "use a built-in Hello preset instead of applying a custom ClientHelloSpec")
	flag.StringVar(&helloPreset, "hello", "chrome_120", "hello preset to use when --no-spec is set (e.g., chrome_120, chrome_115, chrome_100)")
	flag.StringVar(&applyPreset, "apply-preset", "", "if set, generate a ClientHelloSpec from the named utls preset (e.g., chrome_120) and apply it (forces --no-spec=false)")
	// When true, include ECH (65037) and 65281 extension IDs in the generated spec. Disabled by default because
	// including placeholder ECH data can cause handshake failures on some servers; use for debugging/matching only.
	var includeECH bool
	flag.BoolVar(&includeECH, "include-ech", false, "include ECH (65037) and 65281 in the custom spec (dangerous for handshake)")
	// Allow building a spec directly from a raw ClientHello (e.g., a captured Chrome ClientHello bin).
	// Useful for iterating toward an exact byte-for-byte match without guessing individual fields.
	var rawSpecFile string
	flag.StringVar(&rawSpecFile, "raw-spec-file", "", "path to raw ClientHello bin to use as the source spec (debug only)")
	var rawExtFile string
	flag.StringVar(&rawExtFile, "raw-ext-file", "", "path to a JSON file containing ordered extension id and raw data pairs (debug only)")
	// Force ML-KEM advertisement: omit plain X25519 key shares and bias supported_groups to ML-KEM
	flag.BoolVar(&forceMLKEM, "force-mlkem", false, "force advertise only ML-KEM keyshare (increase chance server selects X25519MLKEM768)")
	// Strict mode: remove X25519 from supported_groups entirely and only advertise ML-KEM
	flag.BoolVar(&forceMLKEMOnly, "force-mlkem-only", false, "force strict ML-KEM only: remove X25519 from supported_groups and omit plain X25519 keyshare")
	// Probe-only mode: send ClientHello and report ServerHello/Alert without attempting full handshake
	var probeOnly bool
	var probeTimeoutSec int
	flag.BoolVar(&probeOnly, "probe-only", false, "send ClientHello and report ServerHello/Alert only (no TLS handshake)")
	flag.IntVar(&probeTimeoutSec, "probe-timeout", 5, "probe socket read timeout in seconds")
	flag.StringVar(&probeOutDir, "probe-out-dir", "", "directory to write probe artifacts (default /tmp)")
	// Debug option: persist ephemeral client private keys into probe-out-dir on ML-KEM successes (debug only)
	var saveEphemeral bool
	flag.BoolVar(&saveEphemeral, "save-ephemeral", false, "write ephemeral client private keys to probe-out-dir (debug only)")
	flag.Parse()

	// If strict ML-KEM-only mode requested, also enable the broader force-mlkem
	if forceMLKEMOnly {
		forceMLKEM = true
	}

	if ja3 == "" && applyPreset == "" {
		log.Fatal("--ja3 required (or use --apply-preset)")
	}
	u, err := url.Parse(targetURL)
	if err != nil {
		log.Fatal(err)
	}
	host := u.Hostname()
	if server == "" {
		server = host
	}

	// parse base JA3 to extract ciphers & curves; we'll optionally override extensions
	var parsedExts []int
	var curves []utls.CurveID
	var ciphers []uint16
	if ja3 != "" {
		_, ciphers, parsedExts, curves, _, err = parseJA3(ja3)
		if err != nil {
			log.Fatal(err)
		}
	}

	var extIDs []int
	if extsFlag != "" {
		// accept comma-separated or dash-separated lists
		sep := ","
		if strings.Contains(extsFlag, "-") && !strings.Contains(extsFlag, ",") {
			sep = "-"
		}
		parts := strings.Split(extsFlag, sep)
		for _, p := range parts {
			p = strings.TrimSpace(p)
			if p == "" {
				continue
			}
			v, _ := strconv.Atoi(p)
			extIDs = append(extIDs, v)
		}
	} else {
		extIDs = parsedExts
	}

	spec := &utls.ClientHelloSpec{
		TLSVersMin:   utls.VersionTLS12,
		TLSVersMax:   utls.VersionTLS13,
		CipherSuites: ciphers,
		Extensions:   []utls.TLSExtension{},
	}

	// If a raw ClientHello file is provided, parse it into a ClientHelloSpec and use it directly.
	if rawSpecFile != "" {
		b, err := os.ReadFile(rawSpecFile)
		if err != nil {
			log.Fatalf("failed reading raw spec file: %v", err)
		}
		f := utls.Fingerprinter{}
		rspec, err := f.RawClientHello(b)
		if err != nil {
			log.Fatalf("failed parsing raw clienthello: %v", err)
		}
		spec = rspec
		if debug {
			log.Println("Using ClientHelloSpec constructed from raw file:", rawSpecFile)
		}
	}

	// If a raw extensions JSON file is provided, use those exact extensions (id + data) in order.
	var rawExtIDs map[int]bool
	rawExtProvided := false
	if rawExtFile != "" {
		rb, err := os.ReadFile(rawExtFile)
		if err != nil {
			log.Fatalf("failed reading raw extensions file: %v", err)
		}
		var exts []struct {
			Id      int    `json:"id"`
			DataHex string `json:"data_hex"`
		}
		if err := json.Unmarshal(rb, &exts); err != nil {
			log.Fatalf("failed parsing raw extensions json: %v", err)
		}
		// replace spec.Extensions with exact GenericExtension entries and collect their IDs
		spec.Extensions = []utls.TLSExtension{}
		rawExtIDs = make(map[int]bool)
		for _, e := range exts {
			data, _ := hex.DecodeString(e.DataHex)
			if e.Id == 51 {
				// KeyShare extension: replace raw bytes with a generated KeyShareExtension that
				// includes ML-KEM/X25519 entries so we can complete a TLS handshake (we will
				// also store the private keys in preparedKeyShare for the handshake state).
				var keyShares []utls.KeyShare
				keyShares = append(keyShares, utls.KeyShare{Group: utls.CurveID(0x0a0a), Data: []byte{0x00}})
				keyShares = append(keyShares, utls.KeyShare{Group: utls.CurveID(0x11ec), Data: []byte{0x00}})
				seed := make([]byte, mlkem.SeedSize)
				if _, err := rand.Read(seed); err == nil {
					if mlkemKey, err := mlkem.NewDecapsulationKey768(seed); err == nil {
						if ecdhePriv, err := ecdh.X25519().GenerateKey(rand.Reader); err == nil {
							encKey := mlkemKey.EncapsulationKey().Bytes()
							ecdhePub := ecdhePriv.PublicKey().Bytes()
							log.Println("Generated ML-KEM keyshare (raw-ext path): encKey_len=", len(encKey), "ecdhePub_len=", len(ecdhePub), "total=", len(encKey)+len(ecdhePub))
							keyShares = append(keyShares, utls.KeyShare{Group: utls.X25519MLKEM768, Data: append(encKey, ecdhePub...)})
							preparedKeyShare = &utls.KeySharePrivateKeys{
								CurveID:    utls.X25519MLKEM768,
								Mlkem:      mlkemKey,
								MlkemEcdhe: ecdhePriv,
							}
							// Persist seed to probe-out-dir for deterministic offline decapsulation if provided
							if probeOutDir != "" {
								seedPath := filepath.Join(probeOutDir, "probe_mlkem_seed.bin")
								if err := os.WriteFile(seedPath, seed, 0600); err == nil {
									log.Println("Wrote mlkem seed to", seedPath)
								}
							}
						}
					}
				}
				// also add a plain X25519 share for compatibility (skip when forcing ML-KEM)
				if !forceMLKEM {
					if pub, err := makeX25519Pub(); err == nil {
						keyShares = append(keyShares, utls.KeyShare{Group: utls.X25519, Data: pub})
					}
				}
				spec.Extensions = append(spec.Extensions, &utls.KeyShareExtension{KeyShares: keyShares})
				rawExtIDs[e.Id] = true
			} else if e.Id == 10 && forceMLKEMOnly {
				// Override raw supported_groups with a strict ML-KEM-only ordering (omit X25519)
				grease := []utls.CurveID{utls.CurveID(0x0a0a), utls.CurveID(0x11ec)}
				var combined []utls.CurveID
				combined = append(combined, grease...)
				seen := map[utls.CurveID]bool{}
				for _, g := range combined {
					seen[g] = true
				}
				if !seen[utls.X25519MLKEM768] {
					combined = append(combined, utls.X25519MLKEM768)
					seen[utls.X25519MLKEM768] = true
				}
				for _, c := range curves {
					if c == utls.X25519 {
						continue
					}
					if !seen[c] {
						combined = append(combined, c)
						seen[c] = true
					}
				}
				spec.Extensions = append(spec.Extensions, &utls.SupportedCurvesExtension{Curves: combined})
				rawExtIDs[e.Id] = true
			} else {
				spec.Extensions = append(spec.Extensions, &utls.GenericExtension{Id: uint16(e.Id), Data: data})
				rawExtIDs[e.Id] = true
			}
		}
		rawExtProvided = true
		if debug {
			log.Println("Using raw extensions from:", rawExtFile)
		}
	}

	if debug {
		log.Println("using extension IDs:", extIDs)
		if rawExtProvided {
			ids := []int{}
			for k := range rawExtIDs {
				ids = append(ids, k)
			}
			log.Println("raw extension IDs provided:", ids)
		}
	}

	// filter/construct extensions using extByID (we still filter ECH & renegotiation by default)
	filtered := []int{}
	for _, e := range extIDs {
		// By default we avoid adding ECH/65281 (they can be sensitive), but allow including them
		// when --include-ech is explicitly set for debugging/JA3 matching.
		if !includeECH && (e == 65037 || e == 65281) {
			continue
		}
		filtered = append(filtered, e)
	}
	// If a raw clienthello or raw extensions file was supplied, avoid double-adding those extension IDs
	if rawSpecFile == "" {
		for _, e := range filtered {
			if rawExtProvided && rawExtIDs != nil && rawExtIDs[e] {
				if debug {
					log.Printf("Skipping extension %d because supplied in raw-ext-file", e)
				}
				continue
			}
			ext := extByID(e, server, curves)
			if ext != nil {
				spec.Extensions = append(spec.Extensions, ext)
			}
		}
	} else {
		if debug {
			log.Println("Skipping automatic extension construction because raw clienthello spec was provided")
		}
	}

	// Ensure the GREASE cipher 0x9a9a appears at the front of the cipher list to match Chrome ordering.
	// This forces the first suite to 39578 (0x9a9a) but avoids duplication if already present.
	greaseCipher := uint16(39578)
	if len(spec.CipherSuites) == 0 || spec.CipherSuites[0] != greaseCipher {
		newSuites := []uint16{greaseCipher}
		for _, cs := range spec.CipherSuites {
			if cs == greaseCipher {
				continue
			}
			newSuites = append(newSuites, cs)
		}
		spec.CipherSuites = newSuites
	}

	if debug {
		buf, _ := json.MarshalIndent(spec, "", "  ")
		fmt.Println(string(buf))
	}

	// Dial and use uTLS with custom ClientHelloSpec
	addr := host + ":443"
	dialer := &net.Dialer{Timeout: 10 * time.Second}
	conn, err := dialer.Dial("tcp", addr)
	if err != nil {
		log.Fatal(err)
	}
	defer conn.Close()

	config := &utls.Config{ServerName: server}
	var uconn *utls.UConn
	if applyPreset != "" {
		// generate spec from named preset and apply it (forces spec application path)
		var presetSpec utls.ClientHelloSpec
		switch strings.ToLower(applyPreset) {
		case "chrome_120":
			presetSpec, _ = utls.UTLSIdToSpec(utls.HelloChrome_120)
		case "chrome_115":
			presetSpec, _ = utls.UTLSIdToSpec(utls.HelloChrome_115_PQ)
		case "chrome_100":
			presetSpec, _ = utls.UTLSIdToSpec(utls.HelloChrome_100)
		default:
			presetSpec, _ = utls.UTLSIdToSpec(utls.HelloRandomized)
		}
		uconn = utls.UClient(conn, config, utls.HelloCustom)
		if err := applyClientHelloSpec(uconn, &presetSpec, debug); err != nil {
			log.Println("applyClientHelloSpec failed for preset:", err)
		} else {
			log.Println("Applied preset-based ClientHelloSpec")
		}
	} else if noSpec {
		// select Hello preset (map common names to available utls presets)
		switch strings.ToLower(helloPreset) {
		case "chrome_120":
			uconn = utls.UClient(conn, config, utls.HelloChrome_120)
		case "chrome_115":
			uconn = utls.UClient(conn, config, utls.HelloChrome_115_PQ)
		case "chrome_100":
			uconn = utls.UClient(conn, config, utls.HelloChrome_100)
		default:
			uconn = utls.UClient(conn, config, utls.HelloRandomized)
		}
		log.Println("Using builtin Hello preset, skipping ClientHelloSpec application")
	} else {
		uconn = utls.UClient(conn, config, utls.HelloCustom)
		// set the custom ClientHelloSpec on the connection
		if err := applyClientHelloSpec(uconn, spec, debug); err != nil {
			log.Println("applyClientHelloSpec failed:", err)
		} else {
			log.Println("ClientHelloSpec applied")
		}
	}

	// If debug is enabled, try to marshal the ClientHello and print a short hexdump of what will
	// be sent to the server to aid debugging of malformed extensions.
	if debug {
		rv := reflect.ValueOf(uconn)
		// try MarshalClientHelloNoECH first
		if m := rv.MethodByName("MarshalClientHelloNoECH"); m.IsValid() {
			if res := m.Call(nil); len(res) == 1 && !res[0].IsNil() {
				log.Println("MarshalClientHelloNoECH returned error:", res[0].Interface())
			}
		}
		// try to read outgoing bytes
		if m := rv.MethodByName("GetOutKeystream"); m.IsValid() {
			outs := m.Call([]reflect.Value{reflect.ValueOf(8192)})
			if len(outs) == 2 {
				if !outs[1].IsNil() {
					log.Println("GetOutKeystream error:", outs[1].Interface())
				} else {
					b := outs[0].Interface().([]byte)
					hexSnippet := hex.EncodeToString(b)
					if len(hexSnippet) > 800 {
						hexSnippet = hexSnippet[:800]
					}
					log.Println("ClientHello hex snippet:", hexSnippet)
				}
			}
		}

		// if MarshalClientHelloNoECH created hello raw, write it to /tmp
		if uconn.HandshakeState.Hello != nil && len(uconn.HandshakeState.Hello.Raw) > 0 {
			raw := uconn.HandshakeState.Hello.Raw
			// write raw bytes and hex to /tmp with mode in filename
			mode := "preset"
			if !noSpec {
				mode = "spec"
			}
			hexFile := fmt.Sprintf("/tmp/clienthello_%s.hex", mode)
			binFile := fmt.Sprintf("/tmp/clienthello_%s.bin", mode)
			if err := os.WriteFile(hexFile, []byte(hex.EncodeToString(raw)), 0644); err != nil {
				log.Println("Failed writing clienthello hex:", err)
			} else {
				log.Println("Wrote clienthello hex to", hexFile)
			}
			if err := os.WriteFile(binFile, raw, 0644); err != nil {
				log.Println("Failed writing clienthello bin:", err)
			} else {
				log.Println("Wrote clienthello bin to", binFile)
			}

			// Patch first cipher suite to GREASE 0x9a9a if needed
			patchedRaw, didPatch := patchFirstCipher(raw)
			probeDir := "/tmp"
			if probeOutDir != "" {
				probeDir = probeOutDir
			}
			if didPatch {
				uconn.HandshakeState.Hello.Raw = patchedRaw
				patchedHex := fmt.Sprintf("/tmp/clienthello_%s_patched.hex", mode)
				patchedBin := fmt.Sprintf("/tmp/clienthello_%s_patched.bin", mode)
				if err := os.WriteFile(patchedHex, []byte(hex.EncodeToString(patchedRaw)), 0644); err != nil {
					log.Println("Failed writing patched clienthello hex:", err)
				} else {
					log.Println("Wrote patched clienthello hex to", patchedHex)
				}
				if err := os.WriteFile(patchedBin, patchedRaw, 0644); err != nil {
					log.Println("Failed writing patched clienthello bin:", err)
				} else {
					log.Println("Wrote patched clienthello bin to", patchedBin)
				}
				// also write patched copies to probe dir if provided
				if probeOutDir != "" {
					probePatchedHex := filepath.Join(probeDir, fmt.Sprintf("clienthello_%s_patched.hex", mode))
					probePatchedBin := filepath.Join(probeDir, fmt.Sprintf("clienthello_%s_patched.bin", mode))
					if err := os.WriteFile(probePatchedHex, []byte(hex.EncodeToString(patchedRaw)), 0644); err != nil {
						log.Println("Failed writing patched clienthello hex to probe dir:", err)
					} else {
						log.Println("Wrote patched clienthello hex to", probePatchedHex)
					}
					if err := os.WriteFile(probePatchedBin, patchedRaw, 0644); err != nil {
						log.Println("Failed writing patched clienthello bin to probe dir:", err)
					} else {
						log.Println("Wrote patched clienthello bin to", probePatchedBin)
					}
				}
				log.Println("Patched ClientHello first cipher to 0x9a9a")
			}

			// write probe copies for inspection (default /tmp, override with --probe-out-dir)
			if err := os.WriteFile(filepath.Join(probeDir, "clienthello_probe.bin"), raw, 0644); err == nil {
				log.Println("Wrote clienthello probe bin to", filepath.Join(probeDir, "clienthello_probe.bin"))
			}
			if err := os.WriteFile(filepath.Join(probeDir, "clienthello_probe.hex"), []byte(hex.EncodeToString(raw)), 0644); err == nil {
				log.Println("Wrote clienthello probe hex to", filepath.Join(probeDir, "clienthello_probe.hex"))
			}

			// If probe-only mode is set, send ClientHello raw to server and parse response
			if probeOnly {
				toSend := uconn.HandshakeState.Hello.Raw
				wrapped := wrapTLSRecordIfNeeded(toSend)
				dialer := &net.Dialer{Timeout: time.Duration(probeTimeoutSec) * time.Second}
				connProbe, err := dialer.Dial("tcp", host+":443")
				if err != nil {
					log.Println("probe-only: dial error:", err)
				} else {
					defer connProbe.Close()
					connProbe.SetDeadline(time.Now().Add(time.Duration(probeTimeoutSec) * time.Second))
					if _, err := connProbe.Write(wrapped); err != nil {
						log.Println("probe-only: write error:", err)
					} else {
						buf := make([]byte, 65536)
						n, err := connProbe.Read(buf)
						if n > 0 {
							resp := buf[:n]
							if err := os.WriteFile(filepath.Join(probeDir, "probe_response.bin"), resp, 0644); err != nil {
								log.Println("probe-only: failed writing response to", filepath.Join(probeDir, "probe_response.bin"), ":", err)
							} else {
								log.Println("probe-only: wrote response to", filepath.Join(probeDir, "probe_response.bin"))
							}
							summary := parseServerHelloSummary(resp)
							log.Println("probe-only result:", summary) // If we prepared an ML-KEM key locally, attempt a simple in-process decapsulation
							if preparedKeyShare != nil && preparedKeyShare.Mlkem != nil {
								found := false
								for i := 0; i+4 <= len(resp); i++ {
									if resp[i] == 0x00 && resp[i+1] == 0x33 {
										elen := int(resp[i+2])<<8 | int(resp[i+3])
										if i+4+elen > len(resp) {
											continue
										}
										d := resp[i+4 : i+4+elen]
										if len(d) < 4 {
											continue
										}
										group := int(d[0])<<8 | int(d[1])
										klen := int(d[2])<<8 | int(d[3])
										if 4+klen > len(d) {
											continue
										}
										keyexchange := d[4 : 4+klen]
										log.Println("probe-only: found key_share ext group=0x", fmt.Sprintf("%x", group), "klen=", klen)
										if group == int(utls.X25519MLKEM768) {
											if len(keyexchange) >= mlkem.CiphertextSize768 {
												ciphertext := keyexchange[:mlkem.CiphertextSize768]
												secret, err := preparedKeyShare.Mlkem.Decapsulate(ciphertext)
												if err != nil {
													log.Println("probe-only: decapsulation failed:", err, "ciphertext_len=", len(ciphertext))
													if err := os.WriteFile(filepath.Join(probeDir, "probe_ciphertext.bin"), ciphertext, 0644); err == nil {
														log.Println("probe-only: wrote ciphertext to", filepath.Join(probeDir, "probe_ciphertext.bin"))
													}
												} else {
													log.Println("probe-only: decapsulation success: secret_len=", len(secret))
													if probeDir == "" {
														probeDir = "/tmp"
													}
													snippet := hex.EncodeToString(secret)
													if len(snippet) > 64 {
														snippet = snippet[:64]
													}
													if err := os.WriteFile(filepath.Join(probeDir, "probe_decap_secret.hex"), []byte(snippet), 0644); err == nil {
														log.Println("probe-only: wrote decap secret snippet to", filepath.Join(probeDir, "probe_decap_secret.hex"))
													}
												}
											} else {
												log.Println("probe-only: key exchange shorter than expected =", len(keyexchange), "expected mlkem.CiphertextSize768+32", mlkem.CiphertextSize768+32)
											}
										}
									}
								}
								if !found {
									// Did not find key_share ext; if ServerHello looks truncated, attempt one additional read
									if strings.Contains(parseServerHelloSummary(resp), "truncated") {
										more := make([]byte, 65536)
										mn, merr := connProbe.Read(more)
										if mn > 0 {
											resp = append(resp, more[:mn]...)
											if err := os.WriteFile(filepath.Join(probeDir, "probe_response.bin"), resp, 0644); err == nil {
												log.Println("probe-only: appended more response to", filepath.Join(probeDir, "probe_response.bin"))
											}
											log.Println("probe-only result:", parseServerHelloSummary(resp))
											// try to find key_share ext again
											for i := 0; i+4 <= len(resp); i++ {
												if resp[i] == 0x00 && resp[i+1] == 0x33 {
													elen := int(resp[i+2])<<8 | int(resp[i+3])
													if i+4+elen > len(resp) {
														continue
													}
													d := resp[i+4 : i+4+elen]
													if len(d) < 4 {
														continue
													}
													group := int(d[0])<<8 | int(d[1])
													klen := int(d[2])<<8 | int(d[3])
													if 4+klen > len(d) {
														continue
													}
													keyexchange := d[4 : 4+klen]
													log.Println("probe-only: found key_share ext group=0x", fmt.Sprintf("%x", group), "klen=", klen)
													if group == int(utls.X25519MLKEM768) {
														if len(keyexchange) >= mlkem.CiphertextSize768 {
															ciphertext := keyexchange[:mlkem.CiphertextSize768]
															secret, err := preparedKeyShare.Mlkem.Decapsulate(ciphertext)
															if err != nil {
																log.Println("probe-only: decapsulation failed:", err, "ciphertext_len=", len(ciphertext))
																if err := os.WriteFile(filepath.Join(probeDir, "probe_ciphertext.bin"), ciphertext, 0644); err == nil {
																	log.Println("probe-only: wrote ciphertext to", filepath.Join(probeDir, "probe_ciphertext.bin"))
																}
															} else {
																log.Println("probe-only: decapsulation success: secret_len=", len(secret))
																if probeDir == "" {
																	probeDir = "/tmp"
																}
																snippet := hex.EncodeToString(secret)
																if len(snippet) > 64 {
																	snippet = snippet[:64]
																}
																if err := os.WriteFile(filepath.Join(probeDir, "probe_decap_secret.hex"), []byte(snippet), 0644); err == nil {
																	log.Println("probe-only: wrote decap secret snippet to", filepath.Join(probeDir, "probe_decap_secret.hex"))
																}
														}
													} else {
														log.Println("probe-only: key exchange shorter than expected =", len(keyexchange), "expected mlkem.CiphertextSize768+32", mlkem.CiphertextSize768+32)
													}
													}
												}
											}
									} else if merr != nil {
										if ne, ok := merr.(net.Error); ok && ne.Timeout() {
											log.Println("probe-only: continuation read timeout")
										} else {
											log.Println("probe-only: continuation read error:", merr)
										}
									}
								} else {
									log.Println("probe-only: did not find key_share ext in ServerHello (or it was truncated)")
								}
								}
							}
						}
						if err != nil {
							if ne, ok := err.(net.Error); ok && ne.Timeout() {
								log.Println("probe-only: read timeout")
							} else {
								log.Println("probe-only: read error:", err)
							}
						}
					}
				}
				// print local computed JA3 and exit
				h := md5.Sum([]byte(ja3))
				fmt.Println("local ja3_md5:", hex.EncodeToString(h[:]))
				os.Exit(0)
			}
		}

		// If prepared ML-KEM keys were generated, attach them to HandshakeState so the
		// handshake implementation can access the private keys when the server selects
		// X25519MLKEM768 (group 0x11ec).
		if preparedKeyShare != nil {
			if uconn.HandshakeState.Hello != nil {
				if uconn.HandshakeState.State13.KeyShareKeys == nil {
					uconn.HandshakeState.State13.KeyShareKeys = preparedKeyShare
				} else {
					uconn.HandshakeState.State13.KeyShareKeys.Ecdhe = preparedKeyShare.Ecdhe
					uconn.HandshakeState.State13.KeyShareKeys.Mlkem = preparedKeyShare.Mlkem
					uconn.HandshakeState.State13.KeyShareKeys.MlkemEcdhe = preparedKeyShare.MlkemEcdhe
				}
				log.Println("Applied prepared ML-KEM KeySharePrivateKeys to HandshakeState")
			} else {
				log.Println("preparedKeyShare exists but uconn.HandshakeState.Hello is nil; cannot attach ML-KEM keys")
			}
		}

		if err := uconn.Handshake(); err != nil {
			log.Fatal("handshake failed:", err)
		}

		// Now use net/http over the connection (very small manual request)
		req, _ := http.NewRequest("GET", targetURL, nil)
		req.Header.Set("User-Agent", "utls-client/1.0")
		req.Header.Set("Accept", "*/*")

		// write the request
		if err := req.Write(uconn); err != nil {
			log.Fatal(err)
		}
		resp, err := http.ReadResponse(bufio.NewReader(uconn), req)
		if err != nil {
			log.Fatal(err)
		}
		defer resp.Body.Close()

		var out map[string]interface{}
		json.NewDecoder(resp.Body).Decode(&out)
		jsonOut, _ := json.MarshalIndent(out, "", "  ")
		fmt.Println(string(jsonOut))

		// print local computed JA3 from the spec
		// compute md5 of ja3 string
		h := md5.Sum([]byte(ja3))
		fmt.Println("local ja3_md5:", hex.EncodeToString(h[:]))
	}
}

// applyClientHelloSpec attempts multiple runtime strategies to set a custom ClientHello spec
// on the provided uconn. It uses reflection so the program compiles across utls versions that
// expose different methods (SetClientHelloSpec, MakeClientHello, ApplyPreset, etc.).
func applyClientHelloSpec(uconn *utls.UConn, spec *utls.ClientHelloSpec, debug bool) error {
	rv := reflect.ValueOf(uconn)
	if debug {
		for i := 0; i < rv.NumMethod(); i++ {
			m := rv.Type().Method(i)
			log.Printf("uconn method: %s -> %s", m.Name, m.Type)
		}
	}
	methodNames := []string{"SetTLSVers", "SetClientHelloSpec", "MakeClientHello", "ApplyPreset", "SetClientHello"}
	for _, name := range methodNames {
		m := rv.MethodByName(name)
		if !m.IsValid() {
			continue
		}
		// verify the method accepts 1 argument assignable from spec, or 0 args
		mt := m.Type()
		if mt.NumIn() == 1 {
			argType := mt.In(0)
			v := reflect.ValueOf(spec)
			// support value vs pointer parameter types
			if !v.Type().AssignableTo(argType) {
				if v.Kind() == reflect.Ptr && v.Elem().IsValid() && v.Elem().Type().AssignableTo(argType) {
					v = v.Elem()
				} else {
					// not compatible
					continue
				}
			}
			var callErr error
			func() {
				defer func() {
					if r := recover(); r != nil {
						callErr = fmt.Errorf("panic calling %s: %v", name, r)
					}
				}()
				outs := m.Call([]reflect.Value{v})
				for _, o := range outs {
					if o.Type().Implements(reflect.TypeOf((*error)(nil)).Elem()) {
						if !o.IsNil() {
							callErr = o.Interface().(error)
						}
					}
				}
			}()
			if callErr != nil {
				return fmt.Errorf("%s returned error: %w", name, callErr)
			}
			if debug {
				log.Printf("applied ClientHello using method %s", name)
			}
			return nil
		}
		if mt.NumIn() == 0 {
			// try calling a no-arg method
			var callErr error
			func() {
				defer func() {
					if r := recover(); r != nil {
						callErr = fmt.Errorf("panic calling %s: %v", name, r)
					}
				}()
				outs := m.Call(nil)
				for _, o := range outs {
					if o.Type().Implements(reflect.TypeOf((*error)(nil)).Elem()) {
						if !o.IsNil() {
							callErr = o.Interface().(error)
						}
					}
				}
			}()
			if callErr != nil {
				return fmt.Errorf("%s returned error: %w", name, callErr)
			}
			if debug {
				log.Printf("applied ClientHello using method %s (no-arg)", name)
			}
			return nil
		}
	}
	return fmt.Errorf("no supported method found to set ClientHelloSpec on UConn")
}
