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

Every connection is routed by the PUBLISHER the browser is reading, not by the
host the connection is for. A Yakima Herald page pulls from yakimaherald.com,
www.yakimaherald.com, townnews CDNs and google.com/recaptcha; routed host by
host those left through different Squids, so one page reached the publisher
and its bot scorer from several egress IPs at once -- and reCAPTCHA scores the
reader on exactly that. ``route_as()`` names the publisher (``follow_navigation``
sets it on every ``driver.get``); ``publisher_pinned()`` holds it through a
login that crosses to an SSO host.
"""

from __future__ import annotations

import base64
import contextlib
import logging
import socket
import threading
import urllib.parse
from typing import Callable, Iterator, Optional

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


class PublisherRoute:
    """The publisher the browser is reading, the proxy chosen for it, and the
    tunnels opened for it.

    The router is the load balancer; the browser asks it once per publisher
    and keeps the answer until the browser session ends (``end_session``).
    Asked per connection, a backoff recorded mid-page moved the rest of that
    page -- and a logged-in session's next article -- to the other Squid: a
    second egress IP for one reader. The one exception is a 403 through the
    chosen proxy (``fail_over``): the publisher moves to the other Squid for
    the rest of the session, once.
    """

    def __init__(self) -> None:
        self.publisher: Optional[str] = None
        # publisher -> the upstream URL the router chose (None: the default)
        self._upstreams: dict[str, Optional[str]] = {}
        self._failed_over: set[str] = set()
        self._pinned = 0
        # client socket -> the routing key it was opened under
        self._live: dict[socket.socket, Optional[str]] = {}
        self._lock = threading.Lock()

    def route_as(self, url_or_host: str, *, force: bool = False) -> None:
        """Route every connection from now on as ``url_or_host``'s publisher.

        Ignored while a pin holds (``pinned``) unless ``force``. On a change of
        publisher, tunnels opened for the previous one are closed: Chrome keeps
        a CONNECT tunnel open and reuses it for the same host, so a recaptcha
        or CDN tunnel from the last page would otherwise carry this
        publisher's page out through the last publisher's Squid.
        """
        key = _publisher_of(url_or_host)
        if not key:
            return
        with self._lock:
            if self._pinned and not force:
                return
            if key == self.publisher:
                return
            self.publisher = key
            stale = [c for c, k in self._live.items() if k != key]
        for client in stale:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    @contextlib.contextmanager
    def pinned(self, url_or_host: str) -> Iterator[None]:
        """Hold the publisher at ``url_or_host`` for the duration.

        A login leaves the publisher's host -- an Auth0 tenant, an etype or
        Newzware portal, ``myaccount.`` -- and each ``driver.get`` there would
        otherwise re-route the session as that host.
        """
        self.route_as(url_or_host, force=True)
        with self._lock:
            self._pinned += 1
        try:
            yield
        finally:
            with self._lock:
                self._pinned -= 1

    def upstream_for(
        self, key: str, resolve: Callable[[str], Optional[str]]
    ) -> Optional[str]:
        """The upstream chosen for ``key`` this session; asked once."""
        with self._lock:
            if key in self._upstreams:
                return self._upstreams[key]
        try:
            chosen = resolve(key)
        except Exception as exc:
            # Never fail a page load over a routing decision: the default
            # upstream is always reachable.
            logger.debug("relay upstream resolution failed: %s", exc)
            chosen = None
        with self._lock:
            # Two first connections may race; the first answer is the session's.
            return self._upstreams.setdefault(key, chosen)

    def switch(self, key: str, upstream: str) -> bool:
        """Move ``key`` to ``upstream`` for the rest of the session, once.

        Its open tunnels are closed so Chrome reconnects through the new one.
        False when ``key`` has already failed over this session: a 403 from
        both Squids is the publisher's answer, not a proxy's.
        """
        with self._lock:
            if key in self._failed_over:
                return False
            self._failed_over.add(key)
            self._upstreams[key] = upstream
            stale = [c for c, k in self._live.items() if k == key]
        for client in stale:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        return True

    def end_session(self) -> None:
        """The browser is gone: forget its publisher and every choice made."""
        with self._lock:
            self.publisher = None
            self._upstreams.clear()
            self._failed_over.clear()
            stale = list(self._live)
        for client in stale:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def opened(self, client: socket.socket, key: Optional[str]) -> None:
        with self._lock:
            self._live[client] = key

    def closed(self, client: socket.socket) -> None:
        with self._lock:
            self._live.pop(client, None)


class ProxyAuthRelay:
    """Loopback proxy that forwards to an authenticated upstream proxy."""

    def __init__(
        self,
        upstream_url: str,
        resolve_upstream: Optional[Callable[[str], Optional[str]]] = None,
        route: Optional[PublisherRoute] = None,
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
                next domain. The relay sees every connection, so it can
                route each one behind one fixed loopback endpoint.
            route: the browser's current publisher; connections are resolved
                as that publisher, not as their own host.
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
        self._route = route if route is not None else PublisherRoute()

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

    def _routing_key(self, head: bytes) -> Optional[str]:
        """The publisher this connection is routed as.

        The browser's current publisher when one is set; the request's own
        host only before the first navigation.
        """
        return self._route.publisher or self.target_host(head)

    def _upstream_for(
        self, head: bytes, key: Optional[str] = None
    ) -> tuple[str, int, bytes]:
        """(host, port, auth_header) for this connection."""
        if self._resolve_upstream is not None:
            host = key if key is not None else self._routing_key(head)
            if host:
                chosen = self._route.upstream_for(host, self._resolve_upstream)
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

            key = self._routing_key(head)
            self._route.opened(client, key)
            host, port, auth = self._upstream_for(head, key)
            upstream = socket.create_connection((host, port), timeout=_CONNECT_TIMEOUT)
            upstream.settimeout(_IDLE_TIMEOUT)
            upstream.sendall(self._with_auth(head, auth))

            threading.Thread(target=_pipe, args=(client, upstream), daemon=True).start()
            _pipe(upstream, client)
        except OSError as exc:
            logger.debug("relay connection ended: %s", exc)
        finally:
            self._route.closed(client)
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

        A plain-HTTP request is also made the LAST on its connection. The
        header is injected into the first request head only; everything after
        it is piped through untouched. A CONNECT carries one request per
        connection, so that is enough for HTTPS. Plain HTTP is kept alive, and
        Chrome sends the next request down the same connection -- which then
        reached Squid with no credentials. Measured 2026-10-14 from the api
        pod, three GETs on one relay connection: 200, 407, 407.

        A 407 makes Chrome open a proxy-login dialog, and a modal dialog
        freezes chromedriver: every command, a cookie read included, waits out
        the client timeout and reports `DriverUnresponsive`. That is what
        stopped the logins at chinookobserver.com, www.wenatcheeworld.com and
        both McClatchy homepages, all of them carrying `http://` ad and
        tracker requests. `Connection: close` sends each plain-HTTP request on
        a connection of its own, so every one passes through here.
        """
        auth = self._auth_header if auth is None else auth
        if not auth:
            return head
        line_end = head.find(b"\r\n")
        if line_end == -1:
            return head
        request_line = head[: line_end + 2]
        rest = head[line_end + 2 :]
        plain_http = not request_line.upper().startswith(b"CONNECT ")
        dropped: tuple[bytes, ...] = (b"proxy-authorization:",)
        if plain_http:
            dropped += (b"connection:", b"proxy-connection:")
        cleaned = b"".join(
            line + b"\r\n"
            for line in rest.split(b"\r\n")
            if not line.lower().startswith(dropped)
        )
        # split/rejoin leaves a trailing empty element -> normalise the
        # header/body separator back to exactly one blank line.
        cleaned = cleaned.rstrip(b"\r\n") + b"\r\n\r\n"
        if plain_http:
            cleaned = b"Connection: close\r\nProxy-Connection: close\r\n" + cleaned
        return request_line + auth + cleaned


_relay: Optional[ProxyAuthRelay] = None
_relay_lock = threading.Lock()


def _publisher_of(url_or_host: str) -> Optional[str]:
    """Publisher key for a URL or a bare host; None for about:/data: pages."""
    from .proxy_router import publisher_key

    text = (url_or_host or "").strip()
    if text.lower().startswith(("about:", "data:", "blob:", "javascript:", "chrome:")):
        return None
    if "://" in text:
        parsed = urllib.parse.urlsplit(text)
        if parsed.scheme not in ("http", "https"):
            return None
        text = parsed.netloc
    elif "/" in text:
        text = text.split("/", 1)[0]
    return publisher_key(text) or None


#: The process's one browser reads one publisher at a time. Module-level so a
#: pin taken before the browser (and its relay) exists still holds.
_browser_route = PublisherRoute()


def route_as(url_or_host: str) -> None:
    """Route the process's browser as ``url_or_host``'s publisher."""
    _browser_route.route_as(url_or_host)


def fail_over(url_or_host: str) -> bool:
    """A 403 through the session's proxy: move the publisher to the other Squid.

    True when the publisher now routes through a different Squid; the caller
    retries the page through it. False when the publisher was never routed,
    has already failed over this session, or no other Squid is configured.
    """
    from .proxy_config import get_proxy_manager
    from .proxy_router import _PROXY_POOL

    key = _publisher_of(url_or_host)
    if not key:
        return False
    failed = _routes.get(key)
    if failed is None:
        return False
    for other in _PROXY_POOL:
        if other is failed:
            continue
        try:
            proxies = get_proxy_manager().get_requests_proxies_for_router_proxy(other)
        except Exception as exc:  # never fail a page over a routing decision
            logger.debug("failover lookup failed for %s: %s", key, exc)
            proxies = None
        upstream = proxies and (proxies.get("https") or proxies.get("http"))
        if upstream and _browser_route.switch(key, upstream):
            _routes[key] = other
            logger.info(
                "🔀 %s refused through %s; session moves to %s",
                key,
                getattr(failed, "value", failed),
                other.value,
            )
            return True
    return False


def session_upstream_for(url_or_host: str) -> Optional[str]:
    """The upstream proxy URL this browser session uses for the publisher.

    None before the publisher's first connection, or when the router declined
    and the relay's fallback served it.
    """
    key = _publisher_of(url_or_host)
    if not key:
        return None
    with _browser_route._lock:
        return _browser_route._upstreams.get(key)


def end_browser_session() -> None:
    """Forget the publisher and its chosen proxy; the next browser asks anew."""
    _browser_route.end_session()


def publisher_pinned(url_or_host: str) -> contextlib.AbstractContextManager[None]:
    """Keep the browser routed as ``url_or_host`` through every navigation.

    For logins: the whole sign-in leaves through the publisher's Squid, so the
    session cookie is issued to the same egress IP that then reads the paper.
    """
    return _browser_route.pinned(url_or_host)


def follow_navigation(driver) -> None:
    """Make every ``driver.get`` re-route the relay as the page's publisher.

    Done on the driver rather than at each call site: extraction, discovery's
    renderer, the login flows and validate-login all navigate the one shared
    browser, and a call site that forgot would quietly route a publisher's
    page by the previous publisher.
    """
    if getattr(driver, "_routes_by_publisher", False):
        return
    navigate = driver.get

    def get(url, *args, **kwargs):
        route_as(url)
        return navigate(url, *args, **kwargs)

    driver.get = get
    driver._routes_by_publisher = True


#: The router's last answer per target host, as the relay applied it. The
#: browser path reads it to report how that proxy fared: the router chose the
#: browser's egress and never heard the outcome, so a proxy Cloudflare refused
#: for a host stayed that host's choice. myedmondsnews.com, 2026-10-14: the
#: Mizzou Squid, refused every navigation, showed one failure, from September.
_routes: dict[str, object] = {}


def routed_proxy_for(host: str):
    """The RouterProxy the relay last used for ``host``'s publisher, or None."""
    from .proxy_router import publisher_key

    return _routes.get(publisher_key(host))


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

        proxies, choice, _method = get_proxy_manager().get_requests_proxies_for_domain(
            host, service="selenium"
        )
    except Exception as exc:  # router unavailable, misconfigured, anything
        logger.debug("router lookup failed for %s: %s", host, exc)
        return None
    if not proxies:
        return None
    if choice is not None:
        from .proxy_router import publisher_key

        _routes[publisher_key(host)] = choice
    return proxies.get("https") or proxies.get("http")


def get_relay_proxy(upstream_url: str, *, route: bool = True) -> str:
    """Return a loopback ``host:port`` that proxies to Squid.

    One relay per process, reused across drivers -- there is one shared browser
    per process (``ContentExtractor._shared_persistent_driver``), so one
    current publisher. With ``route`` the relay picks the upstream from the
    shared router, keyed on that publisher (see ``route_as``); ``upstream_url``
    is the fallback when the router declines or fails. Raises ValueError if
    that fallback is unusable -- callers must fail loudly rather than hand
    Chrome no proxy at all.
    """
    global _relay
    with _relay_lock:
        if _relay is None or _relay.port is None:
            _relay = ProxyAuthRelay(
                upstream_url,
                resolve_upstream=_router_upstream if route else None,
                route=_browser_route,
            )
            _relay.start()
        return _relay.proxy_url
