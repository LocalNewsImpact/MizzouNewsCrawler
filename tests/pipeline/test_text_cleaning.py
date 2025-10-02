from src.pipeline.text_cleaning import _rot47, decode_rot47_segments


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


def test_decode_rot47_segments_ignores_short_runs():
    tokens = ["short1", "short2", "short3", "short4", "short5"]
    encoded = _rot47("<p>" + " ".join(tokens) + "</p>")
    text = f"Intro {encoded} Outro"

    assert decode_rot47_segments(text) == text
