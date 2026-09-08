"""A link that says `paused` while its article is finished is lying.

33,289 of them: 20,209 whose article is enriched, labelled or skipped,
and 13,080 carrying a content verdict. Nothing is blocked -- both
extraction selectors require `status = 'article'` AND no article row, so
a link with an article is never re-extracted whatever it says -- but
every count drawn from `candidate_links.status` is wrong by that much.
The Blocked page read 26,918 never-fetched where 8,407 were.
"""

from src.cli.commands import link_status_repair as repair


def test_a_finished_article_puts_its_link_at_extracted():
    """Read from the corpus, not chosen: where a link and its article
    agree, enriched is extracted 84% of the time, labeled 74%,
    enrichment_skipped 76%."""
    assert repair.FINISHED_LINK_STATUS == "extracted"
    assert set(repair.FINISHED) == {"enriched", "labeled", "enrichment_skipped"}


def test_a_judged_article_puts_its_link_at_the_same_verdict():
    """wire is wire 71% of the time, obituary 63%, opinion 85%,
    weather 85%. The link repeats the verdict rather than flattening it,
    because that is what the content rule writes when it writes both."""
    for verdict in ("wire", "obituary", "opinion", "weather"):
        assert verdict in repair.VERDICTS


def test_the_two_groups_do_not_overlap():
    """A status cannot be both a stage and a verdict, or the second pass
    would undo the first."""
    assert not set(repair.FINISHED) & set(repair.VERDICTS)


def test_only_paused_links_are_touched():
    """A link already agreeing with its article is not rewritten, and a
    link with no article is left alone: that one may really be held."""
    for statement in (str(repair.COUNT_SQL), str(repair.REPAIR_SQL)):
        assert "cl.status = 'paused'" in statement
        assert "JOIN articles a ON a.candidate_link_id = cl.id" in statement


def test_the_repair_is_batched_and_repeatable():
    """33,289 rows against a two-minute default statement timeout. The
    same statement run again finds only what it has not repaired, so a
    run that dies halfway costs nothing."""
    written = str(repair.REPAIR_SQL)
    assert "LIMIT :batch" in written
    assert "status = 'paused'" in written, "a second run would re-touch settled rows"


def test_the_stale_reason_goes_with_the_stale_status():
    """ "Re-paused: already extracted" described a hold that is being
    lifted. Leaving it behind would put a reason on a link that is no
    longer paused."""
    assert "error_message = NULL" in str(repair.REPAIR_SQL)
