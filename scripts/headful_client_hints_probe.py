#!/usr/bin/env python3
"""Enhanced headful client-hints probe.

Features:
 - optional injection of `navigator.userAgentData` and `navigator.platform` via
   Page.addScriptToEvaluateOnNewDocument (use --inject-user-agentdata)
 - robust fallbacks for Network.setUserAgentOverride
 - saves perflog, page HTML, screenshot, and cookies under /tmp

Usage:
  ./scripts/headful_client_hints_probe.py --target-url https://httpbin.org/headers --inject-user-agentdata
"""

import json
import time
import os
import argparse
import traceback

import undetected_chromedriver as uc


DEFAULT_TARGET = os.environ.get("SELENIUM_TEST_URL", "https://httpbin.org/headers")
DEFAULT_UA = os.environ.get(
    "SELENIUM_TEST_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
)


def build_injection_script(platform="Win32", brands=None, full_version=None, mobile=False):
    if brands is None:
        brands = [{"brand": "Google Chrome", "version": "143"}]
    full_version_list = [{"brand": brands[0]["brand"], "version": full_version or "143.0.0.0"}]

    # Script overrides navigator.platform and navigator.userAgentData
    script = f"""
(function(){{
  try {{
    Object.defineProperty(navigator, 'platform', {{
      get: () => '{platform}',
      configurable: true
    }});

    const uaData = {{
      brands: {json.dumps(brands)},
      mobile: {str(mobile).lower()},
      getHighEntropyValues: function(hints) {{
        const res = {{}};
        if (Array.isArray(hints)) {{
          if (hints.indexOf('platform') !== -1) res.platform = '{platform}';
          if (hints.indexOf('fullVersionList') !== -1) res.fullVersionList = {json.dumps(full_version_list)};
        }}
        return Promise.resolve(res);
      }},
      toString: function() {{ return 'UAData for injection'; }}
    }};

    try {{
      Object.defineProperty(navigator, 'userAgentData', {{ get: () => uaData, configurable: true }});
    }} catch (e) {{
      // ignore
    }}
  }} catch (e) {{
    // ignore
  }}
}})();
"""
    return script


def main():
    p = argparse.ArgumentParser(description="Headful client-hints probe with fallbacks and optional injection")
    p.add_argument("--target-url", default=DEFAULT_TARGET, help="Target URL to navigate to")
    p.add_argument("--user-agent", default=DEFAULT_UA, help="User-Agent string to use")
    p.add_argument("--inject-user-agentdata", action="store_true", help="Inject navigator.userAgentData/platform via Page.addScriptToEvaluateOnNewDocument before navigation")
    p.add_argument("--inject-platform", default="Win32", help="Platform string to inject into navigator.platform and userAgentData (e.g., 'MacIntel')")
    p.add_argument("--screenshot", default="/tmp/selenium_screenshot.png", help="Path to save screenshot")
    p.add_argument("--perflog", default="/tmp/selenium_perflog.json", help="Path to save performance log JSON")
    p.add_argument("--page-html", default="/tmp/selenium_page.html", help="Path to save page HTML")
    p.add_argument("--cookies", default="/tmp/selenium_after_cookies.json", help="Path to save cookies JSON")
    p.add_argument("--force-reduced", action="store_true", help="Skip full Network.setUserAgentOverride payload (no userAgentMetadata) and use reduced payload first")
    args = p.parse_args()

    print("Starting headful client-hints probe")

    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280,1024")
    options.add_argument(f"--user-agent={args.user_agent}")
    try:
        options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    except Exception:
        pass

    print("Launching undetected-chromedriver...")
    driver = uc.Chrome(options=options, use_subprocess=False, version_main=None)
    time.sleep(1)

    # Enable Network domain
    try:
        driver.execute_cdp_cmd("Network.enable", {})
    except Exception:
        pass

    if args.inject_user_agentdata:
        script = build_injection_script(platform=args.inject_platform)
        try:
            driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": script})
            print(f"Injected script via Page.addScriptToEvaluateOnNewDocument (platform={args.inject_platform})")
        except Exception as e:
            print("Failed to add script injection:", e)

def make_payload(user_agent: str, platform: str = "Win32", accept_language: str = "en-US") -> dict:
    brands = [{"brand": "Google Chrome", "version": "143"}]
    full_version_list = [{"brand": "Google Chrome", "version": "143.0.0.0"}]
    return {
        "userAgent": user_agent,
        "userAgentMetadata": {
            "brands": brands,
            "fullVersionList": full_version_list,
            "mobile": False,
            "platform": platform,
        },
        "platform": platform,
        "acceptLanguage": accept_language,
    }


def align_payload_platform(payload: dict, inject_platform: str) -> dict:
    if not payload or not inject_platform:
        return payload
    payload["platform"] = inject_platform
    if payload.get("userAgentMetadata") is not None:
        payload["userAgentMetadata"]["platform"] = inject_platform
    return payload


    payload = make_payload(args.user_agent)

    # If the user requests injection with a specific platform, align the
    # outgoing payload platform and userAgentMetadata.platform with the
    # injected value so headers like sec-ch-ua-platform match the JS-visible
    # navigator.platform/userAgentData overrides.
    try:
        if args.inject_user_agentdata and getattr(args, "inject_platform", None):
            payload["platform"] = args.inject_platform
            if payload.get("userAgentMetadata"):
                payload["userAgentMetadata"]["platform"] = args.inject_platform
            print(f"Aligned payload.platform and userAgentMetadata.platform to {args.inject_platform}")
    except Exception:
        pass

    # Determine if we should try the full payload first. Either the caller
    # explicitly requested reduced payloads via --force-reduced, or the
    # driver may have been previously marked as not supporting
    # userAgentMetadata on this session (driver._supports_user_agent_metadata).
    force_reduced = getattr(args, "force_reduced", False)
    supports_meta = getattr(driver, "_supports_user_agent_metadata", True)

    if not force_reduced and supports_meta:
        print("Trying full Network.setUserAgentOverride with client hints (primary attempt)")
        try:
            driver.execute_cdp_cmd("Network.setUserAgentOverride", payload)
            print("UA override applied via Network.setUserAgentOverride (full payload)")
            # Best-effort: also set sec-ch-* and Accept-Language via extra headers
            try:
                extra_headers = {}
                if payload.get("acceptLanguage"):
                    extra_headers["Accept-Language"] = payload.get("acceptLanguage")
                ua_meta = payload.get("userAgentMetadata") or {}
                brands = ua_meta.get("brands", []) or []
                if brands:
                    extra_headers["sec-ch-ua"] = ", ".join(f'"{b.get("brand")}";v="{b.get("version")}"' for b in brands)
                extra_headers["sec-ch-ua-mobile"] = "?1" if ua_meta.get("mobile") else "?0"
                if payload.get("platform"):
                    extra_headers["sec-ch-ua-platform"] = f'"{payload.get("platform")}"'
                if extra_headers:
                    driver.execute_cdp_cmd("Network.setExtraHTTPHeaders", {"headers": extra_headers})
            except Exception as exc:
                print("Network.setExtraHTTPHeaders after full payload failed:", exc)
        except Exception as e:
            print("Full Network.setUserAgentOverride failed:", e)
            # If the driver rejects userAgentMetadata, cache that fact on the
            # driver object so subsequent calls can skip the full payload.
            try:
                if "invalid parameters" in str(e).lower():
                    try:
                        driver._supports_user_agent_metadata = False
                        print("Marked driver as not supporting userAgentMetadata on this session")
                    except Exception:
                        pass
            except Exception:
                pass

            # Fall back to reduced payload (no userAgentMetadata)
            reduced = {"userAgent": args.user_agent}
            for k, v in payload.items():
                if k not in ("userAgentMetadata", "userAgent"):
                    reduced[k] = v
            try:
                driver.execute_cdp_cmd("Network.setUserAgentOverride", reduced)
                print("UA override applied via Network.setUserAgentOverride (reduced payload)")
            except Exception as e2:
                print("Reduced Network.setUserAgentOverride failed:", e2)
                # Try Emulation.setUserAgentOverride as alternative
                try:
                    emu_payload = {"userAgent": args.user_agent}
                    if "platform" in payload:
                        emu_payload["platform"] = payload["platform"]
                    driver.execute_cdp_cmd("Emulation.setUserAgentOverride", emu_payload)
                    print("UA override applied via Emulation.setUserAgentOverride")
                except Exception as e3:
                    print("Emulation.setUserAgentOverride failed:", e3)

            # As a last resort, set sec-ch-* headers explicitly via extra HTTP headers
            if "userAgentMetadata" in payload:
                try:
                    ua_meta = payload.get("userAgentMetadata") or {}
                    brands = ua_meta.get("brands", []) or []
                    sec_ch_ua = ", ".join(f'"{b.get("brand")}";v="{b.get("version")}"' for b in brands)
                    headers = {
                        "sec-ch-ua": sec_ch_ua,
                        "sec-ch-ua-mobile": "?1" if ua_meta.get("mobile") else "?0",
                        "sec-ch-ua-platform": f'"{payload.get("platform")}"',
                        "Accept-Language": payload.get("acceptLanguage", "en-US"),
                    }
                    driver.execute_cdp_cmd("Network.setExtraHTTPHeaders", {"headers": headers})
                    print("Set sec-ch-* headers via Network.setExtraHTTPHeaders")
                except Exception as e4:
                    print("Failed to set extra headers:", e4)
    else:
        print("Skipping full Network.setUserAgentOverride (force-reduced or driver flagged). Using reduced payload")
        reduced = {"userAgent": args.user_agent}
        for k, v in payload.items():
            if k not in ("userAgentMetadata", "userAgent"):
                reduced[k] = v
        try:
            driver.execute_cdp_cmd("Network.setUserAgentOverride", reduced)
            print("UA override applied via Network.setUserAgentOverride (reduced payload)")
        except Exception as e2:
            print("Reduced Network.setUserAgentOverride failed:", e2)
            try:
                emu_payload = {"userAgent": args.user_agent}
                if "platform" in payload:
                    emu_payload["platform"] = payload["platform"]
                driver.execute_cdp_cmd("Emulation.setUserAgentOverride", emu_payload)
                print("UA override applied via Emulation.setUserAgentOverride")
            except Exception as e3:
                print("Emulation.setUserAgentOverride failed:", e3)

        if "userAgentMetadata" in payload:
            try:
                ua_meta = payload.get("userAgentMetadata") or {}
                brands = ua_meta.get("brands", []) or []
                sec_ch_ua = ", ".join(f'"{b.get("brand")}";v="{b.get("version")}"' for b in brands)
                headers = {
                    "sec-ch-ua": sec_ch_ua,
                    "sec-ch-ua-mobile": "?1" if ua_meta.get("mobile") else "?0",
                    "sec-ch-ua-platform": f'"{payload.get("platform")}"',
                    "Accept-Language": payload.get("acceptLanguage", "en-US"),
                }
                driver.execute_cdp_cmd("Network.setExtraHTTPHeaders", {"headers": headers})
                print("Set sec-ch-* headers via Network.setExtraHTTPHeaders")
            except Exception as e4:
                print("Failed to set extra headers:", e4)

    print("Navigating to:", args.target_url)
    try:
        driver.get(args.target_url)
        time.sleep(2)
    except Exception as e:
        print("Navigation error:", e)
        traceback.print_exc()

    # Capture artifacts
    try:
        perflog = driver.get_log("performance")
        with open(args.perflog, "w") as f:
            json.dump(perflog, f)
        print(f"Wrote {args.perflog}")
    except Exception as e:
        print("Failed to capture performance logs:", e)

    try:
        with open(args.page_html, "w") as f:
            f.write(driver.page_source)
        print(f"Wrote {args.page_html}")
    except Exception as e:
        print("Failed to write page HTML:", e)

    try:
        driver.save_screenshot(args.screenshot)
        print(f"Wrote screenshot to {args.screenshot}")
    except Exception as e:
        print("Failed to save screenshot:", e)

    try:
        cookies = driver.get_cookies()
        with open(args.cookies, "w") as f:
            json.dump(cookies, f)
        print(f"Wrote cookies to {args.cookies}")
    except Exception as e:
        print("Failed to save cookies:", e)

    print("Done; quitting browser")
    try:
        driver.quit()
    except Exception:
        pass


if __name__ == "__main__":
    main()
