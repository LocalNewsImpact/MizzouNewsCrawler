"""A person judged the URL; extraction has to act on the judgement.

The discovery review queue asks "is this a story, and what kind" before
anything is fetched. Restoring the URL used to be the whole of the answer
that survived: the type went into the console's own decision record,
where the crawler cannot see it. The URL was fetched again, the same
classifier that had misjudged it badly enough to put it in the queue ran
again, and whatever it decided is what stuck.

A reviewer who said "opinion" watched the article land in `labeled` and
get enriched, which is the opposite of what they said.

`obituary`, `opinion` and `weather` are statuses no enrichment stage
selects, so recording the type IS the instruction not to enrich.
"""

import inspect
import json

import pytest
from lnic_contracts import discovery_verdict

from src.cli.commands import extraction
from src.cli.commands.extraction import _reviewers_verdict


def test_a_verdict_is_read_off_the_link():
    note = discovery_verdict.build(verdict=discovery_verdict.IS_A_STORY, kind="opinion")
    found = _reviewers_verdict({discovery_verdict.METADATA_KEY: note})
    assert found == note
    assert discovery_verdict.status_for(found) == "opinion"


def test_a_json_string_column_is_read_too():
    """`meta` is Postgres `json`. The driver hands back a decoded dict on
    one connection and a string on another, and a reader that assumed one
    of them worked in tests and not in production."""
    note = discovery_verdict.build(verdict=discovery_verdict.IS_A_STORY, kind="weather")
    raw = json.dumps({discovery_verdict.METADATA_KEY: note})
    assert _reviewers_verdict(raw) == note


@pytest.mark.parametrize(
    "meta",
    [
        None,
        {},
        "not json at all",
        {"review_verdict": None},
        {"review_verdict": {"verdict": "story"}},
        {
            "review_verdict": {
                "verdict": "story",
                "kind": None,
                "decided_at": "2026-09-09",
            }
        },
    ],
)
def test_nothing_usable_is_no_verdict(meta):
    """An unusable verdict must read as absent rather than as an answer.
    `str(None)` is "None", which is not empty -- the shape that would
    have slipped past a truthiness check."""
    assert _reviewers_verdict(meta) is None


def test_reading_a_verdict_asks_the_database_nothing():
    """It takes the value, not the session.

    Two earlier versions ran a query -- one per article, then one per
    batch -- and both sat in front of the block that catches an article's
    own database errors, where a broad `except` swallowed the failure
    that block exists to see. Three rollback tests caught it, and moving
    the query did not help because any query consumed the same mocked
    side effect. `meta` now comes down with the row already being
    selected.
    """
    # The code, not the prose: the docstring above says "session" and an
    # assertion that reads it is asserting about a comment.
    assert "session" not in inspect.signature(_reviewers_verdict).parameters
    body = inspect.getsource(_reviewers_verdict)
    body = body[body.index('"""', body.index('"""') + 3) + 3 :]
    assert ".execute(" not in body, body
    assert "session" not in body, body


def test_the_row_carries_meta_from_both_builders():
    """Extraction builds its rows two ways. Unpacking six values is the
    guard: a column added to one builder and not the other fails loudly
    here rather than silently arriving as None."""
    source = inspect.getsource(extraction)
    assert "cl.meta" in source, "the direct query does not select meta"
    assert (
        "url_id, url, source, status, canonical_name, link_meta = row" in source
    ), "the row is not unpacked with meta"


# ------------------------------------------------ what the status becomes


@pytest.mark.parametrize("kind", ["obituary", "opinion", "weather"])
def test_a_kept_but_unenriched_type_decides_the_status(kind):
    note = discovery_verdict.build(verdict=discovery_verdict.IS_A_STORY, kind=kind)
    assert discovery_verdict.status_for(note) == kind


@pytest.mark.parametrize("kind", ["news", "column"])
def test_an_ordinary_story_leaves_the_detector_alone(kind):
    """News and columns ARE the ordinary pipeline. Overriding the status
    for them would stop articles the corpus wants enriched."""
    note = discovery_verdict.build(verdict=discovery_verdict.IS_A_STORY, kind=kind)
    assert discovery_verdict.status_for(note) is None


def test_wire_never_loses_to_a_verdict():
    """Wire is settled by evidence in the body -- a byline, a canonical
    pointing elsewhere -- which is exactly what a reviewer judging a bare
    URL could not see."""
    source = inspect.getsource(extraction)
    applied = source[source.index("A REVIEWER'S VERDICT DECIDES") :]
    applied = applied[: applied.index("now = datetime.utcnow()")]
    assert 'article_status != "wire"' in applied, applied[:400]
