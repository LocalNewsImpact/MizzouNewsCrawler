"""An article whose fields are wrong stops rather than being exported.

A classification that removes an article is already held: `not_article`,
`obituary` and the rest are selected by no stage. A FIELD defect is not --
a garbage byline or an undecoded body sits on a `labeled` article, which
enrichment selects, so the bad value is enriched and exported before
anybody sees it.

Measured over 100,078 in-scope articles, 8,048 (8.0%) carry one: 4,570 a
byline that is not a name and 3,478 a body still in ciphertext. The second
is a single root cause -- the ROT47 decode -- producing 43% of the hold
volume, which is the point of holding: the queue depth says where the
pipeline is wrong.
"""

import pytest

from src.pipeline.review_hold import (
    IN_REVIEW,
    REVIEW_META_KEY,
    STAGE,
    apply_hold,
    field_defects,
    hold_note,
)

# --- wrong data holds --------------------------------------------------------


@pytest.mark.parametrize(
    "author",
    ["Admin", "MVeditor", "Ksdk", "TradingView", '["Admin"]', "1327", "Jeffrey"],
)
def test_a_byline_that_is_not_a_name_is_a_defect(author):
    assert "byline_not_a_name" in field_defects(author=author)


@pytest.mark.parametrize("marker", ["k^Am", "kE23=6", "lQA5C2?<Qm"])
def test_a_body_still_in_ciphertext_is_a_defect(marker):
    """TownNews serves paywalled bodies ROT47-encoded and `kE23=6 4=2DDlQ`
    is `<table class="p`. Undecoded, every field derived from it is wrong."""
    assert "text_not_decoded" in field_defects(text=f"prose {marker} more")


# --- absent data does not ----------------------------------------------------


@pytest.mark.parametrize("author", ["", "   ", None])
def test_a_missing_byline_is_not_a_defect(author):
    """29,885 articles have none, because plenty of publishers do not run
    them. Holding those would stop the corpus to ask a question with no
    answer."""
    assert field_defects(author=author) == []


# --- real bylines are left alone ---------------------------------------------


@pytest.mark.parametrize(
    "author",
    [
        "Jane Reporter",
        "Melissa Hernandez de la Cruz",
        "Maria de los Angeles Rodriguez",
        "Emily van de Riet",
        'Meredith "Kit" Bromfield',
        "Jane Smith, John Doe",
    ],
)
def test_a_real_byline_is_not_held(author):
    """A hold on a correct value is worse than no hold: it stops the
    corpus and trains reviewers to dismiss the queue."""
    assert field_defects(author=author) == []


def test_one_real_author_among_several_is_enough():
    assert field_defects(author="Admin, Jane Reporter") == []


# --- what the hold writes -----------------------------------------------------


def test_a_defect_moves_the_article_out_of_the_pipeline():
    status, meta = apply_hold("labeled", {}, ["byline_not_a_name"])
    assert status == IN_REVIEW


def test_the_note_records_what_to_put_back():
    """`status` is overwritten, so the claim and the status to restore have
    to live in metadata. The console reads exactly these keys."""
    _, meta = apply_hold("labeled", {}, ["byline_not_a_name"])
    note = meta[REVIEW_META_KEY]
    assert note["status_before"] == "labeled"
    assert note["claim"] == "byline_not_a_name"
    assert note["stage"] == STAGE
    assert note["held_at"]


def test_a_clean_row_is_untouched():
    status, meta = apply_hold("labeled", {"a": 1}, [])
    assert status == "labeled"
    assert meta == {"a": 1}


def test_an_already_held_row_keeps_its_first_note():
    """Re-holding would overwrite the note and lose the status it was
    holding, which is how the console puts the article back."""
    _, first = apply_hold("labeled", {}, ["byline_not_a_name"])
    status, second = apply_hold(IN_REVIEW, first, ["text_not_decoded"])
    assert status == IN_REVIEW
    assert second[REVIEW_META_KEY]["status_before"] == "labeled"
    assert second[REVIEW_META_KEY]["claim"] == "byline_not_a_name"


def test_holding_does_not_discard_other_metadata():
    status, meta = apply_hold(
        "labeled", {"extraction_method": "trafilatura"}, ["text_not_decoded"]
    )
    assert meta["extraction_method"] == "trafilatura"


def test_the_note_shape_matches_what_the_console_reads():
    """datadesk review/dispositions.py reads status_before, claim, stage
    and held_at. A key renamed on one side strands every held article."""
    assert set(hold_note("a_claim", "labeled")) == {
        "status_before",
        "claim",
        "stage",
        "held_at",
    }


# --- the write path -----------------------------------------------------------


def test_extraction_holds_before_it_inserts():
    """The hold has to be applied to article_status before the row is
    written, or the article is inserted on a status the pipeline reads."""
    from pathlib import Path

    body = Path("src/cli/commands/extraction.py").read_text()
    hold_at = body.index("review_hold.apply_hold")
    insert_at = body.index("ARTICLE_INSERT_SQL", hold_at - 4000)
    assert hold_at < insert_at


def test_a_released_row_flagged_again_gets_a_fresh_note():
    """A note from an earlier episode describes a hold already decided and
    released. Keeping it would restore the article to a status it left long
    ago, so a new hold writes a new note."""
    _, first = apply_hold("labeled", {}, ["byline_not_a_name"])
    # Released: the console restored it and it later re-entered the pipeline.
    released = dict(first)
    status, second = apply_hold("enriched", released, ["text_not_decoded"])
    assert status == IN_REVIEW
    assert second[REVIEW_META_KEY]["status_before"] == "enriched"
    assert second[REVIEW_META_KEY]["claim"] == "text_not_decoded"


def test_the_note_shape_comes_from_the_shared_contract():
    """Not a local copy that happens to match. Two copies with a test each,
    neither able to see the other, is what let a rename strand every held
    article."""
    from lnic_contracts import review_note as contract

    from src.pipeline.review_hold import IN_REVIEW as local_status
    from src.pipeline.review_hold import REVIEW_META_KEY as local_key

    assert local_status == contract.IN_REVIEW
    assert local_key == contract.METADATA_KEY
    _, meta = apply_hold("labeled", {}, ["byline_not_a_name"])
    assert contract.is_readable(contract.from_metadata(meta))
