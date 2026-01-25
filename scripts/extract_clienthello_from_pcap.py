#!/usr/bin/env python3
"""Extract the first TLS ClientHello from a pcap and write raw handshake and record bytes.

Usage: scripts/extract_clienthello_from_pcap.py <pcap> [out_prefix]

Writes:
  <out_prefix>.bin       - raw ClientHello handshake bytes (starts with 0x01 ...)
  <out_prefix>.rec       - TLS record header + record bytes (starts with 0x16 0x03 0x03 ...)
  <out_prefix>.bin.hex   - hex dump
  <out_prefix>.rec.hex   - hex dump

This is intentionally small and defensive to avoid fragile dependencies.
"""
import sys
import dpkt
import socket


def ip_to_str(ip_bytes):
    try:
        return socket.inet_ntop(socket.AF_INET, ip_bytes)
    except Exception:
        try:
            return socket.inet_ntop(socket.AF_INET6, ip_bytes)
        except Exception:
            return repr(ip_bytes)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    pcap_path = sys.argv[1]
    out_prefix = sys.argv[2] if len(sys.argv) > 2 else "artifacts/chrome_clienthello"

    flows = {}

    with open(pcap_path, "rb") as f:
        pcap = dpkt.pcap.Reader(f)
        for ts, buf in pcap:
            ip = None
            # try Ethernet style
            try:
                eth = dpkt.ethernet.Ethernet(buf)
                inner = eth.data
                if isinstance(inner, dpkt.ip.IP):
                    ip = inner
                    src = ip_to_str(ip.src)
                    dst = ip_to_str(ip.dst)
                elif isinstance(inner, dpkt.ip6.IP6):
                    ip = inner
                    src = socket.inet_ntop(socket.AF_INET6, inner.src)
                    dst = socket.inet_ntop(socket.AF_INET6, inner.dst)
                elif isinstance(inner, bytes):
                    # sometimes eth.data is raw bytes; attempt to parse as IP
                    try:
                        ip4 = dpkt.ip.IP(inner)
                        ip = ip4
                        src = ip_to_str(ip.src)
                        dst = ip_to_str(ip.dst)
                    except Exception:
                        try:
                            ip6 = dpkt.ip6.IP6(inner)
                            ip = ip6
                            src = socket.inet_ntop(socket.AF_INET6, ip.src)
                            dst = socket.inet_ntop(socket.AF_INET6, ip.dst)
                        except Exception:
                            pass
            except Exception:
                pass
            # try Linux cooked (SLL) style
            if ip is None:
                try:
                    sll = dpkt.sll.SLL(buf)
                    inner = sll.data
                    if isinstance(inner, dpkt.ip.IP):
                        ip = inner
                        src = ip_to_str(ip.src)
                        dst = ip_to_str(ip.dst)
                    elif isinstance(inner, dpkt.ip6.IP6):
                        ip = inner
                        src = socket.inet_ntop(socket.AF_INET6, inner.src)
                        dst = socket.inet_ntop(socket.AF_INET6, inner.dst)
                    elif isinstance(inner, bytes):
                        try:
                            ip4 = dpkt.ip.IP(inner)
                            ip = ip4
                            src = ip_to_str(ip.src)
                            dst = ip_to_str(ip.dst)
                        except Exception:
                            try:
                                ip6 = dpkt.ip6.IP6(inner)
                                ip = ip6
                                src = socket.inet_ntop(socket.AF_INET6, ip.src)
                                dst = socket.inet_ntop(socket.AF_INET6, ip.dst)
                            except Exception:
                                pass
                except Exception:
                    pass
            if ip is None:
                continue
            # detect TCP (IPv4 and IPv6 differ slightly)
            proto = getattr(ip, 'p', None)
            if proto is None:
                proto = getattr(ip, 'nxt', None)
            if proto != dpkt.ip.IP_PROTO_TCP:
                continue
            tcp = ip.data
            data = tcp.data
            if not data:
                continue
            key = (src, dst, tcp.sport, tcp.dport)
            entry = (tcp.seq, data)
            flows.setdefault(key, []).append(entry)

    # Try both directions for any flow
    for key, segments in flows.items():
        src, dst, sport, dport = key
        # build stream by seq numbers with simple reassembly
        if not segments:
            continue
        # normalize seqs to unsigned
        seqs = [s for s, d in segments]
        base = min(seqs)
        # sort by seq adjusted for overflow
        def norm_seq(s):
            if s >= base:
                return s - base
            else:
                return (s + (1 << 32) - base)
        segments_sorted = sorted(segments, key=lambda sd: norm_seq(sd[0]))
        stream = bytearray()
        for seq, data in segments_sorted:
            offset = norm_seq(seq)
            if offset > len(stream):
                stream.extend(b"\x00" * (offset - len(stream)))
            if offset + len(data) > len(stream):
                stream.extend(b"\x00" * (offset + len(data) - len(stream)))
            # Overwrite is fine; initial handshake will be contiguous
            stream[offset:offset+len(data)] = data

        # helper: search for TLS record header + ClientHello (handshake type 1) in a byte stream
        def find_clienthello_in_stream(stream_bytes):
            L = len(stream_bytes)
            for i in range(0, max(0, L - 8)):
                # Accept any TLS minor version (e.g., 0x0301, 0x0303). Some captures show 0x0301.
                if stream_bytes[i] == 0x16 and stream_bytes[i+1] == 0x03:
                    if i + 4 >= L:
                        continue
                    rec_len = (stream_bytes[i+3] << 8) | stream_bytes[i+4]
                    if i + 5 + rec_len > L:
                        # record not fully present in this stream slice
                        continue
                    # handshake starts at i+5
                    if i + 5 >= L:
                        continue
                    if stream_bytes[i+5] != 0x01:
                        # not a client hello handshake message
                        continue
                    # handshake length
                    if i + 8 >= L:
                        continue
                    hl = (stream_bytes[i+6] << 16) | (stream_bytes[i+7] << 8) | stream_bytes[i+8]
                    total_handshake_len = 4 + hl
                    if i + 5 + total_handshake_len > L:
                        continue
                    client_hello = stream_bytes[i+5:i+5+total_handshake_len]
                    rec_bytes = stream_bytes[i:i+5+rec_len]
                    return client_hello, rec_bytes, i
            return None, None, None

        # Try reassembled-by-seq stream first (best effort)
        client_hello, rec_bytes, offset = find_clienthello_in_stream(stream)
        if client_hello is None:
            # Fallback: try concatenating payloads in packet order (less strict, often works for captures)
            ordered_stream = bytearray()
            for seq, data in segments:
                ordered_stream.extend(data)
            client_hello, rec_bytes, offset = find_clienthello_in_stream(ordered_stream)

        if client_hello is not None:
            # write outputs
            with open(out_prefix + ".bin", "wb") as ob:
                ob.write(client_hello)
            with open(out_prefix + ".rec", "wb") as orf:
                orf.write(rec_bytes)
            with open(out_prefix + ".bin.hex", "w") as obh:
                obh.write(client_hello.hex())
            with open(out_prefix + ".rec.hex", "w") as orh:
                orh.write(rec_bytes.hex())
            print(f"Found ClientHello in flow {src}:{sport} -> {dst}:{dport} at offset {offset}; wrote {out_prefix}.bin")
            return 0
    print("No ClientHello found in pcap")
    return 1


if __name__ == '__main__':
    sys.exit(main())
