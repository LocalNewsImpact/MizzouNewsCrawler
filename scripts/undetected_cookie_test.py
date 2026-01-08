#!/usr/bin/env python3
import json
import os
import shutil
import time
from urllib.parse import urlparse

import undetected_chromedriver as uc

TARGET_URL = os.environ.get("SELENIUM_TEST_URL", "https://fox4kc.com/")
COOKIE_FILE = os.environ.get(
    "SELENIUM_IMPORT_COOKIES_FILE", "/tmp/selenium_import_cookies.json"
)
PROFILE_SRC = os.environ.get("SELENIUM_USER_DATA_DIR", "/var/selenium/profile")
PROFILE_COPY = "/tmp/chrome_profile"

def main():
    print("Starting undetected cookie test")

    # Prepare profile copy (if mounted)
    if os.path.exists(PROFILE_SRC):
        try:
            if os.path.exists(PROFILE_COPY):
                shutil.rmtree(PROFILE_COPY)
            # copy tree excluding lost+found
            def ignore_func(src, names):
                return [n for n in names if n == "lost+found"]

            shutil.copytree(PROFILE_SRC, PROFILE_COPY, symlinks=True, ignore=ignore_func)
            print("Copied profile from", PROFILE_SRC, "to", PROFILE_COPY)
        except Exception as e:
            print("Failed to copy profile, proceeding without it:", e)
    else:
        print("Profile source not found; proceeding without profile")

    # Build options
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-web-security")
    options.add_argument("--disable-setuid-sandbox")
    options.add_argument("--remote-debugging-port=9222")
    options.add_argument("--window-size=1280,1024")
    if os.path.exists(PROFILE_COPY):
        options.add_argument(f"--user-data-dir={PROFILE_COPY}")

    # Realistic UA (desktop Chrome)
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
    )
    # Enable performance log collection
    try:
        options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    except Exception:
        pass

    print("Launching undetected-chromedriver...")
    # Create driver
    try:
        driver = uc.Chrome(options=options, use_subprocess=False, version_main=None)
    except Exception as e:
        print("Failed to start Chrome:", e)
        raise

    # Small wait for browser to initialize
    time.sleep(1)

    # Import cookies if provided
    imported = 0
    if os.path.exists(COOKIE_FILE):
        try:
            with open(COOKIE_FILE) as f:
                cookies = json.load(f)
            # enable network domain
            try:
                driver.execute_cdp_cmd("Network.enable", {})
            except Exception:
                pass
            domain = urlparse(TARGET_URL).netloc
            for c in cookies:
                cookie_domain = c.get("domain") or domain
                if not (
                    cookie_domain == domain
                    or cookie_domain == f".{domain}"
                    or cookie_domain.endswith(domain)
                ):
                    continue
                payload = {
                    "name": c.get("name"),
                    "value": c.get("value", ""),
                    "path": c.get("path", "/"),
                    "secure": bool(c.get("secure", False)),
                    "httpOnly": bool(c.get("httpOnly", False)),
                    "domain": cookie_domain,
                    "url": f"https://{domain}{c.get('path','/')}",
                }
                expires = c.get("expires")
                if isinstance(expires, (int, float)) and expires > 0:
                    payload["expires"] = int(expires)
                if c.get("sameSite"):
                    payload["sameSite"] = c.get("sameSite")
                try:
                    driver.execute_cdp_cmd("Network.setCookie", payload)
                    imported += 1
                except Exception as e:
                    print("Network.setCookie failed for", payload.get("name"), e)
            print("Imported", imported, "cookies")
        except Exception as e:
            print("Failed to read or set cookies:", e)
    else:
        print("No cookie file found at", COOKIE_FILE)

    # Navigate to target
    print("Navigating to", TARGET_URL)
    try:
        driver.get(TARGET_URL)
        time.sleep(3)
    except Exception as e:
        print("Navigation error:", e)

    # Collect artifacts
    try:
        ss = "/tmp/selenium_screenshot.png"
        driver.save_screenshot(ss)
        print("Saved screenshot to", ss)
    except Exception as e:
        print("Failed to save screenshot:", e)

    try:
        cookies_after = driver.get_cookies()
        with open("/tmp/selenium_after_cookies.json", "w") as f:
            json.dump(cookies_after, f)
        print("Wrote /tmp/selenium_after_cookies.json")
    except Exception as e:
        print("Failed to write cookies after navigation:", e)

    try:
        perflog = driver.get_log("performance")
        with open("/tmp/selenium_perflog.json", "w") as f:
            json.dump(perflog, f)
        print("Wrote /tmp/selenium_perflog.json")
    except Exception as e:
        print("Failed to capture performance logs:", e)

    try:
        page_html = driver.page_source
        with open("/tmp/selenium_page.html", "w") as f:
            f.write(page_html)
        print("Wrote /tmp/selenium_page.html")
    except Exception as e:
        print("Failed to write page HTML:", e)

    print("Done. Imported", imported, "cookies; see /tmp for artifacts.")
    # Keep browser open briefly to allow inspection
    time.sleep(2)
    driver.quit()


if __name__ == "__main__":
    main()
