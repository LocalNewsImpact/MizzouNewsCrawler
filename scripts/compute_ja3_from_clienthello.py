#!/usr/bin/env python3
"""Compute JA3 string and MD5 from a ClientHello binary (handshake bytes or record bytes).
"""
import sys
import json
from parse_clienthello_simple import parse_clienthello_bytes
import hashlib

if len(sys.argv) < 2:
    print("Usage: compute_ja3_from_clienthello.py <clienthello.bin>")
    sys.exit(2)

p = sys.argv[1]
try:
    b = open(p, 'rb').read()
except Exception as e:
    print('error reading file', e)
    sys.exit(1)
try:
    info = parse_clienthello_bytes(b)
except Exception as e:
    print('parse error', e)
    sys.exit(1)

# version as decimal
ver = int(info.get('version', '0x0303'), 16)
# ciphers
ciphers = info.get('cipher_suites', [])
# extensions order
exts = [e['id'] for e in info.get('extensions', [])]
# curves: find supported_groups extension if present
curves = []
for e in info.get('extensions', []):
    if e.get('id') == 10:
        curves = e.get('curves', [])
        break
# points
points = []
for e in info.get('extensions', []):
    if e.get('id') == 11:
        points = e.get('points', [])
        break

ja3 = f"{ver},{'-'.join(str(x) for x in ciphers)},{'-'.join(str(x) for x in exts)},{'-'.join(str(x) for x in curves)},{'-'.join(str(x) for x in points)}"
md5 = hashlib.md5(ja3.encode()).hexdigest()
out = { 'file': p, 'ja3': ja3, 'ja3_md5': md5 }
print(json.dumps(out, indent=2))
