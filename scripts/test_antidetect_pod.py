#!/usr/bin/env python3
"""Test with anti-detection patches."""
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

    # Use real Chrome UA instead of HeadlessChrome
    options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36')

    # Exclude automation switches
    options.add_experimental_option('excludeSwitches', ['enable-automation'])
    options.add_experimental_option('useAutomationExtension', False)

    service = Service('/home/appuser/chromedriver')
    driver = webdriver.Chrome(service=service, options=options)

    # Remove webdriver property
    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
        'source': '''
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            
            // Add chrome.runtime
            window.chrome = window.chrome || {};
            window.chrome.runtime = {};
            
            // Fix plugins to look more real
            Object.defineProperty(navigator, 'plugins', {
                get: () => [
                    {name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer'},
                    {name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai'},
                    {name: 'Native Client', filename: 'internal-nacl-plugin'}
                ]
            });
        '''
    })

    try:
        # Test fingerprint first
        driver.get('about:blank')
        fp = driver.execute_script('''
            return {
                webdriver: navigator.webdriver,
                chrome_runtime: !!(window.chrome && window.chrome.runtime),
                user_agent: navigator.userAgent,
                screen: screen.width + "x" + screen.height
            };
        ''')
        print("Fingerprint after patches:")
        print(json.dumps(fp, indent=2))
        
        # Test IP
        print("\nTesting IP...")
        driver.get('https://httpbin.org/ip')
        time.sleep(2)
        print(f"IP: {driver.find_element(By.TAG_NAME, 'body').text[:200]}")
        
        # Test Fox2Now
        print("\nTesting fox2now.com...")
        driver.get('https://fox2now.com/')
        time.sleep(8)
        title = driver.title
        body = driver.find_element(By.TAG_NAME, 'body').text[:500]
        
        if 'denied' in body.lower() or 'blocked' in body.lower() or 'Press & Hold' in body:
            print(f"BLOCKED - Title: {title}")
        else:
            print(f"SUCCESS - Title: {title}")
        print(f"Body preview: {body[:300]}")
        
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
