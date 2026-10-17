"""A rewound link is not charged a try for a fetch that never happened.

`spend_attempt` charges a rewound link before its fetch, and three charges
abandon it as `fetch_failed`. A credentialed fetch with no confirmed
session is declined before the page is requested, so charging it spent the
row's tries on the LOGIN: on 2026-10-14 a columbian.com row was charged while
its login hung and the host was refused. The login has its own budget.
"""

from __future__ import annotations

import inspect

from src.cli.commands import extraction
from src.crawler import ContentExtractor
from src.pipeline import refetch


class _Session:
    def __init__(self):
        self.statements: list[str] = []
        self.params: list[dict] = []

    def execute(self, statement, params=None):
        self.statements.append(" ".join(str(statement).split()))
        self.params.append(params)


class TestTheRefund:
    def test_it_gives_back_one_try_never_below_zero(self):
        session = _Session()
        refetch.refund_attempt(session, ["link-1"])
        sql = session.statements[0]
        assert "- 1" in sql and "greatest(" in sql
        assert session.params[0] == {"refetch": "refetch", "link_ids": ["link-1"]}

    def test_only_a_link_still_owed_a_fetch_is_refunded(self):
        session = _Session()
        refetch.refund_attempt(session, ["link-1"])
        assert "cl.status = :refetch" in session.statements[0]

    def test_nothing_to_refund_touches_nothing(self):
        session = _Session()
        refetch.refund_attempt(session, [])
        assert session.statements == []


class TestTheRefusalIsKnown:
    def test_the_flag_is_reset_for_every_article(self):
        source = inspect.getsource(ContentExtractor.extract_content)
        assert "self.refused_without_session = False" in source

    def test_it_is_set_where_the_fetch_is_declined(self):
        source = inspect.getsource(ContentExtractor._extract_with_selenium)
        declined = source.index("no confirmed subscriber session")
        assert source.index("self.refused_without_session = True") > declined

    def test_the_extraction_loop_refunds_a_declined_rewound_link(self):
        source = " ".join(inspect.getsource(extraction).split())
        assert (
            'getattr(extractor, "refused_without_session", False) is True'
        ) in source
        assert (
            "from src.pipeline.refetch import refund_attempt "
            "refund_attempt(session, [str(url_id)])"
        ) in source
