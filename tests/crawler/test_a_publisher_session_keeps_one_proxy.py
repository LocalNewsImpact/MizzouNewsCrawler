"""Every connection a publisher's page makes leaves through one Squid.

The relay used to route each CONNECT by its own host, hashed as written. A
Yakima Herald page -- www.yakimaherald.com, yakimaherald.com, its CDNs and
google.com/recaptcha -- reached the publisher and its bot scorer from several
egress IPs at once, and a login on the bare host and the article fetch on
``www.`` could land on different Squids.
"""

from __future__ import annotations

import socket
import threading

import pytest

from src.crawler import proxy_relay, proxy_router
from src.crawler.proxy_relay import ProxyAuthRelay, PublisherRoute
from src.crawler.proxy_router import RouterProxy, publisher_key


class HoldingSquid:
    """Upstream that answers CONNECT with 200 and keeps the tunnel open."""

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.port = self.sock.getsockname()[1]
        self.release = threading.Event()
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._hold, args=(conn,), daemon=True).start()

    def _hold(self, conn):
        try:
            head = b""
            while b"\r\n\r\n" not in head:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                head += chunk
            conn.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
            self.release.wait(10)
        except OSError:
            pass
        finally:
            conn.close()

    def stop(self):
        self.release.set()
        self.sock.close()


@pytest.fixture
def squid():
    s = HoldingSquid()
    yield s
    s.stop()


@pytest.fixture
def route(monkeypatch):
    fresh = PublisherRoute()
    monkeypatch.setattr(proxy_relay, "_browser_route", fresh)
    return fresh


@pytest.fixture
def relay(squid, route):
    asked: list[str] = []

    def resolve(host):
        asked.append(host)
        return None  # the default upstream serves; the question is what was asked

    r = ProxyAuthRelay(
        f"http://127.0.0.1:{squid.port}", resolve_upstream=resolve, route=route
    )
    r.start()
    r.asked = asked
    yield r
    r.stop()


def _tunnel(relay, host: str) -> socket.socket:
    sock = socket.create_connection(("127.0.0.1", relay.port), timeout=5)
    sock.sendall(f"CONNECT {host}:443 HTTP/1.1\r\n\r\n".encode())
    reply = sock.recv(4096)
    assert b"200" in reply
    return sock


class TestOnePublisherKey:
    @pytest.mark.parametrize(
        "host",
        [
            "yakimaherald.com",
            "www.yakimaherald.com",
            "WWW.YakimaHerald.com",
            "www.yakimaherald.com:443",
            "www.yakimaherald.com.",
        ],
    )
    def test_every_spelling_is_one_publisher(self, host):
        assert publisher_key(host) == "yakimaherald.com"

    def test_www_and_bare_get_one_squid_and_one_health_record(self):
        for bare in ["yakimaherald.com", "union-bulletin.com", "spokesman.com"]:
            assert proxy_router.assigned_proxy(
                f"www.{bare}"
            ) == proxy_router.assigned_proxy(bare)
            assert proxy_router._doc_id(
                RouterProxy.HOME_SQUID, f"www.{bare}"
            ) == proxy_router._doc_id(RouterProxy.HOME_SQUID, bare)

    def test_a_subdomain_other_than_www_is_its_own_host(self):
        assert publisher_key("myaccount.spokesman.com") == "myaccount.spokesman.com"


class TestTheRelayRoutesByPublisher:
    def test_every_host_on_the_page_is_routed_as_the_publisher(self, relay, route):
        route.route_as("https://www.yakimaherald.com/news/local/a-story.html")
        for host in [
            "www.yakimaherald.com",
            "bloximages.newyork1.vip.townnews.com",
            "www.google.com",
            "www.gstatic.com",
        ]:
            _tunnel(relay, host).close()
        assert relay.asked == ["yakimaherald.com"] * 4

    def test_before_any_navigation_a_connection_is_routed_as_its_host(self, relay):
        _tunnel(relay, "www.example.com").close()
        assert relay.asked == ["www.example.com"]

    def test_a_login_stays_on_the_publishers_squid(self, relay, route):
        with route.pinned("yakimaherald.com"):
            route.route_as("https://yakima.us.auth0.com/u/login")
            _tunnel(relay, "yakima.us.auth0.com").close()
        assert relay.asked == ["yakimaherald.com"]

    def test_the_next_publisher_reroutes_after_the_pin(self, relay, route):
        with route.pinned("yakimaherald.com"):
            pass
        route.route_as("https://www.union-bulletin.com/x")
        _tunnel(relay, "www.google.com").close()
        assert relay.asked == ["union-bulletin.com"]

    def test_about_blank_keeps_the_publisher(self, route):
        route.route_as("https://www.yakimaherald.com/")
        route.route_as("about:blank")
        assert route.publisher == "yakimaherald.com"

    def test_a_new_publisher_closes_the_last_ones_tunnels(self, relay, route):
        """Chrome reuses an open tunnel for the same host; it must not survive."""
        route.route_as("https://www.yakimaherald.com/")
        old = _tunnel(relay, "www.google.com")
        route.route_as("https://www.yakimaherald.com/another")
        old.settimeout(0.5)
        with pytest.raises(socket.timeout):
            old.recv(1)  # same publisher: the tunnel is left open
        route.route_as("https://www.union-bulletin.com/")
        old.settimeout(5)
        assert old.recv(1) == b"", "the old publisher's tunnel was left open"
        old.close()


class TestNavigationSetsThePublisher:
    def test_driver_get_routes_before_it_navigates(self, route):
        seen = []

        class Driver:
            def get(self, url):
                seen.append((url, route.publisher))

        driver = Driver()
        proxy_relay.follow_navigation(driver)
        proxy_relay.follow_navigation(driver)  # idempotent: one wrapper
        driver.get("https://www.yakimaherald.com/news/a")
        assert seen == [("https://www.yakimaherald.com/news/a", "yakimaherald.com")]

    def test_a_pin_taken_before_the_browser_exists_holds(self, route):
        with proxy_relay.publisher_pinned("yakimaherald.com"):
            proxy_relay.route_as("https://login.newzware.com/")
            assert route.publisher == "yakimaherald.com"


def test_the_route_record_is_found_under_either_spelling(monkeypatch):
    monkeypatch.setattr(proxy_relay, "_routes", {})
    proxy_relay._routes[publisher_key("www.yakimaherald.com")] = "choice"
    assert proxy_relay.routed_proxy_for("yakimaherald.com") == "choice"
    assert proxy_relay.routed_proxy_for("www.yakimaherald.com") == "choice"
