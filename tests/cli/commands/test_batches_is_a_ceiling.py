"""`--batches N` stops `extract` after N batches, whatever else is set.

It used to apply only together with `--no-exhaust-queue`, which defaults off
and which no manifest passes. On 2026-10-14 an authenticated-extraction run
submitted with `batches=1` to test one Cascadia article finished its batch,
started batch 2, and claimed and logged in to ptleader.com -- a host the test
had not meant to touch.

The queue here never runs dry, so the batch ceiling is the only thing that can
end the run.
"""

from argparse import Namespace

import pytest

from src.cli.commands import extraction


@pytest.fixture
def endless_queue(monkeypatch):
    calls = {"process": 0}

    class FakeExtractor:
        def get_driver_stats(self):
            return {"has_persistent_driver": False}

        def close_persistent_driver(self):
            return None

    class FakeTelemetry:
        def record_extraction(self, *_args, **_kwargs):
            return None

    def fake_process(*_args, **_kwargs):
        calls["process"] += 1
        if calls["process"] > 10:
            # Past any ceiling under test: fail rather than loop forever.
            raise RuntimeError("extract ran past its batch ceiling")
        return {
            "processed": 1,
            "domains_processed": ["example.com"],
            "same_domain_consecutive": 0,
        }

    monkeypatch.setattr(extraction, "ContentExtractor", FakeExtractor)
    monkeypatch.setattr(extraction, "BylineCleaner", lambda **_kw: object())
    monkeypatch.setattr(
        extraction,
        "ComprehensiveExtractionTelemetry",
        lambda **_kw: FakeTelemetry(),
    )
    monkeypatch.setattr(extraction, "_process_batch", fake_process)
    monkeypatch.setattr(
        extraction, "_run_post_extraction_cleaning", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        extraction,
        "_analyze_dataset_domains",
        lambda *_a, **_k: {
            "unique_domains": 1,
            "is_single_domain": False,
            "sample_domains": ["example.com"],
        },
    )
    monkeypatch.setattr(extraction.time, "sleep", lambda *_a, **_k: None)
    return calls


@pytest.mark.parametrize("exhaust_queue", [True, False])
@pytest.mark.parametrize("batches", [1, 3])
def test_extract_stops_at_the_batch_ceiling(endless_queue, batches, exhaust_queue):
    args = Namespace(
        batches=batches,
        limit=1,
        source=None,
        dataset=None,
        exhaust_queue=exhaust_queue,
    )

    assert extraction.handle_extraction_command(args) == 0
    assert endless_queue["process"] == batches


def test_the_flag_still_parses_for_existing_callers():
    """`--no-exhaust-queue` is kept so a caller that passes it does not fail."""
    import argparse

    parser = argparse.ArgumentParser()
    extraction.add_extraction_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["extract", "--batches", "1", "--no-exhaust-queue"])
    assert args.batches == 1
