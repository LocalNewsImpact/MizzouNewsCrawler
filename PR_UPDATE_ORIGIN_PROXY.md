PR update for feature/origin-proxy-adapter

What's included in the latest push:

- tests/test_extraction_methods.py: replaced flaky webster external test with a deterministic sample-HTML-based test (no external network dependency).
- docs/OPALSTACK_ORIGIN_PROXY.md: added deployment notes for running the origin-style proxy on Opalstack (env vars, suggested startup, security notes).

Why:
- The prior xfail made CI flaky; the new test is deterministic and stable.
- Docs help operators deploy the proxy without system-level proxies like Squid.

Next suggested steps:
- Run GitHub Actions CI; verify the smoke job for proxy tests passes.
- Consider final docs updates for Opalstack-specific process management.
