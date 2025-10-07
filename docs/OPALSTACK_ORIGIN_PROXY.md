Origin-style authenticated proxy for Opalstack

Overview

This project includes an "origin-style" proxy server (Flask WSGI) that implements a simple fetch-and-return proxy to avoid requiring system-level forward proxies (Squid) or sudo on shared hosts like Opalstack. The proxy accepts requests of the form:

  GET /?url=<encoded-target-url>

and returns the remote page HTML (or an error) to the caller. The server can be secured with basic auth.

Why use origin-style proxy on Opalstack?

- Opalstack does not allow installing system packages (no sudo), so tools like Squid aren't available.
- A small WSGI app is permitted and can run under user-level processes.
- The origin-style approach keeps the crawler unchanged except for directing requests to the proxy URL; the proxy makes the external fetch.

Files

- src/crawler/origin_proxy.py  (server and adapter)
- tests/test_origin_proxy.py
- tests/test_integration_proxy.py

Environment variables

- USE_ORIGIN_PROXY (boolean): enable the origin-style proxy adapter in the crawler. When set, the crawler will send requests to ORIGIN_PROXY_URL instead of fetching directly.
- ORIGIN_PROXY_URL: Base URL of the running proxy (e.g., https://your-opalstack-user.example.com:PORT/). Must include scheme and host.
- PROXY_USERNAME / PROXY_PASSWORD: Optional basic auth credentials for the proxy. If set, the crawler adapter will include basic auth when calling the proxy.
- PROXY_POOL: Optional comma-separated list of proxy URLs for pool behavior used by the crawler adapter.

Running locally

1. Create a venv and install requirements (if not already installed):

```bash
python -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
```

2. Run the proxy (development):

```bash
# from project root
export PROXY_USERNAME=alice
export PROXY_PASSWORD=secret
python -m src.crawler.origin_proxy
```

This starts the Flask app on the configured port (defaults to 8080 if not set). Use Ctrl-C to stop.

Production on Opalstack

Opalstack constraints:
- No sudo; can't install system-wide services.
- You can run long-running processes under your user account and set up a reverse proxy / subdomain in the Opalstack control panel.

Recommended approach:
1. Pick a port allowed by Opalstack for user processes (they provide a range; use the assigned port). Example: 8080.
2. Deploy the repository under your account, create a virtualenv, and install the project requirements into it.
3. Create a simple wrapper shell script to activate the venv and start the WSGI server. Prefer Gunicorn for production (if permitted):

```bash
#!/bin/zsh
source ~/path/to/venv/bin/activate
exec gunicorn -b 0.0.0.0:8080 src.crawler.origin_proxy:app --workers=2 --timeout 60
```

If Gunicorn is not available on Opalstack, fallback to running the Flask development server (less ideal):

```bash
source ~/path/to/venv/bin/activate
python -m src.crawler.origin_proxy
```

4. Configure Opalstack's domain/subdomain routing so a public hostname routes requests to your running process. Use HTTPS if Opalstack provides TLS for the subdomain.

Security and secrets

- Store PROXY_USERNAME/PROXY_PASSWORD in Opalstack's environment variables / service settings (do not commit secrets).
- Limit access by configuring Opalstack routing or firewall to only expose the proxy to required clients.

Notes

- The origin-style proxy is intentionally simple. For heavier loads or production use, consider using a proper reverse proxy or managed proxy service.
- The crawler adapter supports basic auth and optional proxy pools; review `src/crawler/origin_proxy.py` for details.
