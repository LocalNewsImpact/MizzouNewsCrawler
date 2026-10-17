"""A statewide story is filed under the state it is about.

March 2026, Missouri: 1,810 enriched stories were `statewide`, and every one
was coded to the publication's state. A Kansas City station's stories on a
Kansas bill, a Kansas lawsuit and Kansas schools were filed under Missouri.
And in a sample of 25, 7 were a local team at a state event ("Doniphan girls
cruise in sectional rout of Potosi"): the state tournament is the venue, not
the impact, and the town's geography was lost.
"""

from __future__ import annotations

from src.enrichment import adapter
from src.enrichment.repository import story_state


def places(*states):
    return {"locations": [{"location": {"components": {"state": s}}} for s in states]}


class TestTheStoryState:
    def test_a_kansas_story_is_kansas(self):
        assert story_state(places("KS", "KS", "Kansas", "MO"), "MO") == "KS"

    def test_a_missouri_story_is_missouri(self):
        assert story_state(places("MO", "Missouri"), "MO") == "MO"

    def test_a_tie_goes_to_the_publication(self):
        assert story_state(places("KS", "MO"), "MO") == "MO"

    def test_no_state_named_falls_back_to_the_publication(self):
        assert story_state(places(None), "MO") == "MO"
        assert story_state(None, "MO") == "MO"

    def test_a_dict_state_is_read(self):
        payload = {
            "locations": [{"location": {"components": {"state": {"abbr": "IL"}}}}]
        }
        assert story_state(payload, "MO") == "IL"


class TestTheScopePrompt:
    def test_the_crawler_supplies_its_own_scope_prompt(self):
        text = (adapter.PROMPTS_DIR / "geographic_scope.md").read_text()
        assert "{text}" in text
        assert "A state event is the venue, not the impact" in text
        assert "Statewide means statewide in the state the story is about" in text
        assert adapter.SCOPE_PROMPT_VERSION == "geographic_scope-v2"

    def test_it_is_passed_to_the_node(self, monkeypatch):
        seen = {}

        def fake(step, node, params, inputs, model, **kw):
            seen.update(params)
            return None

        monkeypatch.setattr(adapter, "_run_node", fake)
        from src.enrichment.types import ArticleInput

        adapter.run_scope(ArticleInput("a", "t", "b", "ds", "Doniphan", "MO"), "m")
        assert "A state event is the venue" in seen["prompt"]


class TestAGameIsCentredOnItsTeam:
    def test_the_focus_prompt_says_so(self):
        """ "Blues in 5-4 loss to Sharks ... in San Jose" was filed under San
        Jose. The story is about St. Louis's team."""
        text = (adapter.PROMPTS_DIR / "focus.md").read_text()
        assert "HOME of the team" in text
        assert "San Jose" in text
        assert adapter.FOCUS_PROMPT_VERSION == "focus-v4"
