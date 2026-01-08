#!/usr/bin/env python3
"""Extract extensions (id + raw data) from a ClientHello binary and write JSON list with order.

Usage: scripts/extract_extensions_raw.py <clienthello.bin> <out.json>
"""
import sys
import json

if len(sys.argv) < 3:
    print(__doc__)
    sys.exit(2)

infile = sys.argv[1]
outfile = sys.argv[2]

b = open(infile,'rb').read()
# strip TLS record if present
if len(b) >= 5 and b[0] == 0x16 and b[1] == 0x03:
    rec_len = (b[3]<<8)|b[4]
    if 5 + rec_len <= len(b):
        b = b[5:5+rec_len]

if len(b) < 4 or b[0] != 0x01:
    print('not a clienthello handshake')
    sys.exit(1)
hl = (b[1]<<16)|(b[2]<<8)|b[3]
off = 4
# skip version(2)+random(32)
off += 2 + 32
sidlen = b[off]
off += 1 + sidlen
cslen = (b[off]<<8)|b[off+1]
off += 2 + cslen
complen = b[off]
off += 1 + complen
ext_total = (b[off]<<8)|b[off+1]
off += 2
ext_end = off + ext_total
exts = []
pos = off
while pos + 4 <= ext_end:
    eid = (b[pos]<<8) | b[pos+1]
    elen = (b[pos+2]<<8) | b[pos+3]
    data = b[pos+4: pos+4+elen]
    exts.append({'id': eid, 'data_hex': data.hex()})
    pos = pos + 4 + elen

open(outfile, 'w').write(json.dumps(exts, indent=2))
print('wrote', outfile, 'with', len(exts), 'extensions')
