#!/usr/bin/env python3
import sys

def dump_records(path):
    b = open(path, 'rb').read()
    i = 0
    recno = 0
    while i+5 <= len(b):
        typ = b[i]
        ver = (b[i+1]<<8) | b[i+2]
        length = (b[i+3]<<8) | b[i+4]
        i += 5
        recno += 1
        data = b[i:i+length]
        print(f"Record {recno}: type=0x{typ:02x} ver=0x{ver:04x} len={length}")
        if typ == 0x16:
            # handshake frames inside
            j = 0
            while j+4 <= len(data):
                hs_type = data[j]
                hs_len = (data[j+1]<<16) | (data[j+2]<<8) | data[j+3]
                print(f"  Handshake: type=0x{hs_type:02x} len={hs_len} (offset {j})")
                # For ServerHello (0x02), try to print key_share extension summary
                if hs_type == 0x02:
                    # parse ServerHello as in parseServerHelloSummary
                    hs_start = j+4
                    off = hs_start + 2 + 32
                    if off+1 <= len(data):
                        sidlen = data[off]
                        off += 1 + sidlen
                        cipher = (data[off]<<8) | data[off+1]
                        off += 2
                        off += 1
                        extTotal = (data[off]<<8) | data[off+1]
                        off += 2
                        endExt = off + extTotal
                        selectedKS = -1
                        while off+4 <= endExt and off+4 <= len(data):
                            eid = (data[off]<<8)|data[off+1]
                            elen = (data[off+2]<<8)|data[off+3]
                            if eid == 51 and off+4+elen <= len(data):
                                d = data[off+4:off+4+elen]
                                if len(d) >= 2:
                                    selectedKS = (d[0]<<8) | d[1]
                            off += 4+elen
                        print(f"    ServerHello: cipher=0x{cipher:04x} selectedKS=0x{selectedKS:04x}")
                j += 4 + hs_len
        elif typ == 0x15:
            # alert
            if len(data) >= 2:
                print(f"  Alert: level={data[0]} desc={data[1]}")
        i += length

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('usage: dump_tls_records.py handshake_response.bin')
        sys.exit(1)
    dump_records(sys.argv[1])
