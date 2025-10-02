"""Utility routines for cleaning extracted article text."""

from __future__ import annotations

import re
from collections.abc import Iterable

_ROT47_MARKERS = set("@?:;[]=^$\\|")
_TOKEN_RE = re.compile(r"\S+")


def _rot47(value: str) -> str:
    # ROT47 operates on printable ASCII (33-126); leave other chars untouched.
    out_chars: list[str] = []
    for ch in value:
        code = ord(ch)
        if 33 <= code <= 126:
            out_chars.append(chr(33 + ((code - 33 + 47) % 94)))
        else:
            out_chars.append(ch)
    return "".join(out_chars)


def _looks_like_rot47_token(token: str) -> bool:
    if len(token) < 4:
        return False
    if not any(ch in _ROT47_MARKERS for ch in token):
        return False
    letters = sum(1 for ch in token if ch.isalpha())
    non_letters = len(token) - letters
    if letters == 0:
        return False
    if letters / len(token) > 0.6:
        return False
    if non_letters / len(token) < 0.35:
        return False
    return True


def _iter_rot47_ranges(text: str) -> Iterable[tuple[int, int]]:
    matches = list(_TOKEN_RE.finditer(text))
    current_start: int | None = None
    current_end: int | None = None
    for idx, match in enumerate(matches):
        token = match.group(0)
        if _looks_like_rot47_token(token):
            if current_start is None:
                current_start = idx
            current_end = idx
        else:
            if current_start is not None and current_end is not None:
                if current_end - current_start + 1 >= 6:
                    yield (
                        matches[current_start].start(),
                        matches[current_end].end(),
                    )
                current_start = None
                current_end = None
    if current_start is not None and current_end is not None:
        if current_end - current_start + 1 >= 6:
            yield (
                matches[current_start].start(),
                matches[current_end].end(),
            )


def _decode_segment(segment: str) -> str | None:
    decoded = _rot47(segment)
    letters = sum(1 for ch in decoded if ch.isalpha())
    if not decoded.strip():
        return None
    if letters / len(decoded) < 0.4:
        return None
    cleaned = re.sub(r"</?p>", " ", decoded)
    return cleaned


def decode_rot47_segments(text: str | None) -> str | None:
    """Return *text* with ROT47-obfuscated sections decoded when detected."""

    if not text:
        return text
    if "kAm" not in text and "k^Am" not in text:
        # Quick short-circuit for the common unaffected case.
        return text

    replacements: list[tuple[int, int, str]] = []
    for start, end in _iter_rot47_ranges(text):
        replacement = _decode_segment(text[start:end])
        if replacement is not None:
            replacements.append((start, end, replacement))

    if not replacements:
        return text

    parts: list[str] = []
    last_index = 0
    for start, end, replacement in replacements:
        parts.append(text[last_index:start])
        parts.append(replacement)
        last_index = end
    parts.append(text[last_index:])

    result = "".join(parts)
    # Collapse any excessive whitespace introduced by replacements.
    result = re.sub(r"\s+", " ", result)
    return result.strip() or text
