#!/usr/bin/env python3
"""Headful anti-detection test for a target URL (run inside extraction pod).
Reads TARGET_URL from env; defaults to the Fox4KC article you provided.
"""
import os
import time
import json
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By

TARGET_URL = os.environ.get(
    "TARGET_URL",
    "https://fox4kc.com/news/one-man-shot-in-manhattan-police-shooting-saturday-kbi/",
)
PROXY = os.environ.get("SELENIUM_PROXY", os.environ.get("SELENIUM_PROXY", "http://t9880447.eero.online:3128"))


def main():
    options = Options()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--start-maximized")
    options.add_argument(f"--proxy-server={PROXY}")
    # HEADFUL: do NOT set --headless
    # Use a realistic UA string
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
    )
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    service = Service("/home/appuser/chromedriver")

    print(f"Running headful test against: {TARGET_URL}")
    print(f"Using proxy: {PROXY}")

    # Launch browser
    driver = webdriver.Chrome(service=service, options=options)

    # Inject anti-detection script before any page runs
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": """
            // Hide webdriver flag
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            // Provide chrome.runtime
            window.chrome = window.chrome || {};
            window.chrome.runtime = {};
            // Fake plugins
            Object.defineProperty(navigator, 'plugins', {
                get: () => [
                    {name: 'Chrome PDF Plugin'},
                    {name: 'Chrome PDF Viewer'},
                    {name: 'Native Client'}
                ]
            });
            // Fake languages
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
            // Attempt to set platform
            try { Object.defineProperty(navigator, 'platform', {get: () => 'Win32'}); } catch(e){}
        """
    })

    try:
        # Report quick fingerprint snapshot
        driver.get("about:blank")
        fp = driver.execute_script('''
            return {
                webdriver: navigator.webdriver,
                chrome_runtime: !!(window.chrome && window.chrome.runtime),
                user_agent: navigator.userAgent,
                screen: screen.width + "x" + screen.height,
                plugins_count: navigator.plugins.length,
            };
        ''')
        print("Fingerprint snapshot:")
        print(json.dumps(fp, indent=2))

        # Confirm public IP
        driver.get('https://httpbin.org/ip')
        time.sleep(2)
        ip = driver.find_element(By.TAG_NAME, 'body').text
        print("IP:", ip)

        # Now load target URL (give it time for JS challenges)
        print('\nLoading target URL (headful mode) ...')
        driver.get(TARGET_URL)
        # Wait for challenge to appear or content to load
        time.sleep(15)

        title = driver.title
        try:
            body_text = driver.find_element(By.TAG_NAME, 'body').text[:1200]
        except Exception:
            body_text = "(unable to read body text)"

        # Check for common challenge/block indicators
        blocked_indicators = ['denied', 'blocked', 'Press & Hold', 'Access to this page has been denied', 'perimeterx', 'challenge']
        blocked = any(ind.lower() in body_text.lower() for ind in blocked_indicators)

        print(f"Title: {title}")
        print("Body preview:\n", body_text)
        print('\nBLOCKED:' if blocked else '\nSUCCESS: Page appears accessible')

        # Save screenshot for inspection
        ss_path = '/tmp/target_page.png'
        driver.save_screenshot(ss_path)
        print(f"Saved screenshot to {ss_path}")

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
