"""An exclusion decided at enrichment is reviewed, not written.

Enrichment is the last step before export and it has signals the earlier
stages do not -- a model reads the body. So it finds things they missed: a
stub, a page that is not news, a story about somewhere else. Its findings
are worth having. They are not, yet, worth acting on unseen.

Anything enrichment decides that would stop a record being eligible for
export is held for a person instead of written: `not_article` from the
model's gate or the boilerplate score, `out_of_scope` from the scope step.
A paywall stub is not held -- it stays exportable, with its CIN label, and
only the enrichment is withheld -- so nothing about it needs a person.

WHY A HOLD AND NOT A STATUS
---------------------------
Two reasons, both measured on 2026-09-13.

The model is wrong often enough to matter. Of 75 articles it called
"international", 50 carried a local byline and the sample read as
Whiteman AFB, the Royals, and Columbia's own film festival. Written as an
exclusion those are lost from the corpus with nothing to notice.

And a person may already have ruled. An article accepted in the extraction
queue as a real story reaches enrichment, and the gate's `not_news` used
to write `not_article` over that decision -- silently, because the queue
had already answered the question `not_article:enrichment` and would not
ask it again. Machine over human, with nobody told.

Held, the record sits at `in_review` with the claim, the stage and the
status to restore, exactly as an extraction-stage hold does, and the
console's held case shows it. A person confirms the exclusion or overrules
it. And a claim a person has answered is not raised again: the gate reads
the answer before refusing, the way the extraction hold does.
"""

from __future__ import annotations

from lnic_contracts import review_note as _contract

IN_REVIEW = _contract.IN_REVIEW
REVIEW_META_KEY = _contract.METADATA_KEY

#: The stage these holds are raised from. The console forms its question
#: from the claim and the stage, so an enrichment finding and an extraction
#: finding with the same name are two different questions.
STAGE = "enrichment"

#: Outcomes that would stop a record being eligible for export. These are
#: held. Everything else enrichment writes -- `enriched`,
#: `enrichment_skipped` -- leaves the record exportable and is written as
#: decided.
HELD_STATUSES: frozenset[str] = frozenset({"not_article", "out_of_scope"})

#: What the console's verbs mean on a held row, and why `status_before` is
#: the EXCLUSION and not `labeled`:
#:
#:   accept   the claim is right. The console restores `status_before`, so
#:            it must be the status the gate wanted -- `not_article`,
#:            `out_of_scope` -- exactly as an extraction hold's is the
#:            status the flag was raised under. Set to `labeled` it would
#:            send a CONFIRMED exclusion back to be enriched.
#:   restore  it is a real story. The console rewinds to `labeled`
#:            (REWIND_TO[enrichment]) and the record is enriched on the
#:            next run -- with the gate reading the answer and not refusing
#:            it again.
#:
#: The status to restore therefore travels on the note per outcome; there
#: is no single constant.


def should_hold(status: str) -> bool:
    """Whether an enrichment outcome with this status is reviewed first."""
    return status in HELD_STATUSES


#: The one decision that confirms the gate rather than overruling it.
CONFIRMED = "accept"


def answered_claims(metadata: dict | None) -> frozenset[str]:
    """Claims from this stage a person has OVERRULED.

    Read before the gate runs, so a refusal a person overruled is not made
    again. Two things are deliberately not here:

    - Another stage's answers. An extraction-stage decision about
      `not_article` is a different question and does not bind the gate.
    - A confirmation. `accept` says the gate was right; the record went to
      its exclusion and does not come back. If it ever did, the gate should
      be free to find the same thing again.
    """
    found = set()
    for record in _contract.decisions(metadata).values():
        if (
            record.get("stage") == STAGE
            and record.get("claim")
            and record.get("decision") != CONFIRMED
        ):
            found.add(record["claim"])
    return frozenset(found)


def hold(metadata: dict | None, claim: str, exclusion: str) -> tuple[str, dict]:
    """The status and metadata to write instead of the exclusion.

    `exclusion` is the status the gate wanted; it becomes `status_before`
    so that a reviewer's accept restores it (see the note above).

    A fresh note each time: the record is not held now (the caller checks
    `should_hold` on an outcome it is about to write), so any earlier note
    describes a hold already decided and released.
    """
    meta = dict(metadata or {})
    meta.pop(REVIEW_META_KEY, None)
    meta[REVIEW_META_KEY] = _contract.build(
        claim=claim, status_before=exclusion, stage=STAGE
    )
    return IN_REVIEW, meta
