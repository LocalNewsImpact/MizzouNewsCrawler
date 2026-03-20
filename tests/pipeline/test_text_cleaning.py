from src.pipeline.text_cleaning import (
    _decode_segment,
    _looks_like_rot47_token,
    _rot47,
    decode_rot47_segments,
)


def test_decode_rot47_segments_returns_original_without_markers():
    text = "Plain article content without obfuscation."
    assert decode_rot47_segments(text) == text


def test_decode_rot47_segments_decodes_long_rot47_run():
    tokens = [
        "mixing1",
        "mixing2",
        "mixing3",
        "mixing4",
        "mixing5",
        "mixing6",
        "mixing7",
    ]
    encoded = _rot47("<p>" + " ".join(tokens) + "</p>")
    text = f"Intro {encoded} Outro"

    decoded = decode_rot47_segments(text)
    assert decoded is not None

    # The encoded tokens should be replaced with their decoded counterparts.
    for token in tokens:
        assert token in decoded

    # Context before/after the encoded block should remain intact.
    assert decoded.startswith("Intro ")
    assert decoded.endswith(" Outro")
    assert encoded not in decoded


def test_decode_rot47_segments_decodes_short_runs_with_markers():
    """Short runs WITH paragraph markers should be decoded (marker-based detection)."""
    tokens = ["short1", "short2", "short3", "short4", "short5"]
    encoded = _rot47("<p>" + " ".join(tokens) + "</p>")
    text = f"Intro {encoded} Outro"

    decoded = decode_rot47_segments(text)
    # With markers present (kAm/k^Am from <p></p>), content should be decoded
    for token in tokens:
        assert token in decoded
    assert decoded.startswith("Intro ")
    assert decoded.endswith(" Outro")


def test_looks_like_rot47_token_short_token():
    """Test short tokens return False (line 26)."""
    assert not _looks_like_rot47_token("abc")
    assert not _looks_like_rot47_token("ab")
    assert not _looks_like_rot47_token("a")
    assert not _looks_like_rot47_token("")


def test_looks_like_rot47_token_no_letters():
    """Test tokens with no letters return False (line 32)."""
    token_no_letters = "@?:;[]"  # ROT47 markers but no letters
    assert not _looks_like_rot47_token(token_no_letters)


def test_looks_like_rot47_token_too_many_letters():
    """Test tokens with >60% letters return False (line 36)."""
    # Need 4+ chars, has markers, but too many letters (>60%)
    token_mostly_letters = "abcd@e"  # 5 letters, 1 marker = 83% letters
    assert not _looks_like_rot47_token(token_mostly_letters)


def test_decode_segment_empty_decoded():
    """Test _decode_segment returns None for empty decoded text (line 71)."""
    # _decode_segment applies ROT47 first, then checks if result is empty
    # Need input that ROT47-decodes to whitespace
    # However, this is hard to construct. Let's test with actual whitespace.
    empty_segment = "   "
    result = _decode_segment(empty_segment)
    # ROT47 of whitespace is still whitespace, so decoded.strip() is empty
    assert result is None


def test_decode_rot47_segments_no_kAm_markers():
    """Test early return when kAm/k^Am markers absent (line 82)."""
    text = "This is normal text without any ROT47 encoding markers."
    # Should return immediately without processing
    result = decode_rot47_segments(text)
    assert result == text
