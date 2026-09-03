"""Stop an article whose fields are wrong, rather than exporting it.

A classification that removes an article from the pipeline is already
held: `not_article`, `obituary` and the rest are selected by no stage. A
FIELD defect is not. A garbage byline or an undecoded body sits on a
`labeled` article -- 85,246 of them -- which enrichment picks up, so the
bad value is enriched and exported before anybody sees it.

`in_review` is selected by no stage. Nothing releases a held article but a
decision in the review console. There is no timeout and no release valve:
what is a risk to the export is not knowable in advance, so the safe
default is to stop and ask. Reviews piling up is not a failure of the
queue, it is the pipeline reporting how often it is wrong.

WHAT HOLDS AND WHAT DOES NOT
----------------------------
Wrong data holds. Absent data does not.

A byline that is not a name is wrong -- somebody's name has been replaced
by "Admin", a station's callsign or a Python repr. An undecoded body is
wrong: it is ciphertext where prose should be.

A byline that is simply missing is not wrong. 29,885 articles have none,
because plenty of publishers do not run them, and holding those would stop
the corpus to ask a question with no answer.

THE NOTE
--------
`status` is overwritten by `in_review`, so the claim being reviewed and
the status to restore live in metadata under `review`. The shape is fixed
by the console that reads it (datadesk review/dispositions.py): it needs
status_before, claim, stage and held_at.
"""

from __future__ import annotations

IN_REVIEW = "in_review"
REVIEW_META_KEY = "review"

#: The stage this hold is raised from. The console forms its question from
#: the claim and the stage, so two stages raising the same claim stay two
#: separate questions.
STAGE = "extraction"

#: Text that reached the row as ciphertext. TownNews serves paywalled
#: bodies ROT47-encoded and `kE23=6 4=2DDlQ` is `<table class="p`; where
#: the decode did not run, the body is unreadable and every field derived
#: from it is wrong.
ROT47_MARKERS = ("k^Am", "kE23=6", "lQA5C2?<Qm")


def _looks_rot47(text: str | None) -> bool:
    if not text:
        return False
    return any(marker in text for marker in ROT47_MARKERS)


def _byline_is_wrong(author: str | None) -> bool:
    """A byline that holds something other than a person's name.

    Uses the cleaner's own name test, so the queue and the cleaner cannot
    disagree about what a name is. Empty is not wrong -- see the module
    docstring.
    """
    value = (author or "").strip()
    if not value:
        return False
    from src.utils.byline_cleaner import BylineCleaner

    # Several authors: right if any part is a person.
    parts = [p.strip() for p in value.replace(";", ",").split(",") if p.strip()]
    if parts:
        return not any(BylineCleaner._looks_like_a_person(p) for p in parts)
    return not BylineCleaner._looks_like_a_person(value)


def field_defects(*, author: str | None = None, text: str | None = None) -> list[str]:
    """Which field-level defects this row carries, as claim names.

    The claim is what the reviewer is being asked about, and what the
    console keys its question on.
    """
    defects = []
    if _byline_is_wrong(author):
        defects.append("byline_not_a_name")
    if _looks_rot47(text):
        defects.append("text_not_decoded")
    return defects


def hold_note(claim: str, status_before: str) -> dict:
    """The note the console reads to form its question and put the row back."""
    from datetime import datetime, timezone

    return {
        "status_before": status_before,
        "claim": claim,
        "stage": STAGE,
        "held_at": datetime.now(timezone.utc).isoformat(),
    }


def apply_hold(status: str, metadata: dict | None, defects: list[str]) -> tuple:
    """Return the status and metadata to write, holding if anything is wrong.

    Takes the first defect as the claim. A row with two wrong fields is one
    question to a reviewer looking at it; the second is asked again if it
    survives the first decision, because a new claim is a new question.

    Leaves a row already held alone: re-holding would overwrite the note
    and lose the status it was holding.
    """
    if not defects or status == IN_REVIEW:
        return status, metadata
    meta = dict(metadata or {})
    if REVIEW_META_KEY in meta:
        return status, metadata
    meta[REVIEW_META_KEY] = hold_note(defects[0], status)
    return IN_REVIEW, meta
