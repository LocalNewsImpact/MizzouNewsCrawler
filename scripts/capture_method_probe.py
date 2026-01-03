#!/usr/bin/env python
from __future__ import annotations

import argparse
import asyncio
import atexit
import hashlib
import shlex
import json
import logging
import os
import random
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlparse

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.crawler import (  # noqa: E402
    ContentExtractor,
    ProxyChallengeError,
    RateLimitError,
)

try:  # noqa: E402
    import cloudscraper
except Exception:  # pragma: no cover - optional dependency
    cloudscraper = None

try:  # noqa: E402
    from playwright.async_api import async_playwright
except Exception:  # pragma: no cover - optional dependency
    async_playwright = None

try:  # noqa: E402
    from pyvirtualdisplay import Display
except Exception:  # pragma: no cover - optional dependency
    Display = None

DEFAULT_METHODS = (
    "requests,cloudscraper,mcmetadata,newspaper4k,beautifulsoup,"
    "unblock_proxy,selenium_basic,selenium_stealth,selenium_profile,"
    "playwright,playwright_persistent"
)


@dataclass
class MethodOutcome:
    method: str
    url: str
    status: str
    elapsed_sec: float
    title: str | None = None
    publish_date: str | None = None
    content_chars: int | None = None
    content_hash: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    artifact_paths: dict[str, str] = field(default_factory=dict)

    def to_summary(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["elapsed_sec"] = round(self.elapsed_sec, 3)
        return payload


class SkipMethod(Exception):
    pass


def slugify(text: str) -> str:
    parsed = urlparse(text)
    base = f"{parsed.netloc}{parsed.path}"
    cleaned = [c if c.isalnum() else "-" for c in base]
    squashed = "-".join(filter(None, "".join(cleaned).split("-")))
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:6]
    combined = f"{squashed[:80]}-{digest}" if squashed else digest
    return combined.strip("-") or digest


def load_urls(args: argparse.Namespace, allow_empty: bool = False) -> list[str]:
    urls: list[str] = []
    if args.urls:
        urls.extend(args.urls)
    if args.urls_file:
        text = Path(args.urls_file).read_text(encoding="utf-8")
        urls.extend([line.strip() for line in text.splitlines() if line.strip()])
    deduped = list(dict.fromkeys(urls))
    if not deduped and not allow_empty:
        raise SystemExit("No URLs provided. Use --url, --urls-file, or --stdin-loop.")
    return deduped


def parse_json_flag(value: str | None, flag_name: str) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON for {flag_name}: {exc}") from exc


def parse_proxy(proxy_url: str | None) -> tuple[dict[str, str] | None, dict[str, str]]:
    if not proxy_url:
        return None, {}
    parsed = urlparse(proxy_url)
    if not parsed.scheme or not parsed.hostname:
        raise SystemExit(f"Invalid proxy URL: {proxy_url}")
    proxy_dict = {"http": proxy_url, "https": proxy_url}
    playwright_cfg: dict[str, str] = {"server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"}
    if parsed.username:
        playwright_cfg["username"] = parsed.username
    if parsed.password:
        playwright_cfg["password"] = parsed.password
    return proxy_dict, playwright_cfg


def configure_logging(level: str):
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )


class CaptureProbe:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.stdin_loop_enabled = bool(getattr(args, "stdin_loop", False))
        self.urls = load_urls(args, allow_empty=self.stdin_loop_enabled)
        proxy_dict, playwright_cfg = parse_proxy(args.proxy)
        self.proxy_dict = proxy_dict
        self.playwright_proxy = playwright_cfg
        self.extractor = ContentExtractor()
        self.playwright_user_data_dir = (
            Path(args.playwright_user_data_dir).expanduser() if args.playwright_user_data_dir else None
        )
        self.playwright_channel = args.playwright_channel or None
        self.playwright_executable_path = (
            Path(args.playwright_executable_path).expanduser()
            if args.playwright_executable_path
            else None
        )
        if self.playwright_executable_path and self.playwright_channel:
            raise SystemExit("--playwright-executable-path cannot be combined with --playwright-channel")
        self.playwright_extra_args = shlex.split(args.playwright_extra_args or "")
        self.selenium_user_data_dir = (
            Path(args.selenium_user_data_dir).expanduser() if args.selenium_user_data_dir else None
        )
        self.selenium_profile_directory = args.selenium_profile_directory
        self.selenium_user_agent = args.selenium_user_agent
        self.selenium_client_hints = parse_json_flag(args.selenium_client_hints, "--selenium-client-hints")
        if self.selenium_client_hints and not isinstance(self.selenium_client_hints, dict):
            raise SystemExit("--selenium-client-hints must be a JSON object")
        self.reuse_selenium_profile_session = bool(getattr(args, "reuse_selenium_profile_session", False))
        self.auto_press_hold = bool(args.auto_press_hold)
        self.press_hold_duration = max(args.press_hold_duration, 0.5)
        self.press_hold_wait = max(args.press_hold_wait, 1.0)
        self.virtual_display_enabled = bool(args.virtual_display)
        self.virtual_display_size = self._parse_display_size(args.virtual_display_size)
        env_vdisplay = os.getenv("CAPTURE_XVFB_BINARY")
        env_vdisplay_libdir = os.getenv("CAPTURE_XVFB_LIBDIR")
        self.virtual_display_binary = (
            Path(args.virtual_display_binary).expanduser()
            if args.virtual_display_binary
            else (Path(env_vdisplay).expanduser() if env_vdisplay else None)
        )
        libdir_source = args.virtual_display_libdir or env_vdisplay_libdir
        self.virtual_display_libdirs: list[Path] = []
        if libdir_source:
            for token in str(libdir_source).split(os.pathsep):
                token = token.strip()
                if token:
                    self.virtual_display_libdirs.append(Path(token).expanduser())
        self.virtual_display = None
        if self.virtual_display_binary and self.virtual_display_binary.exists():
            os.environ["PATH"] = f"{self.virtual_display_binary.parent}:{os.environ.get('PATH', '')}"
        if self.virtual_display_libdirs:
            existing_ld = os.environ.get("LD_LIBRARY_PATH", "")
            extra_ld = os.pathsep.join(
                str(path)
                for path in self.virtual_display_libdirs
                if path.exists()
            )
            if extra_ld:
                os.environ["LD_LIBRARY_PATH"] = (
                    f"{extra_ld}{os.pathsep}{existing_ld}"
                    if existing_ld
                    else extra_ld
                )
        self.fingerprint_profile = self._load_fingerprint_profile(args.fingerprint_file)
        self.fingerprint_script = self._build_fingerprint_script(self.fingerprint_profile)
        self.fingerprint_language = None
        if self.fingerprint_profile:
            self._apply_fingerprint_defaults()
        self.window_width, self.window_height = self._resolve_window_size()
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        self.run_dir = (args.output_dir or (REPO_ROOT / "debug" / "capture-methods")) / timestamp
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.method_registry: dict[str, Callable[[str, Path], dict[str, Any]]] = {
            "requests": self._method_requests,
            "cloudscraper": self._method_cloudscraper,
            "mcmetadata": self._method_mcmetadata,
            "newspaper4k": self._method_newspaper,
            "beautifulsoup": self._method_beautifulsoup,
            "unblock_proxy": self._method_unblock,
            "selenium_basic": self._method_selenium_basic,
            "selenium_stealth": self._method_selenium_stealth,
            "selenium_profile": self._method_selenium_profile,
            "playwright": self._method_playwright,
            "playwright_persistent": self._method_playwright_persistent,
        }
        self.methods = self._resolve_methods(args.methods)
        self._selenium_profile_driver = None
        self._outcomes: list[MethodOutcome] = []
        if self.virtual_display_enabled:
            self._start_virtual_display()

    def _resolve_methods(self, raw: str | None) -> list[str]:
        if not raw or raw.strip().lower() == "all":
            return list(self.method_registry.keys())
        selected: list[str] = []
        for token in raw.split(","):
            key = token.strip().lower().replace("-", "_")
            if not key:
                continue
            if key not in self.method_registry:
                raise SystemExit(f"Unknown method: {token}")
            selected.append(key)
        if not selected:
            raise SystemExit("No valid methods selected")
        return selected

    def _parse_display_size(self, raw: str | None) -> tuple[int, int]:
        default = (1440, 900)
        if not raw:
            return default
        try:
            width_str, height_str = raw.lower().split("x", 1)
            width, height = int(width_str), int(height_str)
            return max(width, 640), max(height, 480)
        except Exception:
            logging.warning("Invalid --virtual-display-size value '%s'; falling back to %sx%s", raw, *default)
            return default

    def _load_fingerprint_profile(self, path: Path | None) -> dict[str, Any] | None:
        if not path:
            return None
        try:
            data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
        except Exception as exc:
            raise SystemExit(f"Unable to read fingerprint file {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise SystemExit("Fingerprint file must contain a JSON object")
        return data

    def _apply_fingerprint_defaults(self):
        if not self.fingerprint_profile:
            return
        ua = self.fingerprint_profile.get("userAgent")
        if ua and not self.selenium_user_agent:
            self.selenium_user_agent = ua
        ua_data = self.fingerprint_profile.get("uaData")
        navigator = self.fingerprint_profile.get("navigator") or {}
        if navigator.get("language"):
            self.fingerprint_language = navigator["language"]
        if self.selenium_client_hints is None:
            hint_payload: dict[str, Any] = {}
            if ua_data:
                hint_payload["userAgentMetadata"] = ua_data
            platform = None
            if isinstance(ua_data, dict):
                platform = ua_data.get("platform")
            platform = platform or navigator.get("platform")
            if platform:
                hint_payload["platform"] = platform
            if navigator.get("language"):
                hint_payload["acceptLanguage"] = navigator["language"]
            if hint_payload:
                self.selenium_client_hints = hint_payload

    def _build_fingerprint_script(self, profile: dict[str, Any] | None) -> str | None:
        if not profile:
            return None
        navigator = dict(profile.get("navigator") or {})
        if profile.get("userAgent") and "userAgent" not in navigator:
            navigator["userAgent"] = profile["userAgent"]
        screen = profile.get("screen") or {}
        webgl = profile.get("webgl") or {}
        lines: list[str] = [
            "(function() {",
            "  const define = (obj, prop, value) => {",
            "    if (!obj || value === undefined) { return; }",
            "    try { Object.defineProperty(obj, prop, { get: () => value, configurable: true }); } catch (err) {}",
            "  };",
            "  try { define(navigator, 'webdriver', undefined); } catch (err) {}",
        ]

        def add_nav(prop: str):
            if prop in navigator and navigator[prop] is not None:
                lines.append(f"  define(navigator, '{prop}', {json.dumps(navigator[prop])});")

        for key in ("userAgent", "platform", "hardwareConcurrency", "maxTouchPoints", "language", "languages", "deviceMemory"):
            add_nav(key)

        if screen:
            lines.append("  const screenObj = window.screen || {};")
            for key in ("width", "height", "availWidth", "availHeight", "colorDepth", "pixelDepth"):
                if key in screen and screen[key] is not None:
                    lines.append(f"  define(screenObj, '{key}', {json.dumps(screen[key])});")

        vendor = webgl.get("webglVendor")
        renderer = webgl.get("webglRenderer")
        if vendor or renderer:
            lines.extend(
                [
                    "  const spoofWebGL = (Ctor) => {",
                    "    if (!Ctor || !Ctor.prototype) { return; }",
                    "    const proto = Ctor.prototype;",
                    "    if (proto.__fingerprint_patched) { return; }",
                    "    const getParameter = proto.getParameter;",
                    "    if (!getParameter) { return; }",
                    "    Object.defineProperty(proto, '__fingerprint_patched', { value: true });",
                    "    proto.getParameter = function(param) {",
                ]
            )
            if vendor:
                lines.append(
                    f"      if (param === 37445) {{ return {json.dumps(vendor)}; }}"
                )
            if renderer:
                lines.append(
                    f"      if (param === 37446) {{ return {json.dumps(renderer)}; }}"
                )
            lines.extend(
                [
                    "      return getParameter.call(this, param);",
                    "    };",
                    "  };",
                    "  try { spoofWebGL(window.WebGLRenderingContext); } catch (err) {}",
                    "  try { spoofWebGL(window.WebGL2RenderingContext); } catch (err) {}",
                ]
            )

        lines.append("})();")
        return "\n".join(lines)

    def _resolve_window_size(self) -> tuple[int, int]:
        if self.fingerprint_profile:
            screen = self.fingerprint_profile.get("screen") or {}
            width = screen.get("width")
            height = screen.get("height")
            try:
                if width and height:
                    return int(width), int(height)
            except Exception:
                logging.debug("Invalid screen dimensions in fingerprint profile; falling back to defaults")
        return 1280, 720

    def _install_fingerprint_script_selenium(self, driver) -> None:
        if not self.fingerprint_script:
            return
        try:
            driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {"source": self.fingerprint_script},
            )
        except Exception as exc:  # pragma: no cover - diagnostic aid
            logging.debug("Unable to register fingerprint script with Selenium: %s", exc)

    def _apply_user_agent_override(self, driver) -> None:
        if not (self.selenium_user_agent or self.selenium_client_hints):
            return
        try:
            override: dict[str, Any] = {
                "userAgent": self.selenium_user_agent or driver.execute_script("return navigator.userAgent;")
            }
            if isinstance(self.selenium_client_hints, dict):
                override.update(self.selenium_client_hints)
            driver.execute_cdp_cmd("Network.enable", {})
            driver.execute_cdp_cmd("Network.setUserAgentOverride", override)
        except Exception as exc:  # pragma: no cover - diagnostic aid
            logging.debug("Unable to apply user-agent override: %s", exc)

    def _playwright_context_kwargs(self) -> dict[str, Any]:
        viewport = {"width": self.window_width, "height": self.window_height}
        user_agent = self.selenium_user_agent or random.choice(self.extractor.user_agent_pool)
        kwargs: dict[str, Any] = {
            "user_agent": user_agent,
            "viewport": viewport,
            "proxy": self.playwright_proxy or None,
        }
        if self.fingerprint_language:
            kwargs["locale"] = self.fingerprint_language
            kwargs["extra_http_headers"] = {"Accept-Language": self.fingerprint_language}
        return kwargs

    def _build_press_hold_plan(self, width: float | None, height: float | None) -> dict[str, Any]:
        width = float(width or 120.0)
        height = float(height or 40.0)
        width = max(width, 20.0)
        height = max(height, 20.0)
        center_x = width / 2.0
        center_y = height / 2.0
        start_offset = (
            center_x + random.uniform(-width * 0.15, width * 0.15),
            center_y + random.uniform(-height * 0.15, height * 0.15),
        )
        hold_duration = random.uniform(self.press_hold_duration * 0.9, self.press_hold_duration * 1.2)
        pre_click_pause = random.uniform(0.05, 0.18)
        initial_hold_pause = random.uniform(0.2, 0.4)
        jitter_steps: list[dict[str, float]] = []
        elapsed = initial_hold_pause
        for _ in range(random.randint(1, 3)):
            pause = random.uniform(0.15, 0.35)
            jitter_steps.append(
                {
                    "dx": random.uniform(-3.0, 3.0),
                    "dy": random.uniform(-3.0, 3.0),
                    "pause": pause,
                }
            )
            elapsed += pause
        final_hold_pause = max(0.2, hold_duration - elapsed)
        return {
            "start_offset": start_offset,
            "pre_click_pause": pre_click_pause,
            "initial_hold_pause": initial_hold_pause,
            "jitter": jitter_steps,
            "final_hold_pause": final_hold_pause,
        }

    def _start_virtual_display(self):
        if Display is None:
            raise SystemExit("--virtual-display requested but pyvirtualdisplay is not installed")
        width, height = self.virtual_display_size
        extra_args = ["-ac"]
        self.virtual_display = Display(
            backend="xvfb",
            visible=0,
            size=(width, height),
            use_xauth=False,
            extra_args=extra_args,
        )
        self.virtual_display.start()
        atexit.register(self._stop_virtual_display)
        logging.info(
            "Virtual display started on %s (%sx%s)",
            getattr(self.virtual_display, "new_display_var", "DISPLAY"),
            width,
            height,
        )

    def _stop_virtual_display(self):
        if not self.virtual_display:
            return
        try:
            self.virtual_display.stop()
            logging.info("Virtual display stopped")
        except Exception as exc:
            logging.debug("Failed to stop virtual display cleanly: %s", exc)
        finally:
            self.virtual_display = None

    def run(self) -> list[MethodOutcome]:
        outcomes: list[MethodOutcome] = []
        try:
            for url in self.urls:
                logging.info("=== Testing %s ===", url)
                url_dir = self.run_dir / slugify(url)
                url_dir.mkdir(parents=True, exist_ok=True)
                for method in self.methods:
                    outcome = self._run_method(url, method, url_dir)
                    outcomes.append(outcome)
                    if self.args.sleep > 0:
                        time.sleep(self.args.sleep)
            summary_path = self.run_dir / "summary.json"
            summary_payload = [item.to_summary() for item in outcomes]
            summary_path.write_text(json.dumps(summary_payload, indent=2), encoding="utf-8")
            self._print_table(outcomes)
            logging.info("Summary written to %s", summary_path)
            return outcomes
        finally:
            self.extractor.close_persistent_driver()
            self._stop_virtual_display()

    def _run_method(self, url: str, method: str, url_dir: Path) -> MethodOutcome:
        func = self.method_registry[method]
        logging.info("→ %s", method)
        start = time.time()
        artifact_dir = url_dir / method
        artifact_dir.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {}
        error: str | None = None
        status = "success"
        try:
            payload = func(url, artifact_dir)
        except SkipMethod as skip_exc:
            status = "skipped"
            error = str(skip_exc)
            logging.warning("Skipping %s: %s", method, error)
        except (ProxyChallengeError, RateLimitError) as block_exc:
            status = "blocked"
            error = f"{type(block_exc).__name__}: {block_exc}"
            logging.warning("%s blocked: %s", method, error)
        except Exception as exc:  # pragma: no cover - diagnostic script
            status = "error"
            error = f"{type(exc).__name__}: {exc}"
            logging.exception("%s failed", method)
        elapsed = time.time() - start
        artifact_map: dict[str, str] = {}
        if payload and status == "success":
            artifact_map = self._persist_artifacts(payload, artifact_dir)
        result_snapshot = {
            "status": status,
            "error": error,
            "elapsed_sec": round(elapsed, 3),
            "result": self._trim_payload(payload),
        }
        (artifact_dir / "result.json").write_text(
            json.dumps(result_snapshot, indent=2),
            encoding="utf-8",
        )
        content = payload.get("content") if payload else None
        content_hash = (
            hashlib.sha256(content.encode("utf-8")).hexdigest() if content else None
        )
        outcome = MethodOutcome(
            method=method,
            url=url,
            status=status,
            elapsed_sec=elapsed,
            title=(payload or {}).get("title"),
            publish_date=(payload or {}).get("publish_date"),
            content_chars=len(content) if content else None,
            content_hash=content_hash,
            metadata=(payload or {}).get("metadata", {}),
            error=error,
            artifact_paths=artifact_map,
        )
        return outcome

    def _persist_artifacts(self, payload: dict[str, Any], artifact_dir: Path) -> dict[str, str]:
        paths: dict[str, str] = {}
        raw_html = payload.pop("_raw_html", None)
        screenshot = payload.pop("_screenshot_png", None)
        if raw_html and self.args.save_html:
            html_path = artifact_dir / "response.html"
            html_path.write_text(raw_html, encoding="utf-8", errors="ignore")
            paths["html"] = str(html_path)
        if screenshot and self.args.save_screenshot:
            shot_path = artifact_dir / "screenshot.png"
            shot_path.write_bytes(screenshot)
            paths["screenshot"] = str(shot_path)
        extra_artifacts: list[tuple[str, str, str]] = [
            ("_chrome_version_html", "chrome_version.html", "chrome_version_html"),
            ("_chrome_version_text", "chrome_version.txt", "chrome_version_text"),
            ("_devtools_performance_log", "devtools-performance.json", "devtools_performance_log"),
            ("_devtools_browser_log", "devtools-browser.json", "devtools_browser_log"),
            ("_cdp_version_info", "cdp-browser-version.json", "cdp_browser_version"),
        ]
        for key, filename, label in extra_artifacts:
            blob = payload.pop(key, None)
            if not blob:
                continue
            artifact_path = artifact_dir / filename
            artifact_path.write_text(str(blob), encoding="utf-8", errors="ignore")
            paths[label] = str(artifact_path)
        return paths

    def _trim_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not payload:
            return {}
        trimmed = dict(payload)
        content = trimmed.pop("content", None)
        if content and self.args.content_preview > 0:
            trimmed["content_preview"] = content[: self.args.content_preview]
            trimmed["content_length"] = len(content)
        elif content:
            trimmed["content_length"] = len(content)
        return trimmed

    def _make_headers(self) -> dict[str, str]:
        ua = random.choice(self.extractor.user_agent_pool)
        accept = random.choice(self.extractor.accept_header_pool)
        language = random.choice(self.extractor.accept_language_pool)
        return {
            "User-Agent": ua,
            "Accept": accept,
            "Accept-Language": language,
            "Cache-Control": "max-age=0",
        }

    @staticmethod
    def _press_hold_selectors() -> tuple[str, ...]:
        return (
            ".px-captcha-error-button",
            "button[data-px-btn]",
            "button[data-testid='px-captcha-button']",
            "button[aria-label*='Press']",
        )

    def _wait_for_press_hold_clear_selenium(self, driver) -> bool:
        deadline = time.time() + self.press_hold_wait
        check_script = (
            "return !document.querySelector('.px-captcha-error-button') "
            "&& !document.querySelector('.px-captcha-error-message');"
        )
        while time.time() < deadline:
            try:
                if driver.execute_script(check_script):
                    return True
            except Exception:
                return True
            time.sleep(0.3)
        return False

    def _maybe_solve_press_hold_selenium(self, driver) -> bool:
        if not self.auto_press_hold:
            return False
        try:
            from selenium.webdriver.common.action_chains import ActionChains
            from selenium.webdriver.common.by import By
        except Exception as exc:  # pragma: no cover - optional dependency
            logging.debug("Unable to import selenium helpers for press-hold automation: %s", exc)
            return False
        target = None
        deadline = time.time() + self.press_hold_wait
        selectors = self._press_hold_selectors()
        while time.time() < deadline and target is None:
            for selector in selectors:
                try:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                except Exception:
                    elements = []
                if elements:
                    target = elements[0]
                    break
            if target is None:
                time.sleep(0.25)
        if target is None:
            logging.debug("Press-hold widget not detected; skipping automation")
            return False
        logging.info("Attempting to satisfy press-and-hold challenge")
        actions = ActionChains(driver)
        try:
            rect = getattr(target, "rect", None) or {}
            size = getattr(target, "size", None) or {}
            width = rect.get("width") or size.get("width") or 120.0
            height = rect.get("height") or size.get("height") or 40.0
            plan = self._build_press_hold_plan(width, height)
            start_x, start_y = plan["start_offset"]
            actions.move_to_element_with_offset(target, start_x, start_y)
            actions.pause(plan["pre_click_pause"])
            actions.click_and_hold(target)
            actions.pause(plan["initial_hold_pause"])
            for step in plan["jitter"]:
                actions.move_by_offset(step["dx"], step["dy"])
                actions.pause(step["pause"])
            actions.pause(plan["final_hold_pause"])
            actions.release(target)
            actions.perform()
        except Exception as exc:
            logging.warning("Failed to perform press-and-hold interaction: %s", exc)
            return False
        solved = self._wait_for_press_hold_clear_selenium(driver)
        logging.info(
            "Press-and-hold challenge %s",
            "cleared" if solved else "still present",
        )
        return solved

    async def _maybe_solve_press_hold_playwright(self, page) -> bool:
        if not self.auto_press_hold:
            return False
        selectors = self._press_hold_selectors()

        def to_ms(value: float) -> int:
            return max(0, int(value * 1000))
        for selector in selectors:
            try:
                button = await page.query_selector(selector)
            except Exception:
                button = None
            if not button:
                continue
            box = await button.bounding_box()
            if not box:
                continue
            plan = self._build_press_hold_plan(box.get("width"), box.get("height"))
            start_x = box["x"] + plan["start_offset"][0]
            start_y = box["y"] + plan["start_offset"][1]
            logging.info(
                "Holding mouse on %s for ≈%.1fs with humanized motion",
                selector,
                self.press_hold_duration,
            )
            try:
                await page.mouse.move(start_x, start_y, steps=10)
                await page.wait_for_timeout(to_ms(plan["pre_click_pause"]))
                await page.mouse.down()
                await page.wait_for_timeout(to_ms(plan["initial_hold_pause"]))
                current_x, current_y = start_x, start_y
                for step in plan["jitter"]:
                    current_x += step["dx"]
                    current_y += step["dy"]
                    await page.mouse.move(current_x, current_y, steps=4)
                    await page.wait_for_timeout(to_ms(step["pause"]))
                await page.wait_for_timeout(to_ms(plan["final_hold_pause"]))
                await page.mouse.up()
                await page.wait_for_function(
                    "() => !document.querySelector('.px-captcha-error-button') "
                    "&& !document.querySelector('.px-captcha-error-message')",
                    timeout=int(self.press_hold_wait * 1000),
                )
                logging.info("Press-and-hold challenge cleared")
                return True
            except Exception as exc:
                logging.debug("Press-and-hold attempt via %s failed: %s", selector, exc)
        logging.debug("All press-and-hold selectors exhausted with no success")
        return False

    def _method_requests(self, url: str, _: Path) -> dict[str, Any]:
        headers = self._make_headers()
        resp = requests.get(
            url,
            headers=headers,
            proxies=self.proxy_dict,
            timeout=self.args.timeout,
            verify=not self.args.insecure,
        )
        resp.raise_for_status()
        article = self.extractor.extract_article_data(resp.text, url)
        article.setdefault("metadata", {})
        article["metadata"].update(
            {
                "extraction_method": "requests",
                "http_status": resp.status_code,
                "headers": dict(resp.headers),
            }
        )
        article["_raw_html"] = resp.text
        return article

    def _method_cloudscraper(self, url: str, _: Path) -> dict[str, Any]:
        if cloudscraper is None:
            raise SkipMethod("cloudscraper not installed")
        scraper = cloudscraper.create_scraper(
            delay=10,
            browser={"browser": "chrome", "platform": "windows", "mobile": False},
        )
        resp = scraper.get(
            url,
            headers=self._make_headers(),
            proxies=self.proxy_dict,
            timeout=self.args.timeout,
        )
        resp.raise_for_status()
        article = self.extractor.extract_article_data(resp.text, url)
        article.setdefault("metadata", {})
        article["metadata"].update(
            {
                "extraction_method": "cloudscraper",
                "http_status": resp.status_code,
                "headers": dict(resp.headers),
            }
        )
        article["_raw_html"] = resp.text
        return article

    def _method_mcmetadata(self, url: str, _: Path) -> dict[str, Any]:
        try:
            return self.extractor._extract_with_mcmetadata(url)
        except RuntimeError as exc:
            raise SkipMethod(str(exc))

    def _method_newspaper(self, url: str, _: Path) -> dict[str, Any]:
        return self.extractor._extract_with_newspaper(url)

    def _method_beautifulsoup(self, url: str, _: Path) -> dict[str, Any]:
        return self.extractor._extract_with_beautifulsoup(url)

    def _method_unblock(self, url: str, _: Path) -> dict[str, Any]:
        return self.extractor._extract_with_unblock_proxy(url, browser_actions=None, metrics=None)

    def _method_selenium_stealth(self, url: str, _: Path) -> dict[str, Any]:
        result = self.extractor._extract_with_selenium(url)
        driver = None
        try:
            driver = self.extractor.get_persistent_driver()
        except Exception:
            driver = None
        if driver is not None:
            try:
                result["_raw_html"] = driver.page_source
            except Exception:
                pass
            try:
                result["_screenshot_png"] = driver.get_screenshot_as_png()
            except Exception:
                pass
        return result

    def _method_selenium_basic(self, url: str, _: Path) -> dict[str, Any]:
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
        except Exception as exc:  # pragma: no cover - optional dependency
            raise SkipMethod(f"selenium not available: {exc}")

        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument(f"--window-size={self.window_width},{self.window_height}")
        options.add_argument("--disable-blink-features=AutomationControlled")
        if self.args.selenium_proxy:
            options.add_argument(f"--proxy-server={self.args.selenium_proxy}")
        if self.selenium_user_agent:
            options.add_argument(f"--user-agent={self.selenium_user_agent}")

        driver = webdriver.Chrome(options=options)
        driver.set_page_load_timeout(self.args.selenium_timeout)
        self._install_fingerprint_script_selenium(driver)
        self._apply_user_agent_override(driver)
        try:
            driver.get(url)
            time.sleep(self.args.selenium_wait)
            html = driver.page_source
            article = self.extractor.extract_article_data(html, url)
            article.setdefault("metadata", {})
            article["metadata"].update(
                {
                    "extraction_method": "selenium-basic",
                    "page_source_length": len(html),
                }
            )
            article["_raw_html"] = html
            try:
                article["_screenshot_png"] = driver.get_screenshot_as_png()
            except Exception:
                pass
            return article
        finally:
            driver.quit()

    def _method_selenium_profile(self, url: str, _: Path) -> dict[str, Any]:
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
        except Exception as exc:  # pragma: no cover - optional dependency
            raise SkipMethod(f"selenium not available: {exc}")

        if not self.selenium_user_data_dir:
            raise SkipMethod("selenium-profile requires --selenium-user-data-dir pointing to a Chrome profile")

        options = Options()
        if not self.args.selenium_headful:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument(f"--window-size={self.window_width},{self.window_height}")
        options.add_argument(f"--user-data-dir={self.selenium_user_data_dir}")
        if self.selenium_profile_directory:
            options.add_argument(f"--profile-directory={self.selenium_profile_directory}")
        if self.args.selenium_proxy:
            options.add_argument(f"--proxy-server={self.args.selenium_proxy}")
        if self.selenium_user_agent:
            options.add_argument(f"--user-agent={self.selenium_user_agent}")
        options.set_capability("goog:loggingPrefs", {"performance": "ALL", "browser": "ALL"})

        driver = webdriver.Chrome(options=options)
        driver.set_page_load_timeout(self.args.selenium_timeout)
        self._install_fingerprint_script_selenium(driver)
        self._apply_user_agent_override(driver)
        cdp_version: dict[str, Any] | None = None
        chrome_version_html: str | None = None
        chrome_version_text: str | None = None
        original_window = driver.current_window_handle
        try:
            cdp_version = driver.execute_cdp_cmd("Browser.getVersion", {})
        except Exception as exc:  # pragma: no cover - diagnostic aid
            logging.debug("Unable to fetch Browser.getVersion: %s", exc)
        try:
            driver.switch_to.new_window("tab")
            driver.get("chrome://version/")
            time.sleep(1)
            chrome_version_html = driver.page_source
            chrome_version_text = driver.execute_script("return document.body && document.body.innerText;")
            driver.close()
            driver.switch_to.window(original_window)
        except Exception as exc:  # pragma: no cover - diagnostic aid
            chrome_version_text = f"ERROR capturing chrome://version: {exc}"
            try:
                driver.switch_to.window(original_window)
            except Exception:
                pass

        press_hold_cleared = False
        try:
            driver.get(url)
            time.sleep(self.args.selenium_wait)
            if self.auto_press_hold:
                press_hold_cleared = self._maybe_solve_press_hold_selenium(driver)
                if press_hold_cleared:
                    time.sleep(1.0)
            html = driver.page_source
            performance_log: list[Any] | None = None
            browser_log: list[Any] | None = None
            try:
                performance_log = driver.get_log("performance")
            except Exception as exc:
                logging.debug("Unable to fetch performance log: %s", exc)
            try:
                browser_log = driver.get_log("browser")
            except Exception as exc:
                logging.debug("Unable to fetch browser log: %s", exc)
            article = self.extractor.extract_article_data(html, url)
            article.setdefault("metadata", {})
            article["metadata"].update(
                {
                    "extraction_method": "selenium-profile",
                    "page_source_length": len(html),
                    "profile_directory": self.selenium_profile_directory,
                    "user_data_dir": str(self.selenium_user_data_dir),
                    "browser_version_info": cdp_version,
                    "press_hold_attempted": self.auto_press_hold,
                    "press_hold_cleared": press_hold_cleared,
                }
            )
            article["_raw_html"] = html
            if chrome_version_html:
                article["_chrome_version_html"] = chrome_version_html
            if chrome_version_text:
                article["_chrome_version_text"] = chrome_version_text
            if cdp_version:
                article["_cdp_version_info"] = json.dumps(cdp_version, indent=2)
            if performance_log is not None:
                article["_devtools_performance_log"] = json.dumps(performance_log, indent=2)
            if browser_log is not None:
                article["_devtools_browser_log"] = json.dumps(browser_log, indent=2)
            try:
                article["_screenshot_png"] = driver.get_screenshot_as_png()
            except Exception:
                pass
            return article
        finally:
            driver.quit()

    def _method_playwright(self, url: str, _: Path) -> dict[str, Any]:
        if async_playwright is None:
            raise SkipMethod("playwright not installed")

        async def capture() -> tuple[str, bytes]:
            async with async_playwright() as p:
                launch_kwargs: dict[str, Any] = {
                    "headless": not self.args.playwright_headful,
                    "args": ["--no-sandbox", "--disable-dev-shm-usage"],
                }
                if self.playwright_executable_path:
                    launch_kwargs["executable_path"] = str(self.playwright_executable_path)
                browser = await p.chromium.launch(**launch_kwargs)
                context_kwargs = self._playwright_context_kwargs()
                context = await browser.new_context(**context_kwargs)
                if self.fingerprint_script:
                    await context.add_init_script(self.fingerprint_script)
                page = await context.new_page()
                await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=int(self.args.playwright_timeout * 1000),
                )
                await page.wait_for_timeout(int(self.args.playwright_wait * 1000))
                html = await page.content()
                screenshot = await page.screenshot(full_page=True)
                await browser.close()
                return html, screenshot

        html, screenshot = asyncio.run(capture())
        article = self.extractor.extract_article_data(html, url)
        article.setdefault("metadata", {})
        article["metadata"].update(
            {
                "extraction_method": "playwright",
                "page_source_length": len(html),
            }
        )
        article["_raw_html"] = html
        article["_screenshot_png"] = screenshot
        return article

    def _method_playwright_persistent(self, url: str, _: Path) -> dict[str, Any]:
        if async_playwright is None:
            raise SkipMethod("playwright not installed")
        if not self.playwright_user_data_dir:
            raise SkipMethod("playwright-persistent requires --playwright-user-data-dir")

        async def capture() -> tuple[str, bytes, dict[str, Any] | None, bool]:
            async with async_playwright() as p:
                extra_args = ["--no-sandbox", "--disable-dev-shm-usage"]
                if self.playwright_extra_args:
                    extra_args.extend(self.playwright_extra_args)
                if self.selenium_user_agent:
                    extra_args.append(f"--user-agent={self.selenium_user_agent}")
                launch_kwargs: dict[str, Any] = {
                    "user_data_dir": str(self.playwright_user_data_dir),
                    "headless": not self.args.playwright_headful,
                    "proxy": self.playwright_proxy or None,
                    "viewport": {"width": self.window_width, "height": self.window_height},
                    "args": extra_args,
                }
                if self.fingerprint_language:
                    launch_kwargs["locale"] = self.fingerprint_language
                if self.playwright_executable_path:
                    launch_kwargs["executable_path"] = str(self.playwright_executable_path)
                elif self.playwright_channel:
                    launch_kwargs["channel"] = self.playwright_channel
                context = await p.chromium.launch_persistent_context(**launch_kwargs)
                if self.fingerprint_script:
                    await context.add_init_script(self.fingerprint_script)
                if self.fingerprint_language:
                    await context.set_extra_http_headers({"Accept-Language": self.fingerprint_language})
                page = context.pages[0] if context.pages else await context.new_page()
                await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=int(self.args.playwright_timeout * 1000),
                )
                await page.wait_for_timeout(int(self.args.playwright_wait * 1000))
                stealth_report = None
                press_hold_cleared = False
                try:
                    stealth_report = await page.evaluate(
                        "() => ({"
                        "webdriver: navigator.webdriver,"
                        "platform: navigator.platform,"
                        "languages: navigator.languages,"
                        "plugins_length: navigator.plugins ? navigator.plugins.length : null,"
                        "mimeTypes_length: navigator.mimeTypes ? navigator.mimeTypes.length : null,"
                        "maxTouchPoints: navigator.maxTouchPoints,"
                        "hardwareConcurrency: navigator.hardwareConcurrency,"
                        "userAgent: navigator.userAgent"
                        "})"
                    )
                except Exception as exc:
                    logging.debug("Unable to collect navigator snapshot: %s", exc)
                if self.auto_press_hold:
                    press_hold_cleared = await self._maybe_solve_press_hold_playwright(page)
                    if press_hold_cleared:
                        await page.wait_for_timeout(500)
                html = await page.content()
                screenshot = await page.screenshot(full_page=True)
                await context.close()
                return html, screenshot, stealth_report, press_hold_cleared

        html, screenshot, stealth_report, press_hold_cleared = asyncio.run(capture())
        article = self.extractor.extract_article_data(html, url)
        article.setdefault("metadata", {})
        article["metadata"].update(
            {
                "extraction_method": "playwright-persistent",
                "page_source_length": len(html),
                "user_data_dir": str(self.playwright_user_data_dir),
                "channel": self.playwright_channel or "chromium",
                "playwright_extra_args": self.playwright_extra_args,
                "executable_path": str(self.playwright_executable_path)
                if self.playwright_executable_path
                else None,
                "press_hold_attempted": self.auto_press_hold,
                "press_hold_cleared": press_hold_cleared,
                "navigator_snapshot": stealth_report,
            }
        )
        article["_raw_html"] = html
        article["_screenshot_png"] = screenshot
        return article

    def _print_table(self, outcomes: Iterable[MethodOutcome]):
        header = f"{ 'Method':<18}{'Status':<10}{'Elapsed(s)':<12}{'Title'}"
        logging.info(header)
        for outcome in outcomes:
            title = (outcome.title or "").strip()
            shortened = (title[:70] + "…") if len(title) > 70 else title
            logging.info(
                f"{outcome.method:<18}{outcome.status:<10}"
                f"{outcome.elapsed_sec:<12.2f}{shortened}"
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run side-by-side capture tests across extraction methods",
    )
    parser.add_argument("--url", dest="urls", action="append", help="URL to test")
    parser.add_argument("--urls-file", help="Path to newline-delimited URL list")
    parser.add_argument("--methods", default=DEFAULT_METHODS, help="Comma list or 'all'")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory to store artifacts (timestamped subdir added)",
    )
    parser.add_argument(
        "--proxy",
        default=os.getenv("CAPTURE_METHOD_PROXY"),
        help="Proxy URL (http://user:pass@host:port)",
    )
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout seconds")
    parser.add_argument("--sleep", type=float, default=1.5, help="Seconds between method calls")
    parser.add_argument(
        "--virtual-display",
        action="store_true",
        help="Start a virtual X display (pyvirtualdisplay + Xvfb) for headful browser runs",
    )
    parser.add_argument(
        "--virtual-display-size",
        default="1440x900",
        help="Virtual display geometry (e.g. 1440x900)",
    )
    parser.add_argument(
        "--virtual-display-binary",
        type=Path,
        help="Path to the Xvfb binary (defaults to $CAPTURE_XVFB_BINARY or system Xvfb)",
    )
    parser.add_argument(
        "--virtual-display-libdir",
        type=str,
        help="Optional directory or PATH-style list of directories for Xvfb dependencies",
    )
    parser.add_argument(
        "--content-preview",
        type=int,
        default=1500,
        help="Chars of article text to keep in per-method result",
    )
    parser.add_argument(
        "--save-html",
        dest="save_html",
        action="store_true",
        default=True,
        help="Persist HTML artifacts",
    )
    parser.add_argument(
        "--no-save-html",
        dest="save_html",
        action="store_false",
        help="Disable HTML artifact saving",
    )
    parser.add_argument(
        "--save-screenshot",
        dest="save_screenshot",
        action="store_true",
        default=True,
        help="Persist screenshots for browsered methods",
    )
    parser.add_argument(
        "--no-save-screenshot",
        dest="save_screenshot",
        action="store_false",
        help="Disable screenshot capture",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Skip TLS verification for raw HTTP methods",
    )
    parser.add_argument(
        "--selenium-proxy",
        dest="selenium_proxy",
        default=None,
        help="Override proxy for selenium-basic (defaults to --proxy)",
    )
    parser.add_argument(
        "--selenium-headful",
        action="store_true",
        help="Run selenium-profile in headful mode",
    )
    parser.add_argument(
        "--selenium-user-data-dir",
        type=Path,
        help="Path to Chrome user data dir to reuse (copy of local profile recommended)",
    )
    parser.add_argument(
        "--selenium-profile-directory",
        default="Default",
        help="Profile directory name inside the user data dir (Default, Profile 1, etc.)",
    )
    parser.add_argument(
        "--selenium-user-agent",
        help="User-Agent string to force for selenium-profile method",
    )
    parser.add_argument(
        "--selenium-client-hints",
        help="JSON blob merged into Network.setUserAgentOverride (e.g. {\"platform\":\"Windows\"})",
    )
    parser.add_argument(
        "--fingerprint-file",
        type=Path,
        help="JSON fingerprint profile applied to browser-based methods",
    )
    parser.add_argument(
        "--selenium-timeout",
        type=int,
        default=20,
        help="Page load timeout for selenium-basic",
    )
    parser.add_argument(
        "--selenium-wait",
        type=float,
        default=2.5,
        help="Post-navigation sleep seconds for selenium-basic",
    )
    parser.add_argument(
        "--playwright-timeout",
        type=float,
        default=20.0,
        help="Navigation timeout (seconds)",
    )
    parser.add_argument(
        "--playwright-wait",
        type=float,
        default=1.0,
        help="Extra wait after DOMContentLoaded (seconds)",
    )
    parser.add_argument(
        "--playwright-headful",
        action="store_true",
        help="Run Playwright with a visible browser window",
    )
    parser.add_argument(
        "--playwright-user-data-dir",
        type=Path,
        help="Persistent profile directory for playwright-persistent (will be mutated)",
    )
    parser.add_argument(
        "--playwright-channel",
        default=None,
        help="Browser channel for Playwright (chrome, msedge, etc.)",
    )
    parser.add_argument(
        "--playwright-executable-path",
        type=Path,
        help="Full path to a Chrome/Chromium binary for Playwright (incompatible with --playwright-channel)",
    )
    parser.add_argument(
        "--playwright-extra-args",
        default=None,
        help="Additional Chromium args for persistent sessions (pass as a single quoted string)",
    )
    parser.add_argument(
        "--auto-press-hold",
        action="store_true",
        help="Attempt to automatically solve PerimeterX press-and-hold challenges",
    )
    parser.add_argument(
        "--press-hold-duration",
        type=float,
        default=5.0,
        help="Seconds to hold the challenge button when auto-solving",
    )
    parser.add_argument(
        "--press-hold-wait",
        type=float,
        default=10.0,
        help="Seconds to wait for the challenge overlay to disappear after holding",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (DEBUG, INFO, etc.)",
    )
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    if not args.selenium_proxy:
        args.selenium_proxy = args.proxy
    configure_logging(args.log_level)
    probe = CaptureProbe(args)
    probe.run()


if __name__ == "__main__":
    main()
