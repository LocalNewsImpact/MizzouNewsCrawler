"""Utility routines for cleaning extracted article text."""

from __future__ import annotations

import re
from collections.abc import Iterable

_ROT47_MARKERS = set("@?:;[]=^$\\|")
_TOKEN_RE = re.compile(r"\S+")

# Lee Enterprises ROT47 paragraph markers
# kAm = <p>, k^Am = </p>, k9C ^m = <hr >
_ROT47_PARAGRAPH_PATTERN = re.compile(
    r"kAm.*?k\^Am",
    re.DOTALL,
)


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


def _decode_rot47_by_markers(text: str) -> str | None:
    """Decode ROT47 text using paragraph markers (kAm/k^Am).
    
    Lee Enterprises encodes article text with ROT47, using markers:
    - kAm = <p> (paragraph open)
    - k^Am = </p> (paragraph close)
    - k9C ^m = <hr > (horizontal rule)
    
    This is more reliable than token-based detection since short words
    like "of", "33," don't break the pattern matching.
    """
    if "kAm" not in text:
        return None
    
    # Find all ROT47 paragraph segments
    matches = list(_ROT47_PARAGRAPH_PATTERN.finditer(text))
    if not matches:
        return None
    
    # Decode each match and validate
    replacements: list[tuple[int, int, str]] = []
    for match in matches:
        segment = match.group(0)
        decoded = _rot47(segment)
        
        # Basic validation: decoded should have reasonable letter ratio
        letters = sum(1 for ch in decoded if ch.isalpha())
        if len(decoded) > 0 and letters / len(decoded) >= 0.3:
            # Clean up HTML tags
            cleaned = re.sub(r"</?p>", " ", decoded)
            cleaned = re.sub(r"<hr\s*/?>", " ", cleaned)
            replacements.append((match.start(), match.end(), cleaned))
    
    if not replacements:
        return None
    
    # Build result with replacements
    parts: list[str] = []
    last_index = 0
    for start, end, replacement in replacements:
        parts.append(text[last_index:start])
        parts.append(replacement)
        last_index = end
    parts.append(text[last_index:])
    
    result = "".join(parts)
    # Also handle standalone markers like k9C ^m (<hr >)
    result = re.sub(r"k9C\s*\^m", " ", result)
    result = re.sub(r"\s+", " ", result)
    return result.strip()


def decode_rot47_segments(text: str | None) -> str | None:
    """Return *text* with ROT47-obfuscated sections decoded when detected."""

    if not text:
        return text
    if "kAm" not in text and "k^Am" not in text:
        # Quick short-circuit for the common unaffected case.
        return text

    # Try marker-based decoding first (more reliable for Lee Enterprises content)
    marker_result = _decode_rot47_by_markers(text)
    if marker_result:
        return marker_result

    # Fall back to token-based detection for edge cases
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
