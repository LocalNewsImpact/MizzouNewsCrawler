"""The ROT47 paths that the paragraph decoder does not reach.

`decode_rot47_segments` tries paragraph markers first, because Lee
Enterprises wraps every encoded paragraph in `kAm`/`k^Am`. When that
returns nothing -- a closing marker with no opener, a fragment, markup
the pattern does not span -- a token scan runs instead, and it decides
what counts as ciphertext by shape alone.

That scan had no tests. It is the part that can do damage: mistaking
prose for ciphertext rewrites an article into gibberish, and the only
thing standing between the two is a letter ratio and a run length.
"""

from src.pipeline import text_cleaning as tc


def _encode(text: str) -> str:
    """ROT47 is an involution, so encoding is the same operation."""
    return tc._rot47(text)


# The scan recognises a token by punctuation density, and ROT47 produces its
# marker punctuation from o, n, i, j and l -- so a fixture has to be built
# from words that carry them. "the" encodes to "E96", which the scan reads
# as prose, and a run built from it never forms.
CIPHERTEXT_WORDS = [
    "commission",
    "opinion",
    "position",
    "coalition",
    "illinois",
    "collision",
    "resolution",
]


def _run(words=None) -> str:
    return " ".join(_encode(w) for w in (words or CIPHERTEXT_WORDS))


class TestLooksLikeRot47Token:
    def test_a_short_token_is_never_ciphertext(self):
        """Two- and three-character words are punctuation-dense by
        accident. Reading them as ciphertext is how a scan starts
        rewriting English."""
        assert not tc._looks_like_rot47_token(_encode("of"))

    def test_a_token_with_no_marker_punctuation_is_not_ciphertext(self):
        assert not tc._looks_like_rot47_token("ordinary")

    def test_a_token_with_no_letters_is_not_ciphertext(self):
        """A decoded run has to become letters. All-punctuation is more
        likely an ellipsis or a table rule."""
        assert not tc._looks_like_rot47_token("@@@@@@")

    def test_mostly_letters_is_prose_even_with_a_marker(self):
        """An email address or a citation carries `@` or `:` and is not
        ciphertext."""
        assert not tc._looks_like_rot47_token("reporter@example.com")

    def test_encoded_prose_is_recognised(self):
        assert tc._looks_like_rot47_token(_encode("council"))


class TestIterRot47Ranges:
    def test_a_short_run_is_left_alone(self):
        """Four encoded tokens in a row is within what English
        punctuation produces; the scan wants six."""
        assert list(tc._iter_rot47_ranges(_run(CIPHERTEXT_WORDS[:4]))) == []

    def test_a_long_run_is_returned_as_one_range(self):
        text = _run()
        ranges = list(tc._iter_rot47_ranges(text))
        assert len(ranges) == 1
        start, end = ranges[0]
        assert tc._rot47(text[start:end]).startswith("commission opinion")

    def test_prose_between_two_runs_is_not_swallowed(self):
        """A range that spans the English between two encoded blocks
        would decode the prose too, and prose decoded once is gone."""
        run = _run()
        text = f"{run} and then plain English words appear here {run}"
        ranges = list(tc._iter_rot47_ranges(text))
        assert len(ranges) == 2
        first_end, second_start = ranges[0][1], ranges[1][0]
        assert "plain English words" in text[first_end:second_start]

    def test_a_run_at_the_end_of_the_text_is_not_dropped(self):
        """The loop yields on the token that ends a run; a run that ends
        with the text has no such token."""
        text = "Opening prose. " + _run()
        assert len(list(tc._iter_rot47_ranges(text))) == 1


class TestDecodeSegment:
    def test_a_segment_that_decodes_to_prose_is_returned(self):
        decoded = tc._decode_segment(_encode("the council approved the budget"))
        assert decoded == "the council approved the budget"

    def test_a_segment_that_decodes_to_punctuation_is_refused(self):
        """Below a letter ratio the 'decode' is noise, and writing it
        into the article destroys whatever was there."""
        assert tc._decode_segment(_encode("--- === +++ ***")) is None

    def test_an_empty_segment_is_refused(self):
        assert tc._decode_segment("   ") is None

    def test_markup_the_decode_reveals_is_removed(self):
        """The encoding hides real tags, so decoding hands them back."""
        decoded = tc._decode_segment(_encode('<p class="p1">Council met</p>'))
        assert "<p" not in decoded and "</p>" not in decoded
        assert "Council met" in decoded


class TestMarkerDensity:
    def test_english_is_almost_free_of_the_marker_set(self):
        assert tc._marker_density("The council approved the budget.") < 0.05

    def test_ciphertext_is_saturated_with_it(self):
        assert tc._marker_density(_encode("The commission opinion on pollution")) > 0.2

    def test_an_empty_string_is_zero_not_a_division_error(self):
        assert tc._marker_density("") == 0.0


class TestDecodeRot47Segments:
    def test_the_token_scan_runs_when_the_paragraph_pattern_finds_nothing(self):
        """A closing marker with no opener satisfies the short-circuit
        and produces no paragraph match, which is the only route to the
        token scan."""
        text = "k^Am " + _run()
        result = tc.decode_rot47_segments(text)
        assert "commission opinion position coalition illinois" in result

    def test_text_with_no_markers_is_returned_untouched(self):
        prose = "The council approved the budget on Tuesday."
        assert tc.decode_rot47_segments(prose) == prose

    def test_none_and_empty_are_returned_as_they_came(self):
        assert tc.decode_rot47_segments(None) is None
        assert tc.decode_rot47_segments("") == ""

    def test_a_marker_with_nothing_decodable_leaves_the_text_alone(self):
        """Refusing every candidate has to mean 'unchanged', not
        'emptied'."""
        text = "k^Am ordinary prose that is not encoded at all"
        assert tc.decode_rot47_segments(text) == text

    def test_the_horizontal_rule_marker_does_not_survive(self):
        encoded = _encode("<p>The commission opinion on pollution</p>")
        text = f"{encoded} k9C ^m {encoded}"
        result = tc.decode_rot47_segments(text)
        assert "k9C" not in result
        assert result.count("The commission opinion on pollution") == 2
