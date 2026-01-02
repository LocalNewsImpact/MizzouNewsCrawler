"""Helpers for loading and applying Chrome fingerprint profiles."""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)

DEFAULT_FINGERPRINT_PATH = Path("/app/fingerprints/macos-default.json")
_WARNED_PATHS: set[Path] = set()


@dataclass(frozen=True)
class FingerprintProfile:
    """Parsed fingerprint profile metadata."""

    source_path: Path
    raw: dict[str, Any]
    user_agent: str | None
    client_hints: dict[str, Any] | None
    accept_language: str | None
    languages: list[str]
    screen_size: tuple[int, int] | None
    script: str | None


def load_fingerprint_profile(
    path: str | Path | None = None,
) -> FingerprintProfile | None:
    """Load fingerprint profile JSON from disk.

    Returns None when the file is missing or invalid so callers can fall back to
    randomized fingerprints without crashing the extractor.
    """

    candidate = (
        path or os.getenv("SELENIUM_FINGERPRINT_PATH") or DEFAULT_FINGERPRINT_PATH
    )
    candidate_path = Path(candidate).expanduser()
    if not candidate_path.exists():
        if candidate_path not in _WARNED_PATHS:
            logger.info(
                "Fingerprint profile %s not found; Selenium will use randomized fingerprints",
                candidate_path,
            )
            _WARNED_PATHS.add(candidate_path)
        return None

    try:
        raw = json.loads(candidate_path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - extremely unlikely but guarded
        logger.warning("Unable to load fingerprint profile %s: %s", candidate_path, exc)
        return None

    if not isinstance(raw, dict):
        logger.warning(
            "Fingerprint profile %s must contain a JSON object", candidate_path
        )
        return None

    navigator = raw.get("navigator") or {}
    raw_languages = list(navigator.get("languages") or [])
    if not raw_languages and navigator.get("language"):
        raw_languages = [navigator["language"]]

    accept_language = _build_accept_language_header(
        raw_languages, navigator.get("language")
    )
    screen_size = _extract_screen_size(raw.get("screen") or {})
    script = _build_fingerprint_script(raw)
    client_hints = _build_client_hints(raw)

    profile = FingerprintProfile(
        source_path=candidate_path,
        raw=raw,
        user_agent=raw.get("userAgent"),
        client_hints=client_hints,
        accept_language=accept_language,
        languages=raw_languages,
        screen_size=screen_size,
        script=script,
    )
    logger.info("Loaded fingerprint profile from %s", candidate_path)
    return profile


def prepare_user_data_dir(
    source: str | Path | None,
    *,
    readonly: bool = False,
    workdir: Path | None = None,
) -> Path | None:
    """Return a writable Chrome user-data directory based on source settings.

    If source is None, returns None. When source exists and is writable, returns
    the original path unless ``readonly`` forces the code to treat it as a
    template. Read-only paths (common for Kubernetes secrets) are copied into a
    scratch directory so Chrome can mutate profile files safely.
    """

    if not source:
        return None

    src_path = Path(source).expanduser()
    if not src_path.exists():
        raise FileNotFoundError(f"Chrome profile directory {src_path} does not exist")

    writable = _is_directory_writable(src_path)
    treat_as_readonly = readonly or not writable
    if not treat_as_readonly:
        logger.info("Using writable Chrome profile at %s", src_path)
        return src_path

    logger.info("Chrome profile %s is read-only; copying to scratch", src_path)

    scratch_root = workdir or Path("/tmp/chrome-profile")
    scratch_root.mkdir(parents=True, exist_ok=True)
    destination = scratch_root / "profile"
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(src_path, destination)
    logger.info("Copied read-only Chrome profile %s to %s", src_path, destination)
    return destination


def _extract_screen_size(screen: dict[str, Any]) -> tuple[int, int] | None:
    width_raw = screen.get("width")
    height_raw = screen.get("height")
    if width_raw is None or height_raw is None:
        return None
    try:
        width = int(width_raw)
        height = int(height_raw)
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return width, height


def _build_client_hints(raw: dict[str, Any]) -> dict[str, Any] | None:
    ua_data = raw.get("uaData") if isinstance(raw.get("uaData"), dict) else None
    navigator = raw.get("navigator") or {}

    payload: dict[str, Any] = {}
    if ua_data:
        payload["userAgentMetadata"] = ua_data
    platform = None
    if ua_data:
        platform = ua_data.get("platform")
    platform = platform or navigator.get("platform")
    if platform:
        payload["platform"] = platform
    language = navigator.get("language")
    if language:
        payload["acceptLanguage"] = language
    return payload or None


def _build_accept_language_header(
    languages: Iterable[str], fallback: str | None
) -> str | None:
    langs = [lang for lang in languages if lang]
    if not langs and fallback:
        langs = [fallback]
    if not langs:
        return None
    primary, *rest = langs
    parts = [primary]
    q = 0.9
    for lang in rest:
        parts.append(f"{lang};q={q:.1f}")
        q = max(q - 0.1, 0.1)
    return ",".join(parts)


def _build_fingerprint_script(profile: dict[str, Any]) -> str | None:
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

    def add_nav(prop: str) -> None:
        if prop in navigator and navigator[prop] is not None:
            lines.append(
                f"  define(navigator, '{prop}', {json.dumps(navigator[prop])});"
            )

    for key in (
        "userAgent",
        "platform",
        "hardwareConcurrency",
        "maxTouchPoints",
        "language",
        "languages",
        "deviceMemory",
    ):
        add_nav(key)

    if screen:
        lines.append("  const screenObj = window.screen || {};")
        for key in (
            "width",
            "height",
            "availWidth",
            "availHeight",
            "colorDepth",
            "pixelDepth",
        ):
            if key in screen and screen[key] is not None:
                lines.append(
                    f"  define(screenObj, '{key}', {json.dumps(screen[key])});"
                )

    vendor = webgl.get("webglVendor") if isinstance(webgl, dict) else None
    renderer = webgl.get("webglRenderer") if isinstance(webgl, dict) else None
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


def _is_directory_writable(path: Path) -> bool:
    """Positively confirm writability by attempting a temporary file write."""

    target = path if path.is_dir() else path.parent

    try:
        fd, probe_path = tempfile.mkstemp(prefix=".chrome-profile-probe-", dir=target)
    except OSError:
        return False

    os.close(fd)
    try:
        os.unlink(probe_path)
    except OSError:  # pragma: no cover - best effort cleanup
        logger.debug("Failed to cleanup writability probe %s", probe_path)
    return True
