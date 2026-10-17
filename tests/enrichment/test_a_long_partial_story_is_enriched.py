"""A long partial story is enriched; only a stub is skipped.

The re-run of March 2026 skipped stories the gate never saw in August. Two
Unterrified Democrat stories (Osage County's only outlet) carry 6,500 and
15,700 characters of story before "This item is available in full to
subscribers", and the model reads partial text: their places are real. And a
complete 3,900-character Joplin Globe story was read as cut off because
TownNews prints "Javascript is required for you to be able to read premium
content" mid-body.
"""

from __future__ import annotations

from src.enrichment.gate import long_partial_story, paywalled_stub, unique_story_chars
from src.utils.boilerplate import strip_premium_notice

SENTENCES = [
    f"Archer number {i} from Linn shot a strong round at the Vienna qualifier today."
    for i in range(40)
]
LONG = " ".join(SENTENCES) + " This item is available in full to subscribers."
TEASER = (
    "Warren County residents are invited to the open house on March 25. " * 3
    + "This item is available in full to subscribers. Subscribe now! Log in."
)


class TestTheWallRule:
    def test_a_long_partial_story_is_not_a_stub(self):
        assert long_partial_story(LONG)
        assert paywalled_stub(LONG) is None

    def test_a_repeated_teaser_is_still_a_stub(self):
        """The shape the wall rule exists for: repetition does not count."""
        assert not long_partial_story(TEASER)
        assert paywalled_stub(TEASER) == "available in full to subscribers"

    def test_repeated_sentences_count_once(self):
        assert unique_story_chars("Same sentence here. " * 50) < 30


class TestThePremiumNotice:
    STORY = (
        "The New Heights students spent the week serving the community. "
        "They painted, cleaned and cooked for neighbors across Joplin, and "
        "teachers said the week gives them a chance to serve during the year. "
    ) * 2

    def test_it_is_removed_when_a_story_follows(self):
        body = (
            "Missions Week began Monday. Javascript is required for you to be "
            "able to read premium content. Please enable it in your browser "
            "settings. " + self.STORY
        )
        out = strip_premium_notice(body)
        assert "Javascript" not in out and "premium content" not in out
        assert out.startswith("Missions Week began Monday.")
        assert "serving the community" in out

    def test_it_is_kept_when_nothing_follows(self):
        """Then it may be the wall itself."""
        body = "A short teaser. Javascript is required for you to be able to read premium content."
        assert strip_premium_notice(body) == body
