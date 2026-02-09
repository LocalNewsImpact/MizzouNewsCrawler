#!/usr/bin/env python3
"""Improved press-and-hold attempt with canvas/button heuristics.
Run inside extraction pod; reads TARGET_URL from env.
"""
import os
import time
import math
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

    print(f"Press-and-hold v2: {TARGET_URL}")

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
        # Core logic
        driver.get(TARGET_URL)
        # wait up to 30s for challenge
        end = time.time() + 30
        challenge = False
        el = None
        while time.time() < end:
            time.sleep(1)
            body = driver.find_element(By.TAG_NAME, 'body').text
            if 'Press & Hold' in body or 'Press and Hold' in body or 'Press &' in body or 'Press' in body:
                challenge = True
                break

        if not challenge:
            print('No press-and-hold text detected in body; printing short body')
            print(driver.find_element(By.TAG_NAME,'body').text[:400])

        # Try canvas elements first
        canvases = [c for c in driver.find_elements(By.TAG_NAME, 'canvas') if c.is_displayed() and (c.size.get('width',0)>10 and c.size.get('height',0)>10)]
        if canvases:
            # pick largest canvas
            canvases.sort(key=lambda x: x.size.get('width',0)*x.size.get('height',0), reverse=True)
            el = canvases[0]
            print('Found canvas element, size=', el.size)
        else:
            # Buttons and role=button
            buttons = [b for b in driver.find_elements(By.TAG_NAME, 'button') if b.is_displayed() and (b.size.get('width',0)>10 and b.size.get('height',0)>10)]
            if buttons:
                el = buttons[0]
                print('Found visible <button> element, size=', el.size)
            else:
                role_btns = [d for d in driver.find_elements(By.XPATH, "//*[(@role='button' or @role='presentation')]") if d.is_displayed() and (d.size.get('width',0)>10 and d.size.get('height',0)>10)]
                if role_btns:
                    el = role_btns[0]
                    print('Found role="button" element, size=', el.size)

        # Filter out non-interactable tags
        if el is not None and el.tag_name.lower() in ['script','style','meta']:
            print('Selected element is non-interactable tag (script/style/meta); ignoring')
            el = None

        result = 'unknown'
        action = ActionChains(driver)

        def hold_at_element(e, hold_seconds=5):
            try:
                driver.execute_script('arguments[0].scrollIntoView({block:"center"});', e)
            except Exception:
                pass
            # compute center
            loc = e.location_once_scrolled_into_view
            size = e.size
            cx = int(loc['x'] + size['width'] / 2)
            cy = int(loc['y'] + size['height'] / 2)
            print(f'Attempting click-and-hold at element center: ({cx},{cy}), hold {hold_seconds}s')

            # capture pre-click bounding rect and screenshot
            try:
                rect = driver.execute_script('return arguments[0].getBoundingClientRect()', e)
                with open('/tmp/press_hold_rect.json', 'w') as _f:
                    import json
                    _f.write(json.dumps(rect))
            except Exception:
                rect = None
            try:
                pre_ss = '/tmp/press_hold_before.png'
                driver.save_screenshot(pre_ss)
                print('Saved before-click screenshot to', pre_ss)
            except Exception as ex:
                print('Failed to save pre-click screenshot:', ex)

            try:
                action.move_to_element_with_offset(e, size['width']/2 - 1, size['height']/2 - 1).click_and_hold().perform()
                # screenshot during hold
                try:
                    during_ss = '/tmp/press_hold_during.png'
                    driver.save_screenshot(during_ss)
                    print('Saved during-click screenshot to', during_ss)
                except Exception as ex:
                    print('Failed to save during-click screenshot:', ex)

                time.sleep(hold_seconds)

                # screenshot just before release
                try:
                    pre_release_ss = '/tmp/press_hold_prerelease.png'
                    driver.save_screenshot(pre_release_ss)
                    print('Saved pre-release screenshot to', pre_release_ss)
                except Exception as ex:
                    print('Failed to save pre-release screenshot:', ex)

                action.release().perform()

                # screenshot after release
                try:
                    after_ss = '/tmp/press_hold_after.png'
                    driver.save_screenshot(after_ss)
                    print('Saved after-release screenshot to', after_ss)
                except Exception as ex:
                    print('Failed to save after-release screenshot:', ex)

                return True
            except Exception as ex:
                print('ActionChain click-and-hold failed:', ex)
                # fallback to JS pointer events
                try:
                    print('Fallback: dispatching pointerdown/up via JS')
                    driver.execute_script("""
                        var x = arguments[0], y = arguments[1];
                        var el = document.elementFromPoint(x, y);
                        function dispatch(type){
                          var ev = new PointerEvent(type, {bubbles:true,clientX:x,clientY:y, pointerType:'mouse'});
                          el.dispatchEvent(ev);
                        }
                        dispatch('pointerdown');
                    """, cx, cy)

                    # screenshot during fallback hold
                    try:
                        fallback_during_ss = '/tmp/press_hold_fallback_during.png'
                        driver.save_screenshot(fallback_during_ss)
                        print('Saved fallback during-click screenshot to', fallback_during_ss)
                    except Exception as ex2:
                        print('Failed to save fallback during screenshot:', ex2)

                    time.sleep(hold_seconds)
                    driver.execute_script("""
                        var x = arguments[0], y = arguments[1];
                        var el = document.elementFromPoint(x, y);
                        function dispatch(type){
                          var ev = new PointerEvent(type, {bubbles:true,clientX:x,clientY:y, pointerType:'mouse'});
                          el.dispatchEvent(ev);
                        }
                        dispatch('pointerup');
                    """, cx, cy)
                    return True
                except Exception as ex2:
                    print('JS pointer fallback failed:', ex2)
                    return False

        HOLD_SECONDS = int(os.environ.get('HOLD_SECONDS', '8'))
        if el is not None:
            ok = hold_at_element(el, hold_seconds=HOLD_SECONDS)
            if ok:
                # allow challenge time
                time.sleep(8)
                body_after = driver.find_element(By.TAG_NAME, 'body').text
                if any(x.lower() in body_after.lower() for x in ['Press & Hold'.lower(),'press and hold','Access to this page has been denied','denied']):
                    result = 'still_blocked'
                else:
                    result = 'passed'
            else:
                result = 'action_failed'
        else:
            # fallback to center of viewport
            print('No clear interactable element found; attempting text-based search for challenge elements')
            candidates = driver.find_elements(By.XPATH, "//*[not(self::script) and not(self::style) and contains(translate(normalize-space(string(.)), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'press') and contains(translate(normalize-space(string(.)), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'hold')]")
            el_candidate = None
            for c in candidates:
                try:
                    if c.is_displayed() and c.size.get('width', 0) > 10 and c.size.get('height', 0) > 10:
                        el_candidate = c
                        break
                except Exception:
                    continue

            if el_candidate is not None:
                print('Found candidate element for challenge, size=', el_candidate.size)
                try:
                    ok = hold_at_element(el_candidate, hold_seconds=HOLD_SECONDS)
                    if ok:
                        time.sleep(8)
                        body_after = driver.find_element(By.TAG_NAME, 'body').text
                        if any(x.lower() in body_after.lower() for x in ['press & hold', 'press and hold', 'Access to this page has been denied', 'denied']):
                            result = 'still_blocked'
                        else:
                            result = 'passed'
                    else:
                        result = 'action_failed'
                except Exception as e:
                    print('Candidate interaction error:', e)
                    result = 'action_failed'
            else:
                print('No text-based candidate found; falling back to center-of-viewport hold')
                body_elem = driver.find_element(By.TAG_NAME, 'body')
                try:
                    # save before fallback
                    try:
                        fb_pre = '/tmp/press_hold_fallback_before.png'
                        driver.save_screenshot(fb_pre)
                        print('Saved fallback before-click screenshot to', fb_pre)
                    except Exception as ex:
                        print('Failed to save fallback pre-click screenshot:', ex)

                    action.move_to_element_with_offset(body_elem, 960, 540).click_and_hold().perform()

                    # save during fallback
                    try:
                        fb_during = '/tmp/press_hold_fallback_during.png'
                        driver.save_screenshot(fb_during)
                        print('Saved fallback during-click screenshot to', fb_during)
                    except Exception as ex:
                        print('Failed to save fallback during-click screenshot:', ex)

                    time.sleep(HOLD_SECONDS)
                    action.release().perform()

                    # save after fallback
                    try:
                        fb_after = '/tmp/press_hold_fallback_after.png'
                        driver.save_screenshot(fb_after)
                        print('Saved fallback after-release screenshot to', fb_after)
                    except Exception as ex:
                        print('Failed to save fallback after-click screenshot:', ex)

                    time.sleep(6)
                    body_after = driver.find_element(By.TAG_NAME, 'body').text
                    if any(x.lower() in body_after.lower() for x in ['press & hold', 'press and hold', 'Access to this page has been denied', 'denied']):
                        result = 'still_blocked'
                    else:
                        result = 'passed'
                except Exception as e:
                    print('center fallback action error:', e)
                    result = 'action_failed'

        print('Final result:', result)
        ss = '/tmp/press_hold_v2_result.png'
        try:
            driver.save_screenshot(ss)
            print('Saved screenshot to', ss)
        except Exception as e:
            print('Failed to save final screenshot:', e)
    except Exception as e:
        print('Press-and-hold v2 encountered an error:', e)
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()