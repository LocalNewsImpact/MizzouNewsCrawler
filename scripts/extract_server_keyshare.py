#!/usr/bin/env python3
import sys

def extract_keyshare(resp_path):
    b = open(resp_path, 'rb').read()
    if len(b) < 5:
        print('short file')
        return
    recType = b[0]
    if recType != 0x16:
        print(f'record type 0x{recType:02x} not handshake')
        return
    if len(b) < 9:
        print('too short')
        return
    hsType = b[5]
    if hsType != 0x02:
        print(f'handshake type 0x{hsType:02x} != ServerHello')
        return
    hsStart = 5 + 4
    off = hsStart + 2 + 32
    sidlen = b[off]
    off += 1 + sidlen
    cipher = (b[off] << 8) | b[off+1]
    off += 2
    off += 1
    extTotal = (b[off] << 8) | b[off+1]
    off += 2
    endExt = off + extTotal
    print('cipher=0x%04x extTotal=%d' % (cipher, extTotal))
    while off+4 <= endExt and off+4 <= len(b):
        eid = (b[off] << 8) | b[off+1]
        elen = (b[off+2] << 8) | b[off+3]
        data = b[off+4:off+4+elen]
        print(f'ext id={eid} len={elen}')
        if eid == 51:
            print('FOUND KeyShare ext, first 10 bytes:', data[:10].hex())
            # parse KeyShareEntry list
            # For ServerHello, the extension contains a single KeyShareEntry: group(2), key_exchange length(2), key_exchange(bytes)
            if len(data) >= 4:
                group = (data[0] << 8) | data[1]
                klen = (data[2] << 8) | data[3]
                print(f'group=0x{group:04x} klen={klen} total ext len={len(data)}')
                keybytes = data[4:4+klen]
                print('keybytes len', len(keybytes))
                print('first 32 bytes:', keybytes[:32].hex())
                print('last 32 bytes:', keybytes[-32:].hex())
        off += 4 + elen

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('usage: extract_server_keyshare.py probe_response.bin')
        sys.exit(1)
    extract_keyshare(sys.argv[1])
