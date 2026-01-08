#!/usr/bin/env python3
import os
import time
import json
from urllib.parse import urlparse

# Recommended envs to control cookie import behavior
os.environ.setdefault("SELENIUM_EXECUTION_MODE", "headful")
os.environ.setdefault("SELENIUM_WAIT_FOR_COOKIES", "true")
os.environ.setdefault("SELENIUM_IMPORT_COOKIES_FILE", "/tmp/selenium_import_cookies.json")
os.environ.setdefault("SELENIUM_COOKIE_WAIT_SECS", "120")
# Use mounted profile if present
os.environ.setdefault("SELENIUM_USER_DATA_DIR", "/var/selenium/profile")
os.environ.setdefault("SELENIUM_PROFILE_READONLY", "true")

def main():
    from src.crawler.__init__ import ContentExtractor

    url = os.environ.get("SELENIUM_TEST_URL", "https://fox4kc.com/")

    e = ContentExtractor()
    print("Creating persistent driver...")
    driver = e.get_persistent_driver()
    print("Driver created")

    # Import cookies (if file was copied in)
    print("Attempting cookie import...")
    imported = e._maybe_import_selenium_cookies(driver, urlparse(url).netloc)
    print("Cookie import result:", imported)

    # Attempt navigation
    print(f"Navigating to {url} ...")
    success = e._navigate_with_human_behavior(driver, url)
    print("Navigation success:", success)

    # Short pause, then list produced diagnostics
    time.sleep(1)
    print("Diagnostics in /tmp:")
    try:
        import subprocess
        out = subprocess.check_output("ls -1 /tmp | grep selenium_ || true", shell=True)
        print(out.decode())
    except Exception as _:
        pass

    # Save cookies snapshot
    try:
        cookies = driver.get_cookies()
        with open('/tmp/selenium_run_cookies.json', 'w') as f:
            json.dump(cookies, f)
        print('Wrote /tmp/selenium_run_cookies.json')
    except Exception as e:
        print('Failed to write cookies:', e)

    print('Test finished')


if __name__ == "__main__":
    main()
