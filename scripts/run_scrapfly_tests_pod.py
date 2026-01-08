#!/usr/bin/env python3
"""Run full Scrapfly web-tools suite from inside the extraction pod.
Saves screenshots, HTML, and text output in /tmp/scrapfly_artifacts/ and writes a result JSON.
Designed to be run inside the extraction pod with Xvfb active.
"""
import os
import time
import json
from urllib.parse import urlparse
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

OUT_DIR = '/tmp/scrapfly_artifacts'
os.makedirs(OUT_DIR, exist_ok=True)

TESTS = [
    ('ip-info', 'https://scrapfly.io/web-scraping-tools/ip-info'),
    ('ja3-fingerprint', 'https://scrapfly.io/web-scraping-tools/ja3-fingerprint'),
    ('http2-fingerprint', 'https://scrapfly.io/web-scraping-tools/http2-fingerprint'),
    ('browser-fingerprint', 'https://scrapfly.io/web-scraping-tools/browser-fingerprint'),
    ('canvas-fingerprint', 'https://scrapfly.io/web-scraping-tools/canvas-fingerprint'),
    ('webgl-fingerprint', 'https://scrapfly.io/web-scraping-tools/webgl-fingerprint'),
    ('audio-fingerprint', 'https://scrapfly.io/web-scraping-tools/audio-fingerprint'),
    ('fonts', 'https://scrapfly.io/web-scraping-tools/fonts'),
    ('math-engine', 'https://scrapfly.io/web-scraping-tools/math-engine'),
    ('gpu-fingerprint', 'https://scrapfly.io/web-scraping-tools/gpu-fingerprint'),
    ('screen-fingerprint', 'https://scrapfly.io/web-scraping-tools/screen-fingerprint'),
    ('media-codecs', 'https://scrapfly.io/web-scraping-tools/media-codecs'),
    ('drm-capabilities', 'https://scrapfly.io/web-scraping-tools/drm-capabilities'),
    ('speech-voices', 'https://scrapfly.io/web-scraping-tools/speech-synthesis-voices'),
    ('webrtc-leak', 'https://scrapfly.io/web-scraping-tools/webrtc-leak'),
    ('dns-leak', 'https://scrapfly.io/web-scraping-tools/dns-leak'),
    ('timezone-intl', 'https://scrapfly.io/web-scraping-tools/timezone-intl'),
    ('performance-inspector', 'https://scrapfly.io/web-scraping-tools/performance-inspector'),
]

PROXY = os.environ.get('SELENIUM_PROXY')
CHROME_BIN = os.environ.get('CHROME_BIN', '/usr/bin/google-chrome')
CHROMEDRIVER = os.environ.get('CHROMEDRIVER_PATH', '/home/appuser/chromedriver')

# Selenium options (HEADFUL)
options = Options()
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')
options.add_argument('--disable-blink-features=AutomationControlled')
options.add_argument('--window-size=1920,1080')
options.add_argument('--start-maximized')
# real UA
options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36')
if PROXY:
    options.add_argument(f'--proxy-server={PROXY}')
options.add_experimental_option('excludeSwitches', ['enable-automation'])
options.add_experimental_option('useAutomationExtension', False)

service = Service(CHROMEDRIVER)

driver = webdriver.Chrome(service=service, options=options)

# Inject anti-detection script
# - Normalize timezone to America/Chicago
# - Stub WebRTC to prevent ICE candidate leaks
# - Normalize navigator properties (plugins, languages, platform, memory, hardwareConcurrency)
# - Minimal canvas safety wrapper
driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
    'source': """
(function() {
    // Timezone normalization
    try {
        const tz = 'America/Chicago';
        const origGetTimezoneOffset = Date.prototype.getTimezoneOffset;
        Date.prototype.getTimezoneOffset = function() {
            try {
                const local = new Date(this.valueOf());
                const tzDate = new Date(local.toLocaleString('en-US', {timeZone: tz}));
                return Math.round((local.getTime() - tzDate.getTime()) / 60000);
            } catch (e) {
                return origGetTimezoneOffset.call(this);
            }
        };
        const origResolved = Intl.DateTimeFormat.prototype.resolvedOptions;
        Intl.DateTimeFormat.prototype.resolvedOptions = function() {
            const ro = origResolved.call(this);
            ro.timeZone = tz;
            return ro;
        };
    } catch (e) {
        // ignore
    }

    // Stub WebRTC to prevent IP leaks
    try {
        class FakeRTCPeerConnection {
            constructor() { this._listeners = {}; }
            addEventListener(type, listener){ this._listeners[type] = this._listeners[type] || []; this._listeners[type].push(listener); }
            removeEventListener(type, listener){ if(this._listeners[type]) this._listeners[type] = this._listeners[type].filter(l => l !== listener); }
            close(){}
            createDataChannel(){ return {}; }
            createOffer(){ return Promise.resolve({}); }
            createAnswer(){ return Promise.resolve({}); }
            setLocalDescription(){ return Promise.resolve(); }
            setRemoteDescription(){ return Promise.resolve(); }
            addIceCandidate(){ return Promise.resolve(); }
            getStats(){ return Promise.resolve([]); }
        }
        Object.defineProperty(window, 'RTCPeerConnection', { value: FakeRTCPeerConnection, configurable: true });
        Object.defineProperty(window, 'webkitRTCPeerConnection', { value: FakeRTCPeerConnection, configurable: true });
        Object.defineProperty(window, 'mozRTCPeerConnection', { value: FakeRTCPeerConnection, configurable: true });
        try { Object.defineProperty(window, 'RTCIceCandidate', { value: function(){ return {}; }, configurable: true }); } catch(e) {}
        if (!navigator.mediaDevices) navigator.mediaDevices = {};
        navigator.mediaDevices.getUserMedia = function(){ return Promise.reject(new Error('getUserMedia disabled')); };
        navigator.mediaDevices.enumerateDevices = function(){ return Promise.resolve([]); };
    } catch (e) {
        // ignore
    }

    // Normalize navigator properties
    try {
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined, configurable: true });
        Object.defineProperty(navigator, 'languages', { get: () => ['en-US','en'], configurable: true });
        Object.defineProperty(navigator, 'platform', { get: () => 'Win32', configurable: true });
        Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 4, configurable: true });
        Object.defineProperty(navigator, 'deviceMemory', { get: () => 8, configurable: true });
        Object.defineProperty(navigator, 'plugins', { get: () => [
            {name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer'},
            {name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai'},
            {name: 'Native Client', filename: 'internal-nacl-plugin'}
        ], configurable: true });
        try { Object.defineProperty(navigator, 'vendor', { get: () => 'Google Inc.', configurable: true }); } catch(e){}
    } catch (e) {
        // ignore
    }

    // Minimal canvas safety wrapper (keep default behavior but ensure stable results)
    try {
        const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
        HTMLCanvasElement.prototype.toDataURL = function(type, params) {
            try {
                // Ensure a stable font is set when the page draws text
                try { this.getContext('2d').font = this.getContext('2d').font || '14px Arial'; } catch(e) {}
                return origToDataURL.call(this, type, params);
            } catch (e) {
                return origToDataURL.call(this, type, params);
            }
        };
        // Wrap getContext to enforce a consistent 2D context behavior
        const origGetContext = HTMLCanvasElement.prototype.getContext;
        HTMLCanvasElement.prototype.getContext = function(type, ...args) {
            const ctx = origGetContext.call(this, type, ...args);
            if (type === '2d' && ctx) {
                try {
                    const origFillText = ctx.fillText;
                    ctx.fillText = function(text, x, y, maxWidth) {
                        // normalize font
                        try { ctx.font = '14px Arial'; } catch(e) {}
                        return origFillText.call(this, text, x, y, maxWidth);
                    };
                } catch(e) {}
            }
            return ctx;
        };
    } catch (e) {
        // ignore
    }

    // Expose userAgentData client hints to match Windows/Chrome
    try {
        const uaData = {
            brands: [{brand: 'Chromium', version: '143'}, {brand: 'Google Chrome', version: '143'}],
            mobile: false,
            getHighEntropyValues: (hints) => Promise.resolve({
                architecture: 'x86',
                model: '',
                platform: 'Windows',
                platformVersion: '',
                uaFullVersion: '143.0.0.0',
                fullVersionList: [{brand: 'Chromium', version: '143.0.0.0'}, {brand: 'Google Chrome', version: '143.0.0.0'}]
            })
        };
        Object.defineProperty(navigator, 'userAgentData', { get: () => uaData, configurable: true });
    } catch (e) {}

})();
    """
})

# Set client hints headers to match userAgentData
try:
    driver.execute_cdp_cmd('Network.setExtraHTTPHeaders', {'headers': {
        'sec-ch-ua': '"Chromium";v="143", "Not A(Brand";v="24", "Google Chrome";v="143"',
        'sec-ch-ua-platform': '"Windows"',
        'sec-ch-ua-mobile': '?0'
    }})
except Exception:
    pass

results = []

for name, url in TESTS:
    print(f'Running test: {name} -> {url}')
    item = {'name': name, 'url': url, 'status': 'started'}
    try:
        driver.get(url)
        # Wait for document.readyState == complete
        try:
            WebDriverWait(driver, 20).until(lambda d: d.execute_script('return document.readyState') == 'complete')
        except Exception:
            pass

        # Click any obvious run/test buttons if present
        try:
            buttons = driver.find_elements(By.TAG_NAME, 'button')
            for b in buttons:
                txt = (b.text or '').strip().lower()
                if any(k in txt for k in ['run', 'test', 'start']):
                    try:
                        print('Clicking button:', txt[:30])
                        b.click()
                        time.sleep(1)
                    except Exception:
                        pass
        except Exception:
            pass

        # Wait a few seconds for client-side tests to complete
        time.sleep(8)

        # Save screenshot, HTML, and body text
        slug = name.replace('/', '_')
        ss = os.path.join(OUT_DIR, f'{slug}.png')
        htmlp = os.path.join(OUT_DIR, f'{slug}.html')
        txtp = os.path.join(OUT_DIR, f'{slug}.txt')

        driver.save_screenshot(ss)
        with open(htmlp, 'w', encoding='utf-8') as f:
            f.write(driver.page_source)
        try:
            body_text = driver.find_element(By.TAG_NAME, 'body').text
        except Exception:
            body_text = driver.execute_script('return document.body ? document.body.innerText : ""') or ''
        with open(txtp, 'w', encoding='utf-8') as f:
            f.write(body_text)

        # Basic heuristics for blocked detection
        blocked_keywords = ['access to this page has been denied', 'press & hold', 'blocked', 'denied']
        is_blocked = any(k in body_text.lower() for k in blocked_keywords)

        item.update({'status':'ok', 'screenshot':ss, 'html':htmlp, 'text':txtp, 'blocked':is_blocked})
    except Exception as exc:
        print('Error running test', name, exc)
        item.update({'status':'error', 'error': str(exc)})
    results.append(item)

# Write results JSON
res_path = os.path.join(OUT_DIR, 'scrapfly_results.json')
with open(res_path, 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=2)

print('Completed tests, artifacts in', OUT_DIR)
print('Results written to', res_path)

driver.quit()
