import base64
import os
from types import MethodType
from typing import Any
from urllib.parse import quote_plus, urlparse


METADATA_HOSTS = {
    "metadata.google.internal",
    "metadata",
    "169.254.169.254",
    "metadata.google.internal."  # trailing dot variant
}


def _extract_url(value: Any) -> str | None:
    if isinstance(value, str):
        return value

    if hasattr(value, "url"):
        candidate = getattr(value, "url")
        if candidate:
            return str(candidate)

    return None


def _parse_bypass_hosts() -> set[str]:
    """Build a lower-cased set of hosts that should bypass the origin proxy."""

    hosts: set[str] = set(METADATA_HOSTS)

    for env_var in ("ORIGIN_PROXY_BYPASS", "NO_PROXY", "no_proxy"):
        raw = os.getenv(env_var, "")
        if not raw:
            continue

        for entry in raw.split(","):
            entry = entry.strip()
            if not entry:
                continue
            hosts.add(entry.lower())

    return hosts


def _should_bypass(url: Any) -> bool:
    """Return True if the given URL should not be proxied."""

    extracted = _extract_url(url)
    if extracted is None:
        return False

    try:
        parsed = urlparse(extracted)
    except Exception:
        return False

    host = (parsed.hostname or "").lower()
    if not host:
        return False

    bypass_hosts = _parse_bypass_hosts()

    if host in bypass_hosts:
        return True

    # Support domain suffix matches (e.g., ".internal" in bypass list)
    for candidate in bypass_hosts:
        if candidate.startswith(".") and host.endswith(candidate):
            return True

    return False


def _basic_auth_value(user: str, password: str | None) -> str:
    token = f"{user}:{password or ''}".encode("latin1")
    return "Basic " + base64.b64encode(token).decode("latin1")


def enable_origin_proxy(session):
    """Wrap a requests.Session so calls to request(...) are rewritten to an
    origin-style proxy when USE_ORIGIN_PROXY is enabled.

    The wrapper will, when USE_ORIGIN_PROXY is truthy, rewrite the outgoing
    request URL from e.g. "https://example.com/path" to
    "{ORIGIN_PROXY_URL}/?url={quote_plus(original_url)}" and, if no auth
    is provided, attach PROXY_USERNAME/PROXY_PASSWORD as basic auth.

    This function is safe to call multiple times (it will not double-wrap).
    """

    if getattr(session, "_origin_proxy_installed", False):
        return

    # Capture original request method (bound)
    orig_request = session.request

    # Expose it so tests can stub it if needed
    session._origin_original_request = orig_request

    def _wrapped_request(self, method, url, *args, **kwargs):
        use = os.getenv("USE_ORIGIN_PROXY", "").lower() in ("1", "true", "yes")
        if use and not _should_bypass(url):
            proxy_base = (
                os.getenv("ORIGIN_PROXY_URL")
                or os.getenv("PROXY_HOST")
                or os.getenv("PROXY_URL")
                or "http://127.0.0.1:23432"
            )
            proxied = proxy_base.rstrip("/") + "/?url=" + quote_plus(str(url))

            # If no explicit auth for this request, attach proxy basic auth
            if "auth" not in kwargs:
                user = os.getenv("PROXY_USERNAME")
                pwd = os.getenv("PROXY_PASSWORD")
                if user is not None:
                    kwargs["auth"] = (user, pwd or "")
                    headers = kwargs.setdefault("headers", {})
                    if "Proxy-Authorization" not in headers:
                        headers["Proxy-Authorization"] = _basic_auth_value(user, pwd)
                    if "Authorization" not in headers:
                        headers["Authorization"] = _basic_auth_value(user, pwd)

            # Replace the outgoing URL with the proxied URL
            url = proxied

        return session._origin_original_request(method, url, *args, **kwargs)

    # Bind wrapper to the session instance
    session.request = MethodType(_wrapped_request, session)
    session._origin_proxy_installed = True


def disable_origin_proxy(session):
    """Restore the original session.request if it was wrapped."""
    if getattr(session, "_origin_proxy_installed", False):
        orig = getattr(session, "_origin_original_request", None)
        if orig is not None:
            session.request = orig
        session._origin_proxy_installed = False
