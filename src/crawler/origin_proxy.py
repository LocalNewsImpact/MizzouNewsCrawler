import os
from types import MethodType
from urllib.parse import quote_plus

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

    use_flag = os.getenv("USE_ORIGIN_PROXY", "").lower()

    # Capture original request method (bound)
    orig_request = session.request

    # Expose it so tests can stub it if needed
    session._origin_original_request = orig_request

    def _wrapped_request(self, method, url, *args, **kwargs):
        use = os.getenv("USE_ORIGIN_PROXY", "").lower() in ("1", "true", "yes")
        if use:
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
