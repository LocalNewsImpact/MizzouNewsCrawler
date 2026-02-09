#!/usr/bin/env python3
"""Test with headful mode via Xvfb."""
import time
import json
import os
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By

PROXY = os.environ.get('SELENIUM_PROXY', 'http://t9880447.eero.online:3128')

def main():
    options = Options()
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--window-size=1920,1080')
    options.add_argument(f'--proxy-server={PROXY}')
    options.add_argument('--start-maximized')

    # HEADFUL MODE - no headless flag
    # Xvfb should handle the display

    # Use real Chrome UA
    options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36')

    options.add_experimental_option('excludeSwitches', ['enable-automation'])
    options.add_experimental_option('useAutomationExtension', False)

    service = Service('/home/appuser/chromedriver')
    driver = webdriver.Chrome(service=service, options=options)

    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
        'source': '''
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            window.chrome = window.chrome || {};
            window.chrome.runtime = {};
        '''
    })

    try:
        # Quick fingerprint
        driver.get('about:blank')
        fp = driver.execute_script('''
            return {
                webdriver: navigator.webdriver,
                chrome_runtime: !!(window.chrome && window.chrome.runtime),
                user_agent: navigator.userAgent.includes("Headless") ? "HEADLESS DETECTED" : "OK"
            };
        ''')
        print("Fingerprint:", json.dumps(fp))
        
        # Test IP
        print("\nTesting IP...")
        driver.get('https://httpbin.org/ip')
        time.sleep(2)
        print(f"IP: {driver.find_element(By.TAG_NAME, 'body').text}")
        
        # Test Fox2Now with longer wait
        print("\nTesting fox2now.com (headful mode)...")
        driver.get('https://fox2now.com/')
        time.sleep(10)
        title = driver.title
        body = driver.find_element(By.TAG_NAME, 'body').text[:500]
        
        if 'denied' in body.lower() or 'blocked' in body.lower() or 'Press & Hold' in body:
            print(f"BLOCKED - Title: {title}")
        else:
            print(f"SUCCESS - Title: {title}")
        print(f"Body: {body[:300]}")
        
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
