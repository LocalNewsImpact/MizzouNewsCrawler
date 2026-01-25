#!/usr/bin/env python3
"""Test PerimeterX sites with working WebGL."""
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
import os

PROXY = os.environ.get('SELENIUM_PROXY', 'http://t9880447.eero.online:3128')

def main():
    options = Options()
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--headless=new')
    options.add_argument(f'--proxy-server={PROXY}')

    service = Service('/home/appuser/chromedriver')
    driver = webdriver.Chrome(service=service, options=options)

    try:
        # Test IP
        print("Testing IP...")
        driver.get('https://httpbin.org/ip')
        time.sleep(2)
        print(f"IP: {driver.find_element('tag name', 'body').text[:200]}")
        
        # Test Fox2Now
        print("\nTesting fox2now.com...")
        driver.get('https://fox2now.com/')
        time.sleep(5)
        title = driver.title
        body = driver.find_element('tag name', 'body').text[:500]
        if 'denied' in body.lower() or 'blocked' in body.lower():
            print(f"BLOCKED - Title: {title}")
        else:
            print(f"SUCCESS - Title: {title}")
        print(f"Body preview: {body[:200]}")
        
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
