#!/usr/bin/env python3
"""Test Decodo unblock proxy for PerimeterX bypass"""
import undetected_chromedriver as uc
from selenium_stealth import stealth
import zipfile
import tempfile
import time
import os
from selenium.webdriver.common.by import By

print("Starting Decodo unblock proxy test...")

chrome_bin = "/usr/bin/chromium"
driver_path = "/home/appuser/chromedriver"
options = uc.ChromeOptions()
options.add_argument("--headless=new")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# Decodo unblock proxy credentials
proxy_host = "unblock.decodo.com"
proxy_port = "60000"
proxy_user = "U0000332559"
proxy_pass = "PW_1b20cd078bbfbf554faa89e9af56f7ea8"
print(f"Proxy: {proxy_host}:{proxy_port}")

# Create Chrome extension for proxy auth
manifest = '{"version":"1.0.0","manifest_version":2,"name":"ProxyAuth","permissions":["proxy","tabs","unlimitedStorage","storage","<all_urls>","webRequest","webRequestBlocking"],"background":{"scripts":["background.js"]}}'

background = f"""
var config = {{
    mode: "fixed_servers",
    rules: {{
        singleProxy: {{
            scheme: "http",
            host: "{proxy_host}",
            port: {proxy_port}
        }}
    }}
}};
chrome.proxy.settings.set({{value: config, scope: "regular"}}, function() {{}});
chrome.webRequest.onAuthRequired.addListener(
    function(details) {{
        return {{
            authCredentials: {{
                username: "{proxy_user}",
                password: "{proxy_pass}"
            }}
        }};
    }},
    {{urls: ["<all_urls>"]}},
    ['blocking']
);
"""

ext_path = tempfile.mktemp(suffix=".zip")
try:
    with zipfile.ZipFile(ext_path, "w") as zp:
        zp.writestr("manifest.json", manifest)
        zp.writestr("background.js", background)

    options.add_extension(ext_path)

    print("Creating driver...")
    driver = uc.Chrome(
        options=options,
        version_main=None,
        headless=False,
        use_subprocess=False,
        log_level=3,
        driver_executable_path=driver_path,
        browser_executable_path=chrome_bin
    )

    print("Applying stealth...")
    stealth(driver, languages=["en-US"], vendor="Google Inc.", platform="Win32", 
            webgl_vendor="Intel Inc.", renderer="Intel Iris", fix_hairline=True)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    driver.set_page_load_timeout(30)

    url = "https://fox2now.com/news/missouri/woman-critically-injured-in-overnight-shooting-in-south-st-louis"
    print(f"Loading: {url}")
    driver.get(url)
    time.sleep(8)

    title = driver.title
    html_len = len(driver.page_source)
    print(f"\nTitle: {title}")
    print(f"HTML: {html_len} bytes")

    if "Access to this page has been denied" in title:
        print("❌ BLOCKED by PerimeterX")
    elif html_len > 100000:
        print("✅ SUCCESS - FULL PAGE LOADED")
        try:
            h1 = driver.find_element(By.CSS_SELECTOR, "h1").text
            print(f"H1: {h1[:100]}")
        except Exception as e:
            print(f"H1 error: {e}")
    else:
        print(f"⚠️  PARTIAL: {html_len} bytes")

    driver.quit()
finally:
    if os.path.exists(ext_path):
        os.unlink(ext_path)

print("Test complete.")
