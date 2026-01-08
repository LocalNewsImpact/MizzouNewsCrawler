#!/usr/bin/env python3
"""Serve a recorded TLS server response (raw bytes) on a TCP port for local replay/testing.

Usage: python3 scripts/replay_serverhello.py /path/to/probe_response.bin --port 8443

The script will listen on 127.0.0.1:<port> and, for each incoming connection, send the raw bytes
from the given file and then close the connection (one-shot). Use --loop to serve repeatedly.
"""

import argparse
import socket
import sys


def main():
    p = argparse.ArgumentParser(description="Replay a recorded ServerHello/TLS response")
    p.add_argument("file", help="path to recorded server response (probe_response.bin)")
    p.add_argument("--port", type=int, default=8443, help="port to listen on (default 8443)")
    p.add_argument("--loop", action="store_true", help="continue serving after each connection")
    args = p.parse_args()

    try:
        data = open(args.file, "rb").read()
    except Exception as e:
        print(f"Error reading file {args.file}: {e}")
        sys.exit(2)

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", args.port))
    srv.listen(5)
    print(f"Serving {args.file} on 127.0.0.1:{args.port}; loop={args.loop}")

    try:
        while True:
            conn, addr = srv.accept()
            print(f"Connection from {addr}; sending {len(data)} bytes")
            try:
                conn.sendall(data)
            except Exception as e:
                print(f"send failed: {e}")
            finally:
                conn.close()
            if not args.loop:
                break
    except KeyboardInterrupt:
        print("Interrupted; exiting")
    finally:
        srv.close()


if __name__ == '__main__':
    main()
