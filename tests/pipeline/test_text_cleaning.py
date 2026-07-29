from src.pipeline.text_cleaning import (
    _decode_segment,
    _looks_like_rot47_token,
    _marker_density,
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


class TestBoxScoreDecodesInsteadOfBeingRejected:
    """A box score decodes correctly and used to be thrown away anyway.

    Found 2026-07-28 on a real emissourian.com production row: every prose
    paragraph decoded and displayed correctly, then the "Box Score" section
    reverted to raw ciphertext. Not because it failed to decode -- because it
    decoded PERFECTLY and a validation gate rejected it anyway.

    The gate was `letters / len(decoded) >= 0.3`, an absolute floor on the
    OUTPUT. A box score is mostly digits and dashes, so it fails that floor
    even when the decode is exactly right:

        ciphertext: kA 4=2DDlQAcQm}r \\ _ \\ `c \\ _ \\ `_ l ack^Am
        decoded:    <p class="p4">NC - 0 - 14 - 0 - 10 = 24</p>
        letters=10 len=43 ratio=0.23 -- below 0.3, rejected

    Fixed by comparing marker density BEFORE and AFTER decoding instead: ROT47
    saturates ciphertext with a specific punctuation set, and real English
    (however letter-sparse) essentially never does. A genuine decode always
    reduces that saturation; a box score's raw ciphertext still shows it even
    though the box score's own letter count is low -- which is exactly why an
    absolute floor on the output was the wrong measure.
    """

    RAW_BOX_SCORE = r"kA 4=2DDlQAcQm}r \ _ \ `c \ _ \ `_ l ack^Am"
    RAW_SECOND_LINE = r"kA 4=2DDlQAcQm$%r \ _ \ `c \ _ \ _ l `ck^Am"
    # A real prose paragraph from the same production row, so the "full
    # article" test below exercises actual ciphertext throughout rather than
    # a hand-typed stand-in -- an earlier draft used a fabricated paragraph
    # that was already-plain English wearing a kAm/k^Am wrapper, which the
    # relative check correctly refused to touch (it never was ciphertext),
    # leaving a literal `k^Am` in the test's own expected output.
    RAW_INTRO = (
        "kA 4=2DDlQAcQm“(6’G6 8@E E@ 36 E@F896C[” $E] "
        "r=2:C w625 r@249 %C2G:D y@9?D@? D2:5]k^Am"
    )

    def test_the_box_score_decodes_correctly_on_its_own(self):
        """Pin the mechanism, not just the outcome: this IS a correct decode."""
        from src.pipeline.text_cleaning import _decode_rot47_text

        decoded = _decode_rot47_text(self.RAW_BOX_SCORE)
        assert "NC - 0 - 14 - 0 - 10 = 24" in decoded

    def test_the_old_absolute_floor_would_have_rejected_it(self):
        """Document WHY this needed fixing, not just that it now works."""
        from src.pipeline.text_cleaning import _decode_rot47_text

        decoded = _decode_rot47_text(self.RAW_BOX_SCORE)
        letters = sum(1 for ch in decoded if ch.isalpha())
        ratio = letters / len(decoded)
        assert ratio < 0.3, (
            "if this ever rises above 0.3 the box score stopped being the "
            "case that motivated the relative check -- re-derive from a "
            "current low-letter-ratio production example instead"
        )

    def test_marker_density_drops_after_a_genuine_decode(self):
        """The actual replacement rule."""
        from src.pipeline.text_cleaning import _decode_rot47_text

        decoded = _decode_rot47_text(self.RAW_BOX_SCORE)
        assert _marker_density(decoded) < _marker_density(self.RAW_BOX_SCORE)

    def test_a_full_article_with_a_box_score_decodes_completely(self):
        """End to end: no ciphertext survives anywhere in a real article."""
        article = f"{self.RAW_INTRO} {self.RAW_BOX_SCORE} {self.RAW_SECOND_LINE}"
        result = decode_rot47_segments(article)
        assert "kAm" not in result and "k^Am" not in result
        assert "tougher" in result
        assert "NC - 0 - 14 - 0 - 10 = 24" in result
        assert "STC - 0 - 14 - 0 - 0 = 14" in result

    def test_a_paragraph_that_genuinely_did_not_need_decoding_is_left_alone(self):
        """The relative check must not fire on plain text with no ciphertext.

        There is nothing to compare against a lower-density "after" if there
        was never a "before" -- decode_rot47_segments short-circuits before
        ever calling the marker-based decoder when no kAm/k^Am is present.
        """
        text = "The council met Tuesday and approved the budget unanimously."
        assert decode_rot47_segments(text) == text
