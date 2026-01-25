#!/usr/bin/env python3
"""Simulate human press-and-hold on PerimeterX 'Press & Hold' challenge.
Run inside the extraction pod; reads TARGET_URL from env.
"""
import os
import time
import json
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains

TARGET_URL = os.environ.get(
    "TARGET_URL",
    "https://fox4kc.com/news/one-man-shot-in-manhattan-police-shooting-saturday-kbi/",
)
PROXY = os.environ.get("SELENIUM_PROXY", "http://t9880447.eero.online:3128")


def main():
    options = Options()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--start-maximized")
    options.add_argument(f"--proxy-server={PROXY}")
    # HEADFUL: do NOT set --headless
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
    )
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    service = Service("/home/appuser/chromedriver")

    print(f"Press-and-hold test: {TARGET_URL}")

    driver = webdriver.Chrome(service=service, options=options)
    # Anti-detection script before any page
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": """
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            window.chrome = window.chrome || {};
            window.chrome.runtime = {};
            Object.defineProperty(navigator, 'plugins', {get: () => [ {name: 'Chrome PDF Plugin'} ]});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});
            try { Object.defineProperty(navigator, 'platform', {get: () => 'Win32'}); } catch(e){}
        """
    })

    try:
        driver.get('about:blank')
        fp = driver.execute_script('''return {webdriver: navigator.webdriver, user_agent: navigator.userAgent, screen: screen.width + 'x' + screen.height};''')
        print('Fingerprint:', fp)
        # IP check
        driver.get('https://httpbin.org/ip')
        time.sleep(2)
        print('IP:', driver.find_element(By.TAG_NAME, 'body').text)

        # Load target
        driver.get(TARGET_URL)
        # Wait for challenge to appear
        time_limit = time.time() + 30
        challenge_found = False
        el = None
        while time.time() < time_limit:
            time.sleep(1)
            body = driver.find_element(By.TAG_NAME, 'body').text
            if 'Press & Hold' in body or 'Press and Hold' in body or 'Press &' in body:
                challenge_found = True
                print('Challenge text detected')
                # Try to find the clickable challenge element
                candidates = driver.find_elements(By.XPATH, "//*[contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'press') or contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'hold')]")
                if candidates:
                    el = candidates[0]
                else:
                    # try common button-like elements
                    btns = driver.find_elements(By.TAG_NAME, 'button')
                    if btns:
                        el = btns[0]
                break

        if not challenge_found:
            print('No press-and-hold text found; checking body for block signs')
            body = driver.find_element(By.TAG_NAME, 'body').text
            if any(x in body for x in ['denied', 'blocked', 'Access to this page has been denied']):
                print('Blocked, but no explicit press-and-hold text found')
            else:
                print('No blocking detected; page may be accessible')

        # If we have an element, try to click & hold
        result = 'unknown'
        if el is not None:
            try:
                driver.execute_script('arguments[0].scrollIntoView({block:"center", inline:"center"});', el)
            except Exception:
                pass
            action = ActionChains(driver)
            try:
                print('Performing click-and-hold on challenge element for 5s')
                action.move_to_element(el).click_and_hold().perform()
                time.sleep(5)
                action.release().perform()
                time.sleep(6)
                body_after = driver.find_element(By.TAG_NAME, 'body').text
                if any(x.lower() in body_after.lower() for x in ['press & hold', 'press and hold', 'Access to this page has been denied', 'denied']):
                    result = 'still_blocked'
                else:
                    result = 'passed'
            except Exception as e:
                print('Action error:', e)
                result = 'action_failed'
        else:
            # Try center viewport click-and-hold fallback
            try:
                print('No element found; attempting center-of-screen click-and-hold')
                body_elem = driver.find_element(By.TAG_NAME, 'body')
                action = ActionChains(driver)
                action.move_to_element_with_offset(body_elem, 960, 540).click_and_hold().perform()
                time.sleep(5)
                action.release().perform()
                time.sleep(6)
                body_after = driver.find_element(By.TAG_NAME, 'body').text
                if any(x.lower() in body_after.lower() for x in ['press & hold', 'press and hold', 'Access to this page has been denied', 'denied']):
                    result = 'still_blocked'
                else:
                    result = 'passed'
            except Exception as e:
                print('Fallback action error:', e)
                result = 'action_failed'

        print('\nResult after press-and-hold attempt:', result)
        # Save screenshot
        ss = '/tmp/press_hold_result.png'
        driver.save_screenshot(ss)
        print('Saved screenshot to', ss)

    finally:
        driver.quit()


if __name__ == "__main__":
    main()