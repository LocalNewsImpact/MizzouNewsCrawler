#!/usr/bin/env python3
"""Simple TLS ClientHello parser for quick diffs.

Usage: scripts/parse_clienthello_simple.py <file> [file...]

Outputs JSON with version, cipher_suites, extensions (id, len, hex preview), and key_shares if present.
"""
import sys
import struct
import json

EXT_NAMES = {
    0: "server_name",
    5: "status_request",
    10: "supported_groups",
    11: "ec_point_formats",
    13: "signature_algorithms",
    16: "alpn",
    18: "sct",
    21: "padding",
    22: "encrypt_then_mac",
    23: "extended_master_secret",
    27: "compress_certificate",
    35: "session_ticket",
    43: "supported_versions",
    45: "psk_key_exchange_modes",
    51: "key_share",
    57: "client_cert_type",
    16: "alpn",
}


def u16(b, i):
    return (b[i] << 8) | b[i+1]


def parse_clienthello_bytes(b):
    orig = b
    # If b begins with TLS record header (0x16 0x03 XX), find handshake inside
    if len(b) >= 5 and b[0] == 0x16 and b[1] == 0x03:
        rec_len = u16(b, 3)
        if 5 + rec_len <= len(b):
            # Use first record
            b = b[5:5+rec_len]
        else:
            # fallback: search for first 0x01 handshake type
            idx = b.find(b"\x01")
            if idx != -1:
                b = b[idx:]
    # Now expect handshake: type(1) + length(3)
    if len(b) < 4 or b[0] != 0x01:
        raise ValueError("Not a ClientHello handshake")
    hl = (b[1] << 16) | (b[2] << 8) | b[3]
    if 4 + hl > len(b):
        # maybe record header stripped in other way; try to find 0x01
        idx = orig.find(b"\x01")
        if idx != -1 and idx + 4 + ((orig[idx+1]<<16)|(orig[idx+2]<<8)|orig[idx+3]) <= len(orig):
            b = orig[idx:]
            hl = (b[1] << 16) | (b[2] << 8) | b[3]
            if 4 + hl > len(b):
                raise ValueError("Truncated handshake")
        else:
            raise ValueError("Truncated or invalid handshake")
    off = 4
    # client_version
    if off + 2 > len(b):
        raise ValueError("no version")
    version = (b[off] << 8) | b[off+1]
    off += 2
    # random
    rnd = b[off:off+32]
    off += 32
    # session id
    if off >= len(b):
        raise ValueError("no session id len")
    sid_len = b[off]
    off += 1
    sid = b[off:off+sid_len]
    off += sid_len
    # cipher suites
    if off + 2 > len(b):
        raise ValueError("no cipher suites len")
    cs_len = u16(b, off)
    off += 2
    cs = []
    for i in range(0, cs_len, 2):
        if off + i + 2 > len(b):
            break
        cs.append(u16(b, off + i))
    off += cs_len
    # compression methods
    if off >= len(b):
        raise ValueError("no comp len")
    comp_len = b[off]
    off += 1
    comp = b[off:off+comp_len]
    off += comp_len
    # extensions
    exts = []
    if off + 2 <= len(b):
        ext_total_len = u16(b, off)
        off += 2
        ext_end = off + ext_total_len
        while off + 4 <= ext_end and off + 4 <= len(b):
            ext_type = u16(b, off)
            ext_len = u16(b, off+2)
            off += 4
            if off + ext_len > len(b):
                # truncated
                ext_data = b[off:len(b)]
                off = len(b)
            else:
                ext_data = b[off:off+ext_len]
                off += ext_len
            ext = {"id": ext_type, "id_hex": f"0x{ext_type:04x}", "name": EXT_NAMES.get(ext_type, ""), "len": ext_len, "data_preview": ext_data[:16].hex()}
            # parse key_share extension specially
            if ext_type == 51:
                ks = []
                if len(ext_data) >= 2:
                    list_len = u16(ext_data, 0)
                    pos = 2
                    while pos + 4 <= len(ext_data):
                        group = u16(ext_data, pos)
                        pos += 2
                        key_len = u16(ext_data, pos)
                        pos += 2
                        key = ext_data[pos:pos+key_len]
                        pos += key_len
                        ks.append({"group": group, "group_hex": f"0x{group:04x}", "key_len": key_len, "key_preview": key[:16].hex()})
                ext["key_shares"] = ks
            # parse supported_groups / curves
            if ext_type == 10:
                curves = []
                pos = 0
                if len(ext_data) >= 2:
                    list_len = u16(ext_data, 0)
                    pos = 2
                    while pos + 2 <= len(ext_data):
                        curves.append(u16(ext_data, pos))
                        pos += 2
                ext["curves"] = curves
            if ext_type == 11:
                # Supported Points (elliptic point formats)
                pts = []
                if len(ext_data) >= 1:
                    l = ext_data[0]
                    pos = 1
                    for i in range(l):
                        if pos + i < len(ext_data):
                            pts.append(ext_data[pos + i])
                ext["points"] = pts
            exts.append(ext)
    info = {"version": f"0x{version:04x}", "cipher_suites": cs, "cipher_suites_hex": [f"0x{c:04x}" for c in cs], "extensions": exts}
    return info


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    out = {}
    for p in sys.argv[1:]:
        try:
            b = open(p, "rb").read()
        except Exception as e:
            out[p] = {"error": str(e)}
            continue
        try:
            info = parse_clienthello_bytes(b)
            out[p] = info
        except Exception as e:
            out[p] = {"error": str(e)}
    print(json.dumps(out, indent=2))

if __name__ == '__main__':
    main()
