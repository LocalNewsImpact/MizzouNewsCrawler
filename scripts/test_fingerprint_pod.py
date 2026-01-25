#!/usr/bin/env python3
"""Full fingerprint check on bot detection sites."""
import time
import json
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
        
        # Comprehensive fingerprint check
        fp = driver.execute_script('''
        var fp = {};
        
        // WebGL
        var c = document.createElement("canvas");
        var gl = c.getContext("webgl") || c.getContext("experimental-webgl");
        fp.webgl = gl ? "supported" : "not supported";
        if (gl) {
            var d = gl.getExtension("WEBGL_debug_renderer_info");
            fp.webgl_renderer = d ? gl.getParameter(d.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);
            fp.webgl_vendor = d ? gl.getParameter(d.UNMASKED_VENDOR_WEBGL) : gl.getParameter(gl.VENDOR);
        }
        
        // WebDriver detection
        fp.webdriver = navigator.webdriver;
        
        // Chrome detection
        fp.chrome = !!window.chrome;
        fp.chrome_runtime = !!(window.chrome && window.chrome.runtime);
        
        // Plugins
        fp.plugins_count = navigator.plugins.length;
        fp.plugins = Array.from(navigator.plugins).map(p => p.name);
        
        // Languages
        fp.languages = navigator.languages;
        fp.language = navigator.language;
        
        // Screen
        fp.screen_width = screen.width;
        fp.screen_height = screen.height;
        fp.color_depth = screen.colorDepth;
        
        // User agent
        fp.user_agent = navigator.userAgent;
        
        // Platform
        fp.platform = navigator.platform;
        
        // Hardware concurrency
        fp.hardware_concurrency = navigator.hardwareConcurrency;
        
        // Device memory
        fp.device_memory = navigator.deviceMemory;
        
        // Permissions
        fp.permissions_query = typeof navigator.permissions !== 'undefined';
        
        // Audio context
        try {
            var ac = new (window.AudioContext || window.webkitAudioContext)();
            fp.audio_context = "supported";
            ac.close();
        } catch(e) {
            fp.audio_context = "not supported: " + e.message;
        }
        
        // Canvas fingerprint test
        try {
            var canvas = document.createElement("canvas");
            canvas.width = 200;
            canvas.height = 50;
            var ctx = canvas.getContext("2d");
            ctx.textBaseline = "top";
            ctx.font = "14px Arial";
            ctx.fillText("Browser fingerprint test", 2, 2);
            fp.canvas_fp = canvas.toDataURL().substring(0, 100);
        } catch(e) {
            fp.canvas_fp = "error: " + e.message;
        }
        
        return fp;
    ''')
    
        print(json.dumps(fp, indent=2))
    
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
