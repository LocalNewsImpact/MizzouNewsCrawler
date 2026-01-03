#!/usr/bin/env python3
"""Capture a Chrome fingerprint JSON blob from a live browser session.

Run this on the same Linux host (or container) that executes Selenium so the
resulting fingerprint matches the TLS, UA, and hardware characteristics that
servers observe. The script launches Chrome via Selenium, collects relevant
navigator/screen/WebGL properties, and writes them to a JSON file compatible
with ``fingerprint_profile.load_fingerprint_profile``.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

logger = logging.getLogger(__name__)

# JavaScript executed inside Chrome to collect fingerprint details. The script
# uses an async callback so we can await high-entropy UA client hints.
_JS_COLLECT_FINGERPRINT = r"""
const done = arguments[0];
(async () => {
  try {
    const nav = window.navigator;
    const screen = window.screen || {};

    let uaData = null;
    if (nav.userAgentData) {
      const lowEntropy = nav.userAgentData.toJSON ? nav.userAgentData.toJSON() : {};
      const highEntropy = await nav.userAgentData.getHighEntropyValues([
        "platform",
        "platformVersion",
        "architecture",
        "model",
        "bitness",
        "uaFullVersion",
        "fullVersionList",
      ]);
      uaData = Object.assign({}, lowEntropy, highEntropy);
    }

    const describeWebGL = () => {
      const canvas = document.createElement('canvas');
      const ctx = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
      if (!ctx) {
        return null;
      }
      const debugInfo = ctx.getExtension('WEBGL_debug_renderer_info');
      if (!debugInfo) {
        return null;
      }
      const vendor = ctx.getParameter(debugInfo.UNMASKED_VENDOR_WEBGL);
      const renderer = ctx.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL);
      return {
        webglVendor: vendor || null,
        webglRenderer: renderer || null,
      };
    };

    done({
      userAgent: nav.userAgent,
      uaData,
      navigator: {
        platform: nav.platform,
        hardwareConcurrency: nav.hardwareConcurrency,
        maxTouchPoints: nav.maxTouchPoints,
        language: nav.language,
        languages: nav.languages,
        deviceMemory: nav.deviceMemory ?? null,
      },
      screen: {
        width: screen.width,
        height: screen.height,
        availWidth: screen.availWidth,
        availHeight: screen.availHeight,
        colorDepth: screen.colorDepth,
        pixelDepth: screen.pixelDepth,
      },
      webgl: describeWebGL(),
    });
  } catch (err) {
    done({ error: err && err.message ? err.message : String(err) });
  }
})();
"""


def _build_driver(headless: bool, window_size: tuple[int, int]) -> webdriver.Chrome:
  options = Options()
  if headless:
    # Use headless=new so UA/client hints match modern Chrome as closely as possible.
    options.add_argument("--headless=new")
  options.add_argument("--disable-dev-shm-usage")
  options.add_argument("--disable-gpu")
  options.add_argument("--no-sandbox")
  driver = webdriver.Chrome(options=options)
  driver.set_window_size(*window_size)
  return driver


def _write_output(path: Path, payload: dict[str, Any]) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def capture_fingerprint(url: str, output: Path, headless: bool, window_size: tuple[int, int]) -> None:
  driver = _build_driver(headless=headless, window_size=window_size)
  try:
    driver.get(url)
    result = driver.execute_async_script(_JS_COLLECT_FINGERPRINT)
    if isinstance(result, dict) and result.get("error"):
      raise RuntimeError(f"Fingerprint collection failed: {result['error']}")
    _write_output(output, result)
    logger.info("Fingerprint written to %s", output)
  finally:
    driver.quit()


def parse_window_size(raw: str) -> tuple[int, int]:
  try:
    width_str, height_str = raw.lower().split("x", 1)
    width = int(width_str)
    height = int(height_str)
    if width <= 0 or height <= 0:
      raise ValueError
    return width, height
  except ValueError as exc:  # pragma: no cover - CLI validation
    raise argparse.ArgumentTypeError("Window size must be WIDTHxHEIGHT, e.g. 1920x1080") from exc


def main() -> None:  # pragma: no cover - CLI entrypoint
  parser = argparse.ArgumentParser(description="Capture a Chrome fingerprint JSON blob.")
  parser.add_argument(
    "--output",
    type=Path,
    default=Path("fingerprints/linux-default.json"),
    help="Destination path for the fingerprint JSON (default: fingerprints/linux-default.json)",
  )
  parser.add_argument(
    "--url",
    default="https://example.com/",
    help="URL to load before capturing fingerprint data (default: https://example.com/)",
  )
  parser.add_argument(
    "--headless",
    action="store_true",
    help="Run Chrome in headless mode (defaults to headed, which better matches production extractors)",
  )
  parser.add_argument(
    "--window-size",
    dest="window_size",
    type=parse_window_size,
    default=parse_window_size("1920x1080"),
    metavar="WIDTHxHEIGHT",
    help="Window size to set before capture (default: 1920x1080)",
  )
  parser.add_argument(
    "--log-level",
    default="INFO",
    choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    help="Logging verbosity (default: INFO)",
  )

  args = parser.parse_args()
  logging.basicConfig(level=getattr(logging, args.log_level))
  capture_fingerprint(
    url=args.url,
    output=args.output,
    headless=args.headless,
    window_size=args.window_size,
  )


if __name__ == "__main__":
  main()
