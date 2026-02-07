import os
import sys
import logging
import time

# Ensure project root is importable when running in pod
try:
    from src.crawler import ContentExtractor
except Exception as e:
    print(f"Import error: {e}")
    sys.exit(2)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main():
    print("=== Selenium Sanity Check ===")
    print(f"CHROME_BIN={os.getenv('CHROME_BIN')}")
    print(f"GOOGLE_CHROME_BIN={os.getenv('GOOGLE_CHROME_BIN')}")
    print(f"CHROMEDRIVER_PATH={os.getenv('CHROMEDRIVER_PATH')}")
    print(f"SELENIUM_EXECUTION_MODE={os.getenv('SELENIUM_EXECUTION_MODE')}")
    print(f"SELENIUM_FORCE_HEADLESS={os.getenv('SELENIUM_FORCE_HEADLESS')}")
    print(f"DISPLAY={os.getenv('DISPLAY')}")
    print(f"SQUID_PROXY_URL={os.getenv('SQUID_PROXY_URL')}")
    print(f"SELENIUM_PROXY={os.getenv('SELENIUM_PROXY')}")

    # Default to headless for sanity checks to avoid display issues in containers
    selenium_mode = os.getenv("SELENIUM_EXECUTION_MODE", "headless")
    extractor = ContentExtractor(selenium_mode=selenium_mode)

    try:
        driver = extractor.get_persistent_driver()
    except Exception as e:
        logging.error(f"Driver creation failed: {e}")
        sys.exit(1)

    try:
        # Report browser/driver capabilities
        caps = getattr(driver, "capabilities", {}) or {}
        print(f"Browser Version: {caps.get('browserVersion')}")
        print(f"Driver: {driver.__class__.__name__}")

        # User agent via CDP/JS
        try:
            ua = driver.execute_script("return navigator.userAgent")
            print(f"Navigator UA: {ua}")
        except Exception as e:
            print(f"UA check failed: {e}")

        # Simple navigation
        test_url = os.getenv("SANITY_TEST_URL", "https://example.com")
        logging.info(f"Navigating to {test_url}")
        driver.set_page_load_timeout(30)
        driver.get(test_url)
        time.sleep(1)
        print(f"Page title: {driver.title}")
        print("Sanity check succeeded.")
        code = 0
    except Exception as e:
        logging.error(f"Navigation failed: {e}")
        code = 1
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    sys.exit(code)


if __name__ == "__main__":
    main()
