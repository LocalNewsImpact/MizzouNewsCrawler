"""focus-v2: a story centred on a county says so.

v1's prompt could only answer with a city, and the adapter enforced that
-- no city, no focus step. So a story centred on a county reached for the
county seat: "Jackson County Detention Center" came back as Kansas City,
"Ottawa County Election Board" as Miami, "Ray County Museum" as Richmond.
24.1% of fabricated points were that shape.

v2 tells the model to give the county and leave the city empty. On ten
articles through the real adapter it did so three times -- Johnson,
Warren and St. Francois -- and all three resolved to a county GEOID.
Rejecting those answers here would have thrown away the fix and left
those stories with no geography at all.
"""

from __future__ import annotations

import pytest

from src.enrichment import adapter


def _payload(central, mentions=()):
    """What `run_focus` builds, exercised through its own parsing."""
    return {"central": central, "mentions": list(mentions), "rationale": "because"}


class TestWhatCountsAsAnAnswer:
    def test_the_prompt_version_is_recorded(self):
        """Every row carries the prompt that produced it, so a change is
        auditable after the fact rather than guessed at."""
        assert adapter.FOCUS_PROMPT_VERSION == "focus-v2"

    def test_the_prompt_forbids_the_things_that_fabricated(self):
        """The four sources measured as fabrication, named in the file
        the model actually reads."""
        text = (adapter.PROMPTS_DIR / "focus.md").read_text().lower()
        assert "dateline" in text
        assert "masthead" in text or "publication's identity" in text
        assert "biography" in text
        assert "popular stories" in text or "related-story rails" in text

    def test_the_prompt_still_permits_induction(self):
        """The correction of 2026-09-15: inferring a place from an
        institution the story NAMES is reporting and is wanted."""
        text = (adapter.PROMPTS_DIR / "focus.md").read_text().lower()
        assert "tolton" in text or "westminster" in text

    def test_the_prompt_asks_for_evidence(self):
        text = (adapter.PROMPTS_DIR / "focus.md").read_text().lower()
        assert "quote" in text
        assert "evidence" in text


class TestTheResponseBudget:
    def test_it_is_large_enough_for_quoted_evidence(self):
        """v2 quotes the phrase it reasoned from, for the centre and for
        every mention. At 300 the JSON truncated and the parse failed
        with it; the longest real answer measured 458 tokens."""
        import re
        from pathlib import Path

        source = Path("src/enrichment/adapter.py").read_text()
        focus = source[source.index("def run_focus(") :]
        budget = int(re.search(r"max_tokens=(\d+)", focus).group(1))
        assert budget >= 600


class TestANullCityIsNotTheStringNone:
    """`str(central.get("city"))` is "None" when the key is null, and v2
    returns a null city whenever it answers with a county. v1 would have
    written the literal string "None" into point_place."""

    def test_an_absent_city_reads_as_none(self):
        central = {"city": None, "county": "Warren County", "state": "MO"}
        city = str(central.get("city") or "")[:120] or None
        assert city is None

    def test_a_present_city_still_reads(self):
        central = {"city": "Mexico", "state": "MO"}
        assert (str(central.get("city") or "")[:120] or None) == "Mexico"


class TestTheGuard:
    """Asserted on the source: the condition is one line and getting it
    backwards fails every county-only story silently."""

    @pytest.fixture
    def guard(self):
        from pathlib import Path

        source = Path("src/enrichment/adapter.py").read_text()
        start = source.index("def run_focus(")
        return source[start : start + 4000]

    def test_a_county_only_answer_is_accepted(self, guard):
        assert 'if not central.get("city") and not central.get("county"):' in guard

    def test_neither_is_still_refused(self, guard):
        assert 'raise ValueError("no central geography in focus response")' in guard

    def test_the_county_reaches_the_payload(self, guard):
        assert '"county": str(central.get("county") or "")[:120] or None' in guard

    def test_the_evidence_reaches_the_payload(self, guard):
        assert '"evidence": str(central.get("evidence") or "")[:300] or None' in guard

    def test_a_mention_may_be_a_county_too(self, guard):
        assert 'if isinstance(m, dict) and (m.get("city") or m.get("county"))' in guard


class TestTheWritePathStoresIt:
    """The prompt and the adapter are pointless if `persist_outcome`
    drops the county on the floor, which is what it did before."""

    @pytest.fixture
    def source(self):
        from pathlib import Path

        return Path("src/enrichment/repository.py").read_text()

    def test_a_county_only_centre_is_resolved(self, source):
        assert 'if geoid is None and central.get("county"):' in source

    def test_it_is_gated_like_every_other_claim(self, source):
        assert '_says(article, central["county"], named_places)' in source

    def test_the_method_says_which_rung_answered(self, source):
        """`point_method` is how the corpus can be split by how the claim
        was made; a county centre is not the same claim as a city one."""
        assert '"focus_model_county"' in source
