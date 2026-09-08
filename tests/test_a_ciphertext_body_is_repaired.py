"""A body stored as ciphertext is a body nobody can read.

5,377 articles hold ROT47 where the story should be, 1,086 of them
published in March 2026 -- and 162 of those are `enriched` or `labeled`,
which is to say counted as local coverage and exported with ciphertext
in place of prose.

They were extracted before the decoder was repaired. Run against
production on 2026-09-08 the decoder already in the tree read 298 of 300
March bodies, and the 0.4 letter-ratio gate rejected none of 905
segments. Nothing needed inventing; nothing had passed over the rows.
"""

from src.cli.commands import rot47_body_repair as repair
from src.pipeline.text_cleaning import decode_rot47_segments


def test_the_marker_is_what_finds_them():
    """`k^Am` is ROT47 for `</p>`: in every encoded body, in no decoded
    one. Cheaper and more exact than re-running the detector."""
    assert repair.CIPHERTEXT_MARKER == "k^Am"
    assert repair.CIPHERTEXT_MARKER in str(repair.FIND_SQL)


def test_the_repair_does_not_touch_status():
    """Whether an article is wire, weather or local is not a question
    about its encoding. Rewriting status here would re-litigate 5,377
    verdicts a reviewer may already have decided."""
    written = str(repair.REPAIR_SQL)
    assert "status" not in written, "the repair rewrites a verdict"
    assert "wire" not in written
    for column in ("content", "text", "text_hash", "text_excerpt"):
        assert column in written


def test_it_selects_on_the_body_not_the_status():
    """These rows are spread across eight statuses -- wire 784, enriched
    135, out_of_scope 65 and so on -- so selecting by status would find
    some of them and no reliable subset."""
    found = str(repair.FIND_SQL)
    assert "content LIKE" in found
    assert "status" not in found


def test_a_body_that_will_not_decode_is_left_alone():
    """A partial decode written back is worse than ciphertext: the marker
    that finds these rows again would be gone, and the row would look
    repaired."""
    from pathlib import Path

    body = Path("src/cli/commands/rot47_body_repair.py").read_text()
    guard = body[body.index("if not decoded or") : body.index("unchanged += 1")]
    assert "CIPHERTEXT_MARKER in decoded" in guard
    assert "decoded == content" in guard


def test_the_decoder_reads_what_the_page_served():
    """A body as production actually holds it, taken from an article
    still carrying ciphertext on 2026-09-08.

    The shape matters: prose that was never encoded runs ahead of the
    encoded segment, `kAm` and `k^Am` are the paragraph tags, and the
    page has escaped its own angle brackets as `&gt;` and `&lt;` -- which
    is what has to be unescaped before decoding, or every `k` and `m` in
    the recovered text comes back as `U=Ej`.
    """
    encoded = (
        "The winning numbers in Friday's drawing of the "
        '"Illinois Pick 4 Midday" game were:kAm_[ _[ c[ c[ q@?FDi ak^Am'
        "kAmWK6C@[ K6C@[ 7@FC[ 7@FC[ q@?FDi EH@Xk^Am"
        "kAmu@C &gt;@C6 =@EE6CJ C6DF=ED[ 8@ E@ k2 9C67lQ9EEADi^^HHH];24&lt;A@"
    )
    decoded = decode_rot47_segments(encoded)
    assert decoded is not None
    assert repair.CIPHERTEXT_MARKER not in decoded
    # The numbers the ciphertext was hiding.
    assert "0, 0, 4, 4" in decoded
    # And the prose that was never encoded is still there, untouched.
    assert "The winning numbers in Friday" in decoded


def test_prose_is_returned_unchanged():
    """The decoder must not damage a body that was never encoded."""
    prose = "The council met on Tuesday. It voted 5-2 to approve the plan."
    assert decode_rot47_segments(prose) == prose
