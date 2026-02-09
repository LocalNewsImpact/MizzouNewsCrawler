#!/usr/bin/env python3
"""Test WebGL support in the extraction pod."""
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service


def main():
    options = Options()
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--headless=new')

    service = Service('/home/appuser/chromedriver')
    driver = webdriver.Chrome(service=service, options=options)

    try:
        driver.get('about:blank')
        r = driver.execute_script('''
            var c = document.createElement("canvas");
            var gl = c.getContext("webgl") || c.getContext("experimental-webgl");
            if (!gl) return "NOT SUPPORTED";
            var d = gl.getExtension("WEBGL_debug_renderer_info");
            return d ? gl.getParameter(d.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);
        ''')
        print('WebGL:', r)
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
