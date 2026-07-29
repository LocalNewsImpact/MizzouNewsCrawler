"""Utility routines for cleaning extracted article text."""

from __future__ import annotations

import html
import re
from collections.abc import Iterable

_ROT47_MARKERS = set("@?:;[]=^$\\|")
_TOKEN_RE = re.compile(r"\S+")

# Markup revealed by decoding. The encoding hides real tags, so the decoded
# text carries them back: <p class="p1">, <hr />, and friends. A literal
# </?p> misses every attributed form and leaves it in the article body.
_DECODED_TAG_RE = re.compile(r"</?(?:p|hr|br|em|strong|span)\b[^>]*>", re.I)

# Lee Enterprises ROT47 paragraph markers
# kAm = <p>, k^Am = </p>, k9C ^m = <hr >
#
# The opening tag frequently carries attributes, which encode into the run
# between `kA` and the closing `m`:
#
#     kA 4=2DDlQAcQm   ->   <p class="p4">
#
# Requiring a bare `kAm` therefore matched nothing on those articles. In the
# March researcher file the attribute form is the DOMINANT one — affected rows
# carry 24-27 `k^Am` closers and zero bare `kAm` openers, so the decoder passed
# straight over them. `[^m]` is safe as the attribute body because `m` is the
# encoding of `>`, which cannot appear unescaped inside a tag.
_ROT47_PARAGRAPH_PATTERN = re.compile(
    r"kA[^m]{0,120}m.*?k\^Am",
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


# Damage left by decoding ROT47 without unescaping first. `U=Ej` sits where a
# `k` belongs and `U8Ej` where an `m` belongs, so "asked" was stored as
# "asU=Ejed" and "community" as "coU8EjU8Ejunity". Neither sequence occurs in
# English, which makes the repair unambiguous and safe to apply to any input.
_ENTITY_ARTIFACTS = (("U=Ej", "k"), ("U8Ej", "m"))


def repair_entity_artifacts(text: str) -> str:
    """Undo the ``U=Ej`` / ``U8Ej`` corruption in already-stored text.

    Rows written before the unescape fix carry this damage baked in: they hold
    no ROT47 markers and no escaped entities, just prose with every ``k`` and
    ``m`` replaced. Decoding cannot help them — the ciphertext is gone — but the
    substitution is reversible on its own.
    """

    if not text:
        return text
    for artifact, letter in _ENTITY_ARTIFACTS:
        if artifact in text:
            text = text.replace(artifact, letter)
    return text


def _decode_rot47_text(segment: str) -> str:
    """ROT47-decode *segment*, unescaping HTML entities FIRST.

    ROT47 maps ``k`` -> ``<`` and ``m`` -> ``>``. Any ``k`` or ``m`` in the
    original prose therefore arrives inside the ciphertext as a literal ``<`` or
    ``>``, which the page must escape as ``&lt;`` / ``&gt;`` to avoid breaking
    its own markup. Decoding those entities character-by-character produces
    ``U=Ej`` and ``U8Ej`` exactly where the letter belongs:

        ciphertext on the page   '2D&lt;65'
        decoded without unescape 'asU=Ejed'
        decoded with unescape    'asked'

    Every ``k`` and every ``m`` in the recovered text was corrupted this way, so
    the output read as ciphertext to anything checking for it — which is why
    29% of affected articles still looked encoded after decoding.
    """

    return _rot47(html.unescape(segment))


def _decode_segment(segment: str) -> str | None:
    decoded = _decode_rot47_text(segment)
    letters = sum(1 for ch in decoded if ch.isalpha())
    if not decoded.strip():
        return None
    if letters / len(decoded) < 0.4:
        return None
    cleaned = _DECODED_TAG_RE.sub(" ", decoded)
    return cleaned


def _marker_density(s: str) -> float:
    """Share of *s* that is a ROT47-marker punctuation character.

    ROT47 shifts common English letters into this exact punctuation set, so
    genuine ciphertext is saturated with it and genuine English essentially
    never is. Comparing this before and after decoding is what tells a real
    decode apart from a paragraph that merely didn't need one — see the
    validation note below.
    """
    return sum(1 for ch in s if ch in _ROT47_MARKERS) / len(s) if s else 0.0


def _decode_rot47_by_markers(text: str) -> str | None:
    """Decode ROT47 text using paragraph markers (kAm/k^Am).

    Lee Enterprises encodes article text with ROT47, using markers:
    - kAm = <p> (paragraph open)
    - k^Am = </p> (paragraph close)
    - k9C ^m = <hr > (horizontal rule)

    This is more reliable than token-based detection since short words
    like "of", "33," don't break the pattern matching.

    The guard admits `k^Am` on its own. Articles whose paragraphs all open with
    attributes carry no bare `kAm` anywhere, so guarding on it alone returned
    None before the pattern ever ran — the regex finds 24 paragraphs in such an
    article and decodes the first cleanly, but the function never reached it.
    """
    if "kAm" not in text and "k^Am" not in text:
        return None

    # Find all ROT47 paragraph segments
    matches = list(_ROT47_PARAGRAPH_PATTERN.finditer(text))
    if not matches:
        return None

    # Decode each match and validate
    replacements: list[tuple[int, int, str]] = []
    for match in matches:
        segment = match.group(0)
        decoded = _decode_rot47_text(segment)

        # Validation is RELATIVE, not absolute: accept a decode when it
        # measurably reduced ROT47-marker saturation relative to its own
        # ciphertext, rather than requiring the decoded text alone to clear a
        # fixed "looks like prose" bar.
        #
        # An absolute floor on decoded letter-ratio (this used to require
        # >= 0.3) rejects a genuinely correct decode whenever the recovered
        # text is naturally letter-sparse -- a box score is the case that
        # exposed it: "NC - 0 - 14 - 0 - 10 = 24" decodes perfectly and scores
        # 0.23, so the ciphertext was left in place mid-article while every
        # surrounding prose paragraph decoded fine. Its RAW ciphertext scores
        # even fewer letters by coincidence (ROT47 shifts digits and
        # punctuation too), which is exactly why an absolute floor on the
        # OUTPUT is the wrong measure and a relative one is not.
        #
        # Verified against every one of the 44 kAm/k^Am paragraphs in the
        # production row that surfaced this (2026-07-28): marker density drops
        # after decoding in all 44, including the 2 the old floor rejected.
        if _marker_density(decoded) < _marker_density(segment):
            # Clean up HTML tags
            cleaned = _DECODED_TAG_RE.sub(" ", decoded)
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

    # Repair first: rows decoded before the unescape fix carry the damage with
    # no markers left to key off, so this is the only pass that can reach them.
    text = repair_entity_artifacts(text)

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
