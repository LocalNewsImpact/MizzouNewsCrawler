# Allowlist PerimeterX px-cloud domains on Squid proxies

**Summary**
PerimeterX client-side verification (px-cloud JS/XHR) is being blocked by the Squid proxy used by extraction pods (example proxy: `http://t9880447.eero.online:3128`). The proxy returns `HTTP/1.1 403 Forbidden` with `X-Squid-Error: ERR_ACCESS_DENIED` for px-cloud endpoints, preventing verification flows and causing persistent "Press & Hold" challenges in headful Selenium runs.

Whitelisting `*.px-cloud.net` on the Squid proxy will allow PerimeterX verifications to complete and should immediately make headful extractions for impacted sites (e.g., fox2now.com) succeed.

---

## Domains to allowlist
- `.px-cloud.net` (covers `client.px-cloud.net`, `js.px-cloud.net`, `captcha.px-cloud.net`, etc.)

> Note: If you see other PerimeterX domains in site logs, add them similarly.

---

## Squid config snippet (suggested)
Add the following to `/etc/squid/squid.conf` **above any `http_access deny` rules** (i.e., before restrictive deny rules):

```conf
# Allow PerimeterX px-cloud resources for client-side verification
acl PX_CLOUD dstdomain .px-cloud.net
acl PX_CLOUD_PORTS port 80 443
# Permit HTTP/HTTPS to px-cloud
http_access allow PX_CLOUD PX_CLOUD_PORTS
```

If your Squid config restricts CONNECT methods explicitly, ensure CONNECT to px-cloud on port 443 is allowed (place before deny rules):

```conf
acl CONNECT method CONNECT
acl SSL_ports port 443
http_access allow PX_CLOUD SSL_ports CONNECT
```

**Placement:** Put the `http_access allow PX_CLOUD` line(s) before any general deny (e.g., `http_access deny all`) so they match.

---

## Reload/reconfigure Squid
- systemd: `sudo systemctl reload squid`
- or: `sudo squid -k reconfigure`

---

## Acceptance test (quick)
1. From a host that uses the proxy:

```bash
curl -v -x http://<squid-host>:3128 https://client.px-cloud.net/PXCvbtpUrj/main.min.js -I
# Expect: HTTP/1.1 200 OK (not 403)
```

2. Monitor Squid logs while testing:

```bash
sudo tail -F /var/log/squid/access.log | stdbuf -oL grep px-cloud
# Look for TCP_TUNNEL/200 or TCP_MISS/200 entries for client.px-cloud.net
```

3. Re-run the headful extraction (in the extraction pod):

```bash
# run from CI/machine with kube access or inside a pod
xvfb-run -a python -m src.cli.cli_modular extract-url "https://fox2now.com/..." --source fox2now.com --dump-sql --verify-insert
# Verify logs show PerimeterX verification completed and page content is available (no #px-captcha element)
```

---

## Troubleshooting
- If `curl` still returns 403, check for SNI-based or other denylists; check that the PX_CLOUD ACL is placed above deny rules.
- If SSL bumping (SSL_BUMP) or other MITM features are in use, ensure certificates and SNI handling aren't interfering with px-cloud hostnames.
- If change must be scoped narrower, allow only `.px-cloud.net` by source network or the specific proxy cluster IPs used by extraction pods.

---

## Rollback
- Remove the `PX_CLOUD` ACL lines and re-run `squid -k reconfigure`.

---

## Monitoring suggestion (post-apply)
Add a scheduled probe (e.g., cron job, or Prometheus blackbox) that runs `curl -x http://<squid>:3128 -I https://client.px-cloud.net/PXCvbtpUrj/main.min.js` once per hour and alerts if the response is not 200. This will detect regressions quickly.

---

## Evidence & artifacts
- Example failing request observed:

```
curl -x http://t9880447.eero.online:3128 https://client.px-cloud.net/PXCvbtpUrj/main.min.js
# -> HTTP/1.1 403 Forbidden
# -> X-Squid-Error: ERR_ACCESS_DENIED
```

- Extraction artifacts (screenshots, page source, logs): `artifacts/fox2now/` (collected from the extraction pod) — attach to the ticket.

---

## Ops ticket (copy/paste)
**Title:** Allowlist px-cloud domains on Squid proxies used by extraction pods (client.px-cloud.net)

**Body (suggested):**
```
Problem: Our extraction pods are unable to load PerimeterX client resources (client.px-cloud.net, etc.) through the Squid proxy (example proxy: http://t9880447.eero.online:3128). The proxy returns 403/ERR_ACCESS_DENIED for px-cloud, which prevents PerimeterX client verification and causes persistent bot challenge pages during headful extractions (example site: fox2now.com).

Request: Please add a Squid ACL allowing dstdomain .px-cloud.net and permit HTTP/HTTPS (ports 80/443) and CONNECT to that domain. Suggested config snippet:

acl PX_CLOUD dstdomain .px-cloud.net
acl PX_CLOUD_PORTS port 80 443
http_access allow PX_CLOUD PX_CLOUD_PORTS

Please reload Squid (`sudo systemctl reload squid` or `sudo squid -k reconfigure`) after applying. After the change, kindly confirm and we will re-run a headful extraction and verify.

Artifacts: I have attached an example failed curl (403) and extraction artifacts (screenshot, page HTML, logs) in `artifacts/fox2now/`.

Priority: High — this blocks extraction of real-site content protected by PerimeterX.
```

---

If you want, I can open a GitHub issue or send the ticket to the Squid admins — tell me the contact (email or issue tracker) and I will send it and run the verification extraction once they confirm.
