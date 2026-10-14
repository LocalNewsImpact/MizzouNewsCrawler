"""Every plain-HTTP request through the relay reaches Squid authenticated.

The relay injects `Proxy-Authorization` into the first request head of a
connection and pipes the rest through untouched. Measured 2026-10-14 from the
api pod, three GETs on one relay connection to the production Squid:
200, 407, 407. Chrome keeps plain-HTTP proxy connections alive, so every
request after the first was unauthenticated; the 407 opened Chrome's
proxy-login dialog, and a modal dialog freezes chromedriver. Logins on
chinookobserver.com, www.wenatcheeworld.com and both McClatchy homepages
ended in `DriverUnresponsive`.

The fake here behaves like Squid: it keeps a connection alive, answers each
request on it, and requires Basic auth on every one.
"""

from __future__ import annotations

import base64
import socket
import threading

import pytest

from src.crawler.proxy_relay import ProxyAuthRelay

USER, PASSWORD = "mizzoucrawler", "s3kr3t"
TOKEN = base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()


class KeepAliveSquid:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.requests: list[bytes] = []
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        buf = b""
        try:
            while True:
                while b"\r\n\r\n" not in buf:
                    chunk = conn.recv(4096)
                    if not chunk:
                        return
                    buf += chunk
                head, buf = buf.split(b"\r\n\r\n", 1)
                self.requests.append(head)
                lower = head.decode("latin-1").lower()
                if f"proxy-authorization: basic {TOKEN}".lower() in lower:
                    conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
                else:
                    conn.sendall(
                        b"HTTP/1.1 407 Proxy Authentication Required\r\n"
                        b"Content-Length: 0\r\n\r\n"
                    )
                if "connection: close" in lower:
                    return
        except OSError:
            pass
        finally:
            conn.close()

    def stop(self):
        self.sock.close()


@pytest.fixture
def squid():
    s = KeepAliveSquid()
    yield s
    s.stop()


@pytest.fixture
def relay(squid):
    r = ProxyAuthRelay(f"http://{USER}:{PASSWORD}@127.0.0.1:{squid.port}")
    r.start()
    yield r
    r.stop()


GET = b"GET http://ads.example/pixel.gif HTTP/1.1\r\nHost: ads.example\r\nProxy-Connection: keep-alive\r\n\r\n"


def _read_response(sock) -> bytes:
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            return data
        data += chunk
    head, body = data.split(b"\r\n\r\n", 1)
    length = 0
    for line in head.split(b"\r\n"):
        if line.lower().startswith(b"content-length:"):
            length = int(line.split(b":", 1)[1])
    while len(body) < length:
        body += sock.recv(4096)
    return head


class TestPlainHttp:
    def test_a_request_ends_its_connection(self, relay):
        """After one response the relay closes the connection, so the browser
        has to open a new one -- and a new one is authenticated."""
        host, port = relay.proxy_url.split(":")
        with socket.create_connection((host, int(port)), timeout=5) as sock:
            sock.sendall(GET)
            assert _read_response(sock).startswith(b"HTTP/1.1 200")
            sock.settimeout(5)
            assert sock.recv(4096) == b"", "connection stayed open for a second request"

    def test_every_request_the_browser_sends_is_authenticated(self, relay, squid):
        """Three requests, as a browser makes them: a new connection each time
        the last one is closed. None reaches Squid without credentials."""
        host, port = relay.proxy_url.split(":")
        statuses = []
        for _ in range(3):
            with socket.create_connection((host, int(port)), timeout=5) as sock:
                sock.sendall(GET)
                statuses.append(_read_response(sock).split(b"\r\n", 1)[0])
        assert statuses == [b"HTTP/1.1 200 OK"] * 3
        assert len(squid.requests) == 3
        assert all(b"Proxy-Authorization: Basic" in r for r in squid.requests)

    def test_the_close_replaces_the_browsers_keep_alive(self, relay):
        head = relay._with_auth(GET)
        lines = [line.lower() for line in head.split(b"\r\n")]
        assert lines.count(b"connection: close") == 1
        assert lines.count(b"proxy-connection: close") == 1
        assert not any(b"keep-alive" in line for line in lines)
        assert head.endswith(b"\r\n\r\n") and not head.endswith(b"\r\n\r\n\r\n")
        assert head.startswith(b"GET http://ads.example/pixel.gif HTTP/1.1\r\n")


class TestHttpsTunnels:
    def test_a_connect_is_left_as_it_was(self, relay):
        """One request per connection already; nothing to close."""
        head = relay._with_auth(
            b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n"
            b"Proxy-Connection: keep-alive\r\n\r\n"
        )
        assert b"Connection: close" not in head
        assert b"Proxy-Connection: keep-alive" in head
        assert head.count(b"Proxy-Authorization: Basic") == 1


class TestWithoutCredentials:
    def test_an_unauthenticated_upstream_is_passed_through_unchanged(self, squid):
        """No credentials, nothing to inject -- and nothing else is rewritten."""
        r = ProxyAuthRelay(f"http://127.0.0.1:{squid.port}")
        assert r._with_auth(GET) == GET
