"""How a page was obtained survives whichever parser won the fields.

`authenticated_session` and `http_status` were written into the Selenium
result's own `metadata` dict. On the cascade path they never reached a row.
The Selenium capture is re-parsed by mcmetadata FIRST -- that is deliberate,
a real parser on the better capture -- which fills the `metadata` slot. The
Selenium merge then runs with `fields_to_copy=still_missing`, `metadata` is no
longer missing, and `_merge_extraction_results` does:

    target[field] = source_value

which REPLACES the whole dict rather than merging its keys. So the better
parser threw away the fetch's own record of itself.

Measured on the first authenticated yakimaherald run (2026-09-20, workflow
`authenticated-extraction-cjts9`): the pod log says "Authenticated session
established for yakimaherald.com" at 19:14:52 and the three rows it went on to
store all carry `extraction_method=mcmetadata` with `authenticated_session`,
`http_status` and `selenium_reason` absent. Same root cause as the
`candidate_links.http_status` NULLs on the queue path, which reads
`metadata_value["http_status"]`.

The fix is not "also merge metadata keys". It is that these two are facts about
the FETCH, so no parser may own them: they are stamped after the cascade,
beside `extraction_method`, which is the fact-about-the-whole-extraction that
was already recorded exactly there.
"""

from __future__ import annotations

import inspect

import pytest

from src.crawler import ContentExtractor


@pytest.fixture
def extractor():
    e = ContentExtractor.__new__(ContentExtractor)
    e._latest_wire_hints = None
    e._latest_cms_metadata = None
    e._raw_html_by_method = {}
    return e


class TestTheRootCauseIsRealNotAssumed:
    """Prove the mechanism, so the fix is not aimed at a guess.

    This is the defect itself, exercised: a merge that is not told to copy
    `metadata` leaves the target's dict alone, and one that IS told to copy it
    replaces the dict wholesale. Either way the source's own keys do not end up
    beside the target's.
    """

    def test_a_merge_not_copying_metadata_drops_the_fetch_keys(self, extractor):
        target = {
            "metadata": {"extraction_method": "mcmetadata"},
            "extraction_methods": {},
        }
        source = {"metadata": {"authenticated_session": True, "http_status": 200}}
        # `still_missing` after mcmetadata filled everything: metadata is absent
        # from it, which is exactly the production case.
        extractor._merge_extraction_results(
            target, source, "selenium", fields_to_copy=["author"]
        )
        assert "authenticated_session" not in target["metadata"]

    def test_a_merge_that_does_copy_metadata_replaces_rather_than_blends(
        self, extractor
    ):
        target = {
            "metadata": {"extraction_method": "mcmetadata", "meta_description": "d"},
            "extraction_methods": {},
        }
        source = {"metadata": {"authenticated_session": True}}
        extractor._merge_extraction_results(
            target,
            source,
            "selenium",
            fields_to_copy=["metadata"],
            allow_overwrite=True,
        )
        # The source dict won entirely: mcmetadata's own keys are gone. So
        # "just merge metadata too" would trade one loss for another.
        assert target["metadata"] == {"authenticated_session": True}


class TestTheStampSurvivesTheWinningParser:
    def test_the_authenticated_marker_is_written_even_when_mcmetadata_owns_metadata(
        self,
    ):
        """The exact production failure: mcmetadata won, so the key vanished."""
        source = inspect.getsource(ContentExtractor.extract_content)
        body = "\n".join(
            line for line in source.splitlines() if not line.strip().startswith("#")
        )
        # Stamped on result_copy's metadata, after the cascade -- not left to a
        # merge. Asserted on the comment-stripped body: the docstring above and
        # the code comments both name the old behaviour, and a substring check
        # against those would pass with the fix reverted.
        assert 'result_copy["metadata"]["authenticated_session"]' in body
        assert "self._session_state(url)" in body

    def test_it_is_stamped_beside_extraction_method_not_before_it(self):
        """Order matters: the cascade must be over.

        Stamped earlier, a later merge could replace the whole metadata dict
        again and the fix would be undone by the very mechanism it exists for.
        """
        source = inspect.getsource(ContentExtractor.extract_content)
        body = "\n".join(
            line for line in source.splitlines() if not line.strip().startswith("#")
        )
        primary = body.index('result_copy["metadata"]["extraction_method"]')
        authed = body.index('result_copy["metadata"]["authenticated_session"]')
        assert primary < authed

    def test_no_merge_can_reach_it(self):
        """It is assigned on result_copy, which nothing merges into.

        `_merge_extraction_results` writes to the `result` dict during the
        cascade; `result_copy` is built after the last merge has run.
        """
        source = inspect.getsource(ContentExtractor.extract_content)
        # Comments stripped: the explanation beside the fix names
        # `_merge_extraction_results`, so an unstripped check matches the prose
        # rather than the code and would fail with the fix in place.
        body = "\n".join(
            line for line in source.splitlines() if not line.strip().startswith("#")
        )
        after = body[body.index("result_copy = result.copy()") :]
        assert "_merge_extraction_results" not in after


class TestTheValueItStamps:
    def test_a_credentialed_host_with_a_session_records_true(
        self, extractor, monkeypatch
    ):
        monkeypatch.setattr(extractor, "_requires_login", lambda h: True)
        monkeypatch.setattr(
            ContentExtractor, "_authenticated_domains", {"yakimaherald.com"}
        )
        assert extractor._session_state("https://www.yakimaherald.com/a.html") is True

    def test_a_credentialed_host_without_one_records_false_not_none(
        self, extractor, monkeypatch
    ):
        """False and None must not collapse.

        None means the question does not apply. False is the finding: post-#635
        the fetch is refused, so a False on a written row says the refusal
        leaked.
        """
        monkeypatch.setattr(extractor, "_requires_login", lambda h: True)
        monkeypatch.setattr(ContentExtractor, "_authenticated_domains", set())
        assert extractor._session_state("https://www.yakimaherald.com/a.html") is False

    def test_an_ordinary_host_records_none(self, extractor, monkeypatch):
        monkeypatch.setattr(extractor, "_requires_login", lambda h: False)
        assert extractor._session_state("https://example.com/a.html") is None


class TestHttpStatusIsFilledNotClobbered:
    def test_it_fills_the_null_the_queue_path_was_reading(self):
        source = inspect.getsource(ContentExtractor.extract_content)
        body = "\n".join(
            line for line in source.splitlines() if not line.strip().startswith("#")
        )
        assert "_last_fetch_http_status" in body
        # Guarded, so a parser's own value wins.
        assert 'result_copy["metadata"].get("http_status") is None' in body

    def test_a_parsers_own_status_is_kept(self):
        """newspaper4k recovers a status from its own failure ("Status code
        403"); `_last_fetch_http_status` does not know that."""
        source = inspect.getsource(ContentExtractor.extract_content)
        body = "\n".join(
            line for line in source.splitlines() if not line.strip().startswith("#")
        )
        stamp = body.index('result_copy["metadata"]["http_status"]')
        guard = body.index('result_copy["metadata"].get("http_status") is None')
        assert guard < stamp

    def test_it_tolerates_html_somebody_else_fetched(self):
        """`extract_content(url, html=...)` performs no fetch, so the attribute
        the fetch sets need not exist."""
        source = inspect.getsource(ContentExtractor.extract_content)
        # Collapsed, because black wraps the call across lines.
        flat = " ".join(source.split())
        assert 'getattr( self, "_last_fetch_http_status", None )' in flat


class TestTheMergeStillBehavesAsDesigned:
    def test_the_replacement_is_left_alone(self):
        """The fix does NOT change the merge.

        Whole-dict replacement is what makes the winning parser's metadata
        coherent; turning it into a key merge would blend two parsers' views of
        the same page. The fetch facts move out from under it instead.
        """
        source = inspect.getsource(ContentExtractor._merge_extraction_results)
        assert "target[field] = source_value" in source
