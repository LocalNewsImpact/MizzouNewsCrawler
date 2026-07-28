"""Local unauthenticated proxy relay that adds Squid credentials upstream.

Chrome cannot be given proxy credentials on the command line: ``--proxy-server``
has no syntax for them. The long-standing workaround was a Manifest V2
extension answering ``chrome.webRequest.onAuthRequired``. Chrome removed
Manifest V2, and by Chrome 150 such an extension is ignored *silently* -- no
error, no warning. Every Selenium fetch then reached the authenticated Squid
with no credentials, got 407, and returned a ~0.2s "successful" navigation to
an empty error page. Confirmed in production 2026-07-27: zero Selenium
successes since 07-25 across ~500 attempts, and from inside an extraction pod
``no-cred -> 407`` / ``with-cred -> 200``.

Manifest V3 cannot replace it either -- blocking ``onAuthRequired`` is gone.

So the credentials move out of the browser entirely. This relay listens on
127.0.0.1, speaks plain HTTP proxy to Chrome with **no** authentication, and
injects ``Proxy-Authorization`` on the way to the real Squid. Chrome never sees
a credential and never has to support one, so no future browser change can
break this the way MV2 removal did.

Handles both proxy modes:
  * ``CONNECT host:port``  -- HTTPS tunnels (the overwhelming majority)
  * absolute-URI requests  -- plain HTTP

Credentials are never logged; only the upstream host:port is.
"""

from __future__ import annotations

import base64
import logging
import socket
import threading
import urllib.parse
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_BUF = 65536
_CONNECT_TIMEOUT = 20
_IDLE_TIMEOUT = 180


def split_proxy_url(proxy_url: str) -> tuple[str, int, str | None, str | None]:
    """Return (host, port, username, password) for a proxy URL.

    Accepts values with or without a scheme and with or without credentials.
    Raises ValueError when no host/port can be determined -- callers must not
    silently fall through to an unproxied browser.
    """
    if not proxy_url:
        raise ValueError("empty proxy url")

    # Parsed by hand rather than with urlsplit: proxy passwords routinely
    # contain ':' and '/', which make the URL invalid enough that urlsplit
    # raises ("Port could not be cast to integer"). Raising here would refuse
    # to start Selenium at all -- trading a silent outage for a loud one --
    # so accept the raw forms operators actually put in SQUID_PROXY_URL.
    rest = proxy_url.split("://", 1)[1] if "://" in proxy_url else proxy_url

    # Credentials come off FIRST: a password may contain '/', so stripping a
    # trailing path before this would silently truncate it.
    username = password = None
    if "@" in rest:
        creds, rest = rest.rsplit("@", 1)  # last '@' -- host cannot contain one
        if ":" in creds:
            username, password = creds.split(":", 1)  # first ':' -- pw may hold more
        else:
            username = creds
        username = urllib.parse.unquote(username)
        password = urllib.parse.unquote(password) if password is not None else None

    rest = rest.split("/", 1)[0]  # now safe: drop any trailing path
    if ":" in rest:
        host, _, port_text = rest.rpartition(":")
        try:
            port = int(port_text)
        except ValueError as exc:
            raise ValueError(
                f"proxy url has a non-numeric port: {port_text!r}"
            ) from exc
    else:
        host, port = rest, 3128

    if not host:
        raise ValueError("proxy url has no host")
    return host, port, username, password


def _pipe(src: socket.socket, dst: socket.socket) -> None:
    """Shuttle bytes one way until either side closes."""
    try:
        while True:
            chunk = src.recv(_BUF)
            if not chunk:
                break
            dst.sendall(chunk)
    except OSError:
        pass
    finally:
        for sock in (src, dst):
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


class ProxyAuthRelay:
    """Loopback proxy that forwards to an authenticated upstream proxy."""

    def __init__(
        self,
        upstream_url: str,
        resolve_upstream: Optional[Callable[[str], Optional[str]]] = None,
    ):
        """
        Args:
            upstream_url: the Squid used when no resolver is given, or when the
                resolver declines to choose.
            resolve_upstream: maps a target host to the proxy URL that should
                serve it. Routing lives HERE rather than at driver creation
                because Chrome fixes --proxy-server when the process starts and
                drivers are reused across domains (SELENIUM_DRIVER_REUSE_LIMIT),
                so a per-domain choice made at launch would be carried to the
                next domain. The relay sees every request's target host, so it
                can route each connection independently behind one fixed
                loopback endpoint.
        """
        self._default_upstream = upstream_url
        self._resolve_upstream = resolve_upstream
        host, port, user, password = split_proxy_url(upstream_url)
        self.upstream_host = host
        self.upstream_port = port
        self._auth_header = self._auth_for(user, password)
        self._server: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self.port: Optional[int] = None

    @staticmethod
    def _auth_for(user: Optional[str], password: Optional[str]) -> bytes:
        if user is None or password is None:
            return b""
        token = base64.b64encode(f"{user}:{password}".encode()).decode("ascii")
        return f"Proxy-Authorization: Basic {token}\r\n".encode()

    @staticmethod
    def target_host(head: bytes) -> Optional[str]:
        """Host this request is FOR, from the proxy request line.

        `CONNECT example.com:443 HTTP/1.1` -> example.com
        `GET http://example.com/x HTTP/1.1` -> example.com
        """
        try:
            line = head.split(b"\r\n", 1)[0].decode("latin-1")
        except Exception:
            return None
        parts = line.split()
        if len(parts) < 2:
            return None
        method, target = parts[0].upper(), parts[1]
        if method == "CONNECT":
            return target.rsplit(":", 1)[0] or None
        if "://" in target:
            rest = target.split("://", 1)[1].split("/", 1)[0]
            return rest.rsplit("@", 1)[-1].rsplit(":", 1)[0] or None
        return None

    def _upstream_for(self, head: bytes) -> tuple[str, int, bytes]:
        """(host, port, auth_header) for this connection."""
        if self._resolve_upstream is not None:
            host = self.target_host(head)
            if host:
                try:
                    chosen = self._resolve_upstream(host)
                except Exception as exc:
                    # Never fail a page load over a routing decision: the
                    # default upstream is always reachable.
                    logger.debug("relay upstream resolution failed: %s", exc)
                    chosen = None
                if chosen:
                    try:
                        h, p, u, pw = split_proxy_url(chosen)
                        return h, p, self._auth_for(u, pw)
                    except ValueError as exc:
                        logger.warning(
                            "relay ignoring unusable routed proxy (%s); using default",
                            exc,
                        )
        return self.upstream_host, self.upstream_port, self._auth_header

    @property
    def requires_auth(self) -> bool:
        return bool(self._auth_header)

    def start(self) -> str:
        """Bind an ephemeral loopback port and serve. Returns the proxy URL."""
        if self.port is not None:
            return self.proxy_url
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        server.listen(128)
        self._server = server
        self.port = server.getsockname()[1]
        self._thread = threading.Thread(
            target=self._serve, name="proxy-auth-relay", daemon=True
        )
        self._thread.start()
        logger.info(
            "🔐 Proxy auth relay on 127.0.0.1:%s -> %s:%s (credentials injected "
            "server-side; Chrome sees an unauthenticated proxy)",
            self.port,
            self.upstream_host,
            self.upstream_port,
        )
        return self.proxy_url

    @property
    def proxy_url(self) -> str:
        if self.port is None:
            raise RuntimeError("relay not started")
        return f"127.0.0.1:{self.port}"

    def stop(self) -> None:
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
        self._server = None
        self.port = None

    def _serve(self) -> None:
        while True:
            server = self._server
            if server is None:
                return
            try:
                client, _ = server.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(client,), daemon=True).start()

    def _handle(self, client: socket.socket) -> None:
        upstream: Optional[socket.socket] = None
        try:
            client.settimeout(_IDLE_TIMEOUT)
            head = b""
            while b"\r\n\r\n" not in head:
                chunk = client.recv(_BUF)
                if not chunk:
                    return
                head += chunk
                if len(head) > 1_048_576:  # runaway header guard
                    return

            host, port, auth = self._upstream_for(head)
            upstream = socket.create_connection((host, port), timeout=_CONNECT_TIMEOUT)
            upstream.settimeout(_IDLE_TIMEOUT)
            upstream.sendall(self._with_auth(head, auth))

            threading.Thread(target=_pipe, args=(client, upstream), daemon=True).start()
            _pipe(upstream, client)
        except OSError as exc:
            logger.debug("relay connection ended: %s", exc)
        finally:
            for sock in (client, upstream):
                if sock is not None:
                    try:
                        sock.close()
                    except OSError:
                        pass

    def _with_auth(self, head: bytes, auth: Optional[bytes] = None) -> bytes:
        """Insert Proxy-Authorization after the request line.

        Any client-supplied Proxy-Authorization is dropped first so ours is
        authoritative and can't be duplicated.
        """
        auth = self._auth_header if auth is None else auth
        if not auth:
            return head
        line_end = head.find(b"\r\n")
        if line_end == -1:
            return head
        request_line = head[: line_end + 2]
        rest = head[line_end + 2 :]
        cleaned = b"".join(
            line + b"\r\n"
            for line in rest.split(b"\r\n")
            if not line.lower().startswith(b"proxy-authorization:")
        )
        # split/rejoin leaves a trailing empty element -> normalise the
        # header/body separator back to exactly one blank line.
        cleaned = cleaned.rstrip(b"\r\n") + b"\r\n\r\n"
        return request_line + auth + cleaned


_relay: Optional[ProxyAuthRelay] = None
_relay_lock = threading.Lock()


def _router_upstream(host: str) -> Optional[str]:
    """Ask the shared proxy_router which Squid should serve ``host``.

    Selenium previously egressed through a single static SELENIUM_PROXY, so
    browser traffic was exempt from #413's home-vs-mizzou selection and its
    health-based backoff -- the router would log
    ``home_squid backed off for <domain> (62 failures)`` while Chrome kept
    sending requests there anyway, with no failover available.

    Returns None on any failure so the caller falls back to its default
    upstream: a routing decision must never be able to stop a page loading.
    """
    try:
        from .proxy_config import get_proxy_manager

        proxies, _choice, _method = get_proxy_manager().get_requests_proxies_for_domain(
            host, service="selenium"
        )
    except Exception as exc:  # router unavailable, misconfigured, anything
        logger.debug("router lookup failed for %s: %s", host, exc)
        return None
    if not proxies:
        return None
    return proxies.get("https") or proxies.get("http")


def get_relay_proxy(upstream_url: str, *, route: bool = True) -> str:
    """Return a loopback ``host:port`` that proxies to Squid.

    One relay per process, reused across drivers. With ``route`` the relay
    picks the upstream per connection from the shared router, keyed on each
    request's target host; ``upstream_url`` is the fallback when the router
    declines or fails. Raises ValueError if that fallback is unusable --
    callers must fail loudly rather than hand Chrome no proxy at all.
    """
    global _relay
    with _relay_lock:
        if _relay is None or _relay.port is None:
            _relay = ProxyAuthRelay(
                upstream_url, resolve_upstream=_router_upstream if route else None
            )
            _relay.start()
        return _relay.proxy_url
