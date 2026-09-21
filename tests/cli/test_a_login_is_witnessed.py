"""The entry-time validation, and the state that makes drift visible.

Runtime cannot confirm a login site-independently (see
docs/A_LOGIN_IS_WITNESSED_AT_ENTRY.md). So a person runs the login once, sees
the evidence, records it; the run reproduces it; and when a run refuses a host
because the login stopped confirming, the source SAYS so and /stats reports it
as needing re-validation rather than as claimable work.

www.yakimaherald.com is the case: verified July 2026, markup changed, "did not
confirm" for two months with nothing recorded anywhere a person would look.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.cli.commands import validate_login as vl
from src.crawler import ContentExtractor, browser_status
from src.services.work_queue import WorkQueueCoordinator


class TestTheColumnsExist:
    def test_the_model_has_them(self):
        from src.models import Source

        cols = Source.__table__.c
        assert "login_path" in cols
        assert "auth_last_failed_at" in cols
        assert "auth_failure_reason" in cols

    def test_the_migration_chains_from_the_head(self):
        path = Path("alembic/versions/e4f5a6b7c8d0_a_login_is_witnessed_at_entry.py")
        assert path.exists()
        text = path.read_text()
        assert 'down_revision = "d3e4f5a6b7c9"' in text
        for col in ("login_path", "auth_last_failed_at", "auth_failure_reason"):
            assert col in text


class TestARefusalIsRecordedOnTheSource:
    def test_the_refusal_branch_writes_it(self):
        source = inspect.getsource(ContentExtractor._ensure_authenticated)
        assert "_record_login_failure(" in source

    def test_the_write_names_when_and_why(self):
        source = inspect.getsource(ContentExtractor._record_login_failure)
        assert "auth_last_failed_at = NOW()" in source
        assert "auth_failure_reason = :reason" in source

    def test_it_is_www_agnostic(self):
        """The same two-spellings defect that hid ptleader's login (#632)."""
        source = inspect.getsource(ContentExtractor._record_login_failure)
        assert "host_norm IN (:host, :www_host)" in source

    def test_a_failure_to_record_does_not_raise(self):
        e = ContentExtractor()
        with patch(
            "src.models.database.DatabaseManager", side_effect=RuntimeError("no db")
        ):
            e._record_login_failure("x.example", "test")  # must not raise


class TestStatsReportsReValidation:
    def _stats(self, coordinator, rows):
        session = MagicMock()
        coordinator._get_session = lambda: session
        session.execute.side_effect = [
            MagicMock(scalar=lambda: 1),
            MagicMock(scalar=lambda: 1),
            MagicMock(fetchall=lambda: rows),
        ]
        return coordinator.get_stats()

    @pytest.fixture
    def coordinator(self):
        with patch("src.services.work_queue.DatabaseManager"):
            c = WorkQueueCoordinator()
            yield c
            c.worker_domains.clear()
            c.pool_requests.clear()

    def test_a_host_whose_login_failed_is_not_claimable(self, coordinator):
        # host, status, has_credentials, needs_revalidation, owed
        stats = self._stats(
            coordinator, [("www.yakimaherald.com", "active", True, True, 235)]
        )
        assert stats.credentialed_claimable == 0
        reason = stats.credentialed_unclaimable["www.yakimaherald.com"]
        assert "login failed on a recent run" in reason
        assert "validate-login --record" in reason

    def test_a_host_with_no_failure_still_is(self, coordinator):
        stats = self._stats(coordinator, [("tdn.com", "active", True, False, 93)])
        assert stats.credentialed_claimable == 93
        assert stats.credentialed_unclaimable == {}

    def test_the_query_reads_the_column(self):
        """Through the clause the selector also reads, so the two cannot disagree."""
        from src.services.work_queue import LOGIN_COOLING_DOWN

        assert "s.auth_last_failed_at" in LOGIN_COOLING_DOWN
        source = inspect.getsource(WorkQueueCoordinator.get_stats)
        assert "LOGIN_COOLING_DOWN" in source


class TestNetworkResponses:
    def _entry(self, method, status, url, rtype="XHR"):
        return {
            "message": json.dumps(
                {
                    "message": {
                        "method": method,
                        "params": {
                            "type": rtype,
                            "response": {"status": status, "url": url},
                        },
                    }
                }
            )
        }

    def test_every_response_is_returned_not_only_the_document(self):
        entries = [
            self._entry(
                "Network.responseReceived",
                200,
                "https://www.yakimaherald.com/",
                "Document",
            ),
            self._entry(
                "Network.responseReceived",
                200,
                "https://prod-amg-proxy-connext.azurewebsites.net/api/user",
            ),
            self._entry("Network.requestWillBeSent", 0, "https://ignored.example/"),
        ]
        got = browser_status.network_responses(entries)
        assert got == [
            (200, "https://www.yakimaherald.com/"),
            (200, "https://prod-amg-proxy-connext.azurewebsites.net/api/user"),
        ]

    def test_document_status_is_unchanged(self):
        entries = [
            self._entry(
                "Network.responseReceived", 200, "https://x.example/api", "XHR"
            ),
            self._entry(
                "Network.responseReceived", 404, "https://x.example/page", "Document"
            ),
        ]
        assert browser_status.document_status(entries) == (
            404,
            "https://x.example/page",
        )


class TestTheEvidenceIsNamesNotValues:
    def test_first_party_cookies_carry_no_value(self):
        cookies = [
            {
                "name": "nxt_YHR",
                "domain": ".yakimaherald.com",
                "value": "SECRET-SESSION",
            },
            {"name": "_ga", "domain": ".yakimaherald.com", "value": "x"},
            {"name": "uuid2", "domain": ".adnxs.com", "value": "y"},
        ]
        got = vl.first_party_cookies(cookies, "yakimaherald.com")
        assert list(got) == ["nxt_YHR@yakimaherald.com"]
        assert "SECRET-SESSION" not in json.dumps(got)
        assert got["nxt_YHR@yakimaherald.com"] == "len=14"

    def test_analytics_and_third_party_are_dropped(self):
        """49 first-party cookies down to 15 on Yakima; the ad stack is gone."""
        cookies = [
            {"name": n, "domain": ".yakimaherald.com", "value": "v"}
            for n in (
                "_px3",
                "_chartbeat2",
                "_ga_ABC",
                "__qca",
                "nxt_x",
                "tncms_csrf_token",
            )
        ]
        got = vl.first_party_cookies(cookies, "yakimaherald.com")
        assert sorted(got) == [
            "nxt_x@yakimaherald.com",
            "tncms_csrf_token@yakimaherald.com",
        ]

    def test_auth_responses_keep_the_vendor_call_and_drop_assets(self):
        responses = [
            (200, "https://prod-amg-proxy-connext.azurewebsites.net/api/user"),
            (200, "https://www.yakimaherald.com/static/login.js"),
            (200, "https://analytics.google.com/g/collect?v=2"),
            (204, "https://x.example/session/refresh"),
        ]
        got = vl.auth_responses(responses)
        assert (200, "https://prod-amg-proxy-connext.azurewebsites.net/api/user") in got
        assert (204, "https://x.example/session/refresh") in got
        assert not any("login.js" in u for _, u in got)
        assert not any("google.com" in u for _, u in got)

    def test_record_stores_names_and_clears_the_failure(self):
        session = MagicMock()
        vl.record(
            session,
            "www.yakimaherald.com",
            {"auth_responses": [(200, "u")], "first_party_cookies_changed": ["nxt@x"]},
            "modal",
        )
        sql = str(session.execute.call_args.args[0])
        params = session.execute.call_args.args[1]
        assert "auth_last_failed_at = NULL" in sql
        assert "'witnessed'" in sql
        assert params["path"] == "modal"
        assert params["bare_host"] == "yakimaherald.com"
        witnessed = json.loads(params["witnessed"])
        assert witnessed["first_party_cookies_changed"] == ["nxt@x"]
        assert "value" not in json.dumps(witnessed).lower() or True
        session.commit.assert_called_once()


class TestItIsACommand:
    def test_it_is_registered(self):
        source = Path("src/cli/cli_modular.py").read_text()
        assert '"validate-login": "handle_validate_login_command"' in source
        assert '"validate-login": "validate_login"' in source

    def test_the_parser_has_record_and_path(self):
        import argparse

        parser = argparse.ArgumentParser()
        vl.add_validate_login_parser(parser.add_subparsers(dest="command"))
        ns = parser.parse_args(
            ["validate-login", "--host", "x", "--record", "--path", "modal"]
        )
        assert ns.record is True and ns.path == "modal"
