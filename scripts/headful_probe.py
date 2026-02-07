import argparse
import json
import os
import time


def run_probe(url: str, outfile: str, timeout: int = 45, user_agent: str | None = None) -> dict:
    ua = user_agent or (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    )

    info: dict = {
        "url": url,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": None,
        "server": None,
        "cf_ray": None,
        "cf_challenge_detected": False,
        "title": None,
        "page_length": None,
        "screenshot_path": outfile,
    }

    driver = None
    try:
        try:
            import undetected_chromedriver as uc  # type: ignore
            from selenium.webdriver.common.desired_capabilities import (
                DesiredCapabilities,
            )

            options = uc.ChromeOptions()
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_argument(f"--user-agent={ua}")
            options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

            driver = uc.Chrome(options=options, headless=False)
        except Exception:
            from selenium import webdriver  # type: ignore
            from selenium.webdriver.chrome.options import Options  # type: ignore
            from selenium.webdriver.common.desired_capabilities import (
                DesiredCapabilities,
            )

            options = Options()
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_argument(f"--user-agent={ua}")
            caps = DesiredCapabilities.CHROME.copy()
            caps["goog:loggingPrefs"] = {"performance": "ALL"}
            driver = webdriver.Chrome(options=options, desired_capabilities=caps)

        driver.set_page_load_timeout(timeout)
        driver.get(url)
        title = driver.title
        source = driver.page_source or ""
        info["title"] = title
        info["page_length"] = len(source)

        patterns = [
            "Managed Challenge",
            "Just a moment",
            "cf-error",
            "cf_chl",
            'data-translate="managed_challenge"',
            "cf-chl-",
            "window._cf_chl_",
        ]
        if any(p.lower() in source.lower() for p in patterns):
            info["cf_challenge_detected"] = True

        logs = []
        try:
            logs = driver.get_log("performance")
        except Exception:
            logs = []

        status = None
        headers: dict = {}
        for entry in logs:
            try:
                msg = json.loads(entry.get("message", "{}"))["message"]
            except Exception:
                continue
            if msg.get("method") == "Network.responseReceived":
                resp = msg.get("params", {}).get("response", {})
                if resp.get("type") == "Document":
                    status = resp.get("status")
                    headers = resp.get("headers", {})
                    break

        info["status"] = status
        info["server"] = headers.get("server") or headers.get("Server")
        info["cf_ray"] = headers.get("cf-ray") or headers.get("CF-RAY")
        try:
            driver.save_screenshot(outfile)
        except Exception:
            pass
    finally:
        try:
            if driver:
                driver.quit()
        except Exception:
            pass

    return info


def main() -> None:
    parser = argparse.ArgumentParser(description="Headful Selenium probe")
    parser.add_argument("--url", required=True)
    parser.add_argument("--outfile", default="/tmp/headful_probe.png")
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--ua", default=None)
    args = parser.parse_args()

    result = run_probe(args.url, args.outfile, args.timeout, args.ua)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
