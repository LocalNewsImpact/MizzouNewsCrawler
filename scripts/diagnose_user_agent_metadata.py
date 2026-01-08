#!/usr/bin/env python3
"""Diagnostic for Network.setUserAgentOverride userAgentMetadata acceptance.

Tries multiple variants of the payload to determine which fields cause
'Invalid parameters' error on this Chrome/ChromeDriver instance.

Usage:
  xvfb-run -a python scripts/diagnose_user_agent_metadata.py
"""

import json
import time
import traceback
import undetected_chromedriver as uc

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"


def try_payload(driver, payload):
    try:
        driver.execute_cdp_cmd("Network.setUserAgentOverride", payload)
        return True, None
    except Exception as e:
        return False, e


def main():
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=800,600")
    options.add_argument(f"--user-agent={UA}")
    try:
        options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    except Exception:
        pass
    driver = uc.Chrome(options=options, use_subprocess=False, version_main=None)
    time.sleep(1)
    try:
        driver.execute_cdp_cmd("Network.enable", {})
    except Exception:
        pass

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

    # run tests
    results = []
    for name, payload in tests:
        ok, exc = try_payload(driver, payload)
        results.append({"test": name, "ok": ok, "exception": str(exc) if exc else None, "payload": payload})
        print(f"{name}: ok={ok}, exc={exc}")

    # also print Browser.getVersion
    try:
        ver = driver.execute_cdp_cmd("Browser.getVersion", {})
        print("Browser.getVersion:", ver)
    except Exception as e:
        print("Browser.getVersion failed:", e)

    # cleanup
    driver.quit()

    # print full JSON for further parsing
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
