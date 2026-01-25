#!/usr/bin/env python3
"""Diagnostic for Network.setUserAgentOverride userAgentMetadata acceptance.

Tries multiple variants of the payload to determine which fields cause
'Invalid parameters' error on this Chrome/ChromeDriver instance.

Usage:
  xvfb-run -a python scripts/diagnose_user_agent_metadata.py
"""

import json
import time
try:
    import undetected_chromedriver as uc
except Exception:  # pragma: no cover - optional dependency for local diagnostics
    uc = None

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"


def try_payload(driver, payload):
    try:
        driver.execute_cdp_cmd("Network.setUserAgentOverride", payload)
        return True, None
    except Exception as e:
        return False, e


def main():
    options = uc.ChromeOptions()
    # Run in headless so this script is CI-friendly by default
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=800,600")
    options.add_argument(f"--user-agent={UA}")
    try:
        options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    except Exception:
        pass

    # Initialize driver and fail gracefully if Chrome won't start
    driver = None
    results = []
    try:
        driver = uc.Chrome(options=options, use_subprocess=False, version_main=None)
        time.sleep(1)
        try:
            driver.execute_cdp_cmd("Network.enable", {})
        except Exception:
            pass
    except Exception as e:
        # If Chrome failed to start, record a single failure entry and print JSON
        results.append({"test": "chrome_start", "ok": False, "exception": str(e)})
        import sys
        print(f"chrome_start: ok=False, exc={e}", file=sys.stderr)
        # Print JSON to stdout only (so redirecting stdout to a file yields valid JSON)
        print(json.dumps(results, indent=2))
        return

    tests = []
    # minimal payload (should succeed)
    tests.append(("base_user_agent", {"userAgent": UA}))

    # original full payload
    tests.append(("full_payload", {
        "userAgent": UA,
        "userAgentMetadata": {"brands":[{"brand":"Google Chrome","version":"143"}], "fullVersionList":[{"brand":"Google Chrome","version":"143.0.0.0"}], "mobile": False, "platform":"Win32"},
        "platform":"Win32",
        "acceptLanguage":"en-US"
    }))

    # exclude platform in userAgentMetadata
    tests.append(("no_platform_in_meta", {
        "userAgent": UA,
        "userAgentMetadata": {"brands":[{"brand":"Google Chrome","version":"143"}], "fullVersionList":[{"brand":"Google Chrome","version":"143.0.0.0"}], "mobile": False},
        "platform":"Win32",
        "acceptLanguage":"en-US"
    }))

    # brands+mobile only
    tests.append(("brands_mobile_only", {
        "userAgent": UA,
        "userAgentMetadata": {"brands":[{"brand":"Google Chrome","version":"143"}], "mobile": False},
    }))

    # brands only
    tests.append(("brands_only", {
        "userAgent": UA,
        "userAgentMetadata": {"brands":[{"brand":"Google Chrome","version":"143"}]},
    }))

    # fullVersionList only
    tests.append(("fullVersionList_only", {
        "userAgent": UA,
        "userAgentMetadata": {"fullVersionList":[{"brand":"Google Chrome","version":"143.0.0.0"}]},
    }))

    # mobile only
    tests.append(("mobile_only", {
        "userAgent": UA,
        "userAgentMetadata": {"mobile": False},
    }))

    # empty metadata object
    tests.append(("empty_meta", {"userAgent": UA, "userAgentMetadata": {}}))

    # alternate brand string 'Chromium'
    tests.append(("chromium_brand", {
        "userAgent": UA,
        "userAgentMetadata": {"brands":[{"brand":"Chromium","version":"143"}], "mobile": False}
    }))

    # different fullVersionList version types
    tests.append(("fullVersionList_simple", {
        "userAgent": UA,
        "userAgentMetadata": {"fullVersionList":[{"brand":"Chromium","version":"143"}], "mobile": False}
    }))

    # top-level platform but no metadata
    tests.append(("top_platform_only", {"userAgent": UA, "platform":"Win32", "acceptLanguage":"en-US"}))

    # Try an exact-version full payload derived from Browser.getVersion (if possible)
    try:
        bv = driver.execute_cdp_cmd("Browser.getVersion", {})
        product = bv.get("product", "")
        exact_version = None
        if isinstance(product, str) and product.startswith("Chrome/"):
            exact_version = product.split("/", 1)[1]
        if exact_version:
            ua_exact = UA.replace("Chrome/143.0.0.0", f"Chrome/{exact_version}")
            tests.append(("full_payload_exact", {
                "userAgent": ua_exact,
                "userAgentMetadata": {
                    "brands": [{"brand": "Google Chrome", "version": exact_version.split('.')[0]}],
                    "fullVersionList": [{"brand": "Google Chrome", "version": exact_version}],
                    "mobile": False,
                    "platform": "Win32"
                },
                "platform": "Win32",
                "acceptLanguage": "en-US"
            }))
            import sys
            print(f"full_payload_exact: attempting exact_version={exact_version}", file=sys.stderr)

            # Additional variants derived from Browser.getVersion and exact version
            browser_user_agent = bv.get("userAgent", UA)
            major = exact_version.split(".")[0] if exact_version else None

            tests.append(("full_payload_browser_ua_exact", {
                "userAgent": browser_user_agent,
                "userAgentMetadata": {
                    "brands": [{"brand": "Google Chrome", "version": major}],
                    "fullVersionList": [{"brand": "Google Chrome", "version": exact_version}],
                    "mobile": False,
                    "platform": "Win32"
                },
                "platform": "Win32",
                "acceptLanguage": "en-US"
            }))

            tests.append(("full_payload_both_brands", {
                "userAgent": browser_user_agent,
                "userAgentMetadata": {
                    "brands": [{"brand": "Chromium", "version": major}, {"brand": "Google Chrome", "version": major}],
                    "fullVersionList": [{"brand": "Chromium", "version": exact_version}, {"brand": "Google Chrome", "version": exact_version}],
                    "mobile": False,
                    "platform": "Win32"
                },
                "platform": "Win32",
                "acceptLanguage": "en-US"
            }))

            tests.append(("full_payload_chromium_brand_exact", {
                "userAgent": browser_user_agent,
                "userAgentMetadata": {
                    "brands": [{"brand": "Chromium", "version": major}],
                    "fullVersionList": [{"brand": "Chromium", "version": exact_version}],
                    "mobile": False,
                    "platform": "Win32"
                },
                "platform": "Win32",
                "acceptLanguage": "en-US"
            }))
    except Exception as e:
        import sys
        print(f"full_payload_exact: could not derive exact version: {e}", file=sys.stderr)

    # run tests
    results = []
    for name, payload in tests:
        ok, exc = try_payload(driver, payload)
        results.append({"test": name, "ok": ok, "exception": str(exc) if exc else None, "payload": payload})
        # Human-readable per-test logs go to stderr; JSON output is written to stdout at the end
        import sys
        print(f"{name}: ok={ok}, exc={exc}", file=sys.stderr)

    # also print Browser.getVersion
    try:
        ver = driver.execute_cdp_cmd("Browser.getVersion", {})
        import sys
        print("Browser.getVersion:", ver, file=sys.stderr)
    except Exception as e:
        import sys
        print("Browser.getVersion failed:", e, file=sys.stderr)

    # cleanup
    driver.quit()

    # print full JSON for further parsing
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
