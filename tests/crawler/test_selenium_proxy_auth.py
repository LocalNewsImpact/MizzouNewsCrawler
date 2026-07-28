"""Selenium must reach Squid *authenticated*, by a mechanism Chrome supports.

The outage these tests pin against (production, 2026-07-25 → 07-27): Chrome
cannot take proxy credentials on the command line, so the code shipped them in
a Manifest V2 extension answering ``chrome.webRequest.onAuthRequired``. Chrome
removed Manifest V2. By Chrome 150 the extension is ignored **silently** -- no
exception, no warning -- so every Selenium fetch hit the authenticated Squid
with no credentials, got 407, and returned a ~0.2s "navigation succeeded" on an
empty error page. Zero Selenium successes across ~500 attempts; stltoday.com
(Selenium-only, HTTP methods disabled) went to 100% failure with no fallback.

Nothing caught it because **no test touched the Selenium proxy-auth path at
all** -- no reference anywhere in tests/ to manifest_version, onAuthRequired,
add_extension or --proxy-server. It was pure configuration, and configuration
is exactly what a mocked driver cannot validate.

So these tests assert the property that actually matters and that a browser
upgrade can silently violate: **credentials must leave the process attached to
the request**, and the browser must never be handed a bare proxy it cannot
authenticate to. They exercise the real relay over real sockets against a fake
upstream Squid that demands Proxy-Authorization -- no Chrome required.
"""

import base64
import socket
import threading

import pytest

from src.crawler.proxy_relay import ProxyAuthRelay, split_proxy_url

UPSTREAM_USER = "mizzoucrawler"
UPSTREAM_PASS = "s3kr3t:with/chars"


class FakeSquid:
    """Minimal upstream proxy that requires Basic auth, like the real Squid."""

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.seen_headers: list[bytes] = []
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        try:
            head = b""
            while b"\r\n\r\n" not in head:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                head += chunk
            self.seen_headers.append(head)
            expected = base64.b64encode(
                f"{UPSTREAM_USER}:{UPSTREAM_PASS}".encode()
            ).decode("ascii")
            if (
                f"Proxy-Authorization: Basic {expected}".lower()
                in head.decode("latin-1").lower()
            ):
                conn.sendall(b"HTTP/1.1 200 Connection established\r\n\r\nOK-BODY")
            else:
                # Exactly what production Chrome received: 407, fast, empty.
                conn.sendall(
                    b"HTTP/1.1 407 Proxy Authentication Required\r\n"
                    b'Proxy-Authenticate: Basic realm="squid"\r\n\r\n'
                )
        except OSError:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def stop(self):
        try:
            self.sock.close()
        except OSError:
            pass


@pytest.fixture
def squid():
    s = FakeSquid()
    yield s
    s.stop()


@pytest.fixture
def relay(squid):
    r = ProxyAuthRelay(f"http://{UPSTREAM_USER}:{UPSTREAM_PASS}@127.0.0.1:{squid.port}")
    r.start()
    yield r
    r.stop()


def _speak(endpoint: str, request: bytes) -> bytes:
    host, port = endpoint.split(":")
    with socket.create_connection((host, int(port)), timeout=10) as sock:
        sock.sendall(request)
        sock.settimeout(10)
        out = b""
        try:
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                out += chunk
        except OSError:
            pass
        return out


class TestProxyUrlParsing:
    def test_extracts_credentials(self):
        host, port, user, password = split_proxy_url("http://u:p@squid.example:3128")
        assert (host, port, user, password) == ("squid.example", 3128, "u", "p")

    def test_percent_encoded_credentials_are_decoded(self):
        _, _, user, password = split_proxy_url("http://u%40x:p%2Fw@h:3128")
        assert (user, password) == ("u@x", "p/w")

    def test_no_credentials(self):
        host, port, user, password = split_proxy_url("http://squid.example:3128")
        assert (host, port) == ("squid.example", 3128)
        assert user is None and password is None

    def test_scheme_optional(self):
        assert split_proxy_url("squid.example:3128")[0] == "squid.example"

    @pytest.mark.parametrize("bad", ["", "://", "http://"])
    def test_unusable_url_raises(self, bad):
        """Must raise, never silently yield an unproxied browser."""
        with pytest.raises(ValueError):
            split_proxy_url(bad)


class TestRelayAuthenticatesUpstream:
    """The regression: the browser is unauthenticated; the relay supplies auth."""

    def test_connect_tunnel_is_authenticated(self, relay, squid):
        # Chrome speaks CONNECT with NO credentials -- it has no way to send any.
        reply = _speak(
            relay.proxy_url,
            b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n",
        )
        assert b"200" in reply, f"expected upstream 200, got: {reply[:80]!r}"
        assert b"407" not in reply

    def test_plain_http_request_is_authenticated(self, relay, squid):
        reply = _speak(
            relay.proxy_url,
            b"GET http://example.com/ HTTP/1.1\r\nHost: example.com\r\n\r\n",
        )
        assert b"200" in reply
        assert b"407" not in reply

    def test_credentials_actually_reach_upstream(self, relay, squid):
        _speak(
            relay.proxy_url,
            b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n",
        )
        assert squid.seen_headers, "upstream never saw a request"
        assert b"Proxy-Authorization: Basic " in squid.seen_headers[0]

    def test_request_line_is_preserved_verbatim(self, relay, squid):
        """Auth is inserted after the request line, not over it."""
        _speak(
            relay.proxy_url,
            b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n",
        )
        assert squid.seen_headers[0].startswith(b"CONNECT example.com:443 HTTP/1.1\r\n")

    def test_client_supplied_auth_is_replaced_not_duplicated(self, relay, squid):
        _speak(
            relay.proxy_url,
            b"CONNECT example.com:443 HTTP/1.1\r\n"
            b"Proxy-Authorization: Basic Zm9yZ2Vk\r\n"
            b"Host: example.com:443\r\n\r\n",
        )
        head = squid.seen_headers[0]
        assert head.count(b"Proxy-Authorization:") == 1
        assert b"Zm9yZ2Vk" not in head

    def test_headers_end_with_exactly_one_blank_line(self, relay, squid):
        """A mangled header/body separator would break the upstream parse."""
        _speak(
            relay.proxy_url,
            b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n",
        )
        head = squid.seen_headers[0]
        assert head.endswith(b"\r\n\r\n")
        assert not head.endswith(b"\r\n\r\n\r\n")


class TestRelayWithoutCredentials:
    """The other state: an upstream that needs no auth must still work."""

    def test_unauthenticated_upstream_is_passed_through(self, squid):
        relay = ProxyAuthRelay(f"http://127.0.0.1:{squid.port}")
        relay.start()
        try:
            assert relay.requires_auth is False
            reply = _speak(
                relay.proxy_url,
                b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n",
            )
            # FakeSquid demands auth, so this correctly fails -- proving the
            # relay does not fabricate credentials it was never given.
            assert b"407" in reply
            assert b"Proxy-Authorization" not in squid.seen_headers[0]
        finally:
            relay.stop()

    def test_relay_binds_loopback_only(self, relay):
        """Never expose an open proxy to the network."""
        host, _ = relay.proxy_url.split(":")
        assert host == "127.0.0.1"
