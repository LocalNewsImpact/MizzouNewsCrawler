"""Housekeeping fetches credentialed hosts too, in a pass of their own.

`news-housekeeping` already carries a record from a review decision all the way
through: extract, then classify, then enrich, each selecting by status. Its
extraction step was a separate definition from the pipeline's and never gained
`worker-pool`, so it resolved to `mixed` -- and a credentialed link in the rework
queue would be fetched by a worker recycling its driver every few fetches,
signing in on nearly every visit, unwatched.

`docs/AN_AUTHENTICATED_WORKER_IS_PROVISIONED.md` recorded that gap and named the
trigger for fixing it: "the first review decision that rewinds a paywalled
article". That happened on 2026-09-20 -- yakimaherald's three damaged rows were
rewound, and the WSU rework plan rewinds 38 more.

Two decisions this pins, because both are easy to undo by accident:

A SECOND PASS, not a `mixed` one. One worker cannot serve both kinds of host. An
anonymous host needs its driver rotated every few fetches so a publisher cannot
fingerprint one machine working steadily through its site; a credentialed host
needs the driver HELD or every visit pays a fresh login. Running the pass as
`anonymous` instead would be worse than `mixed`: the queue's `requires_login=False`
is an assertion rather than an absent filter, so credentialed rework would be
claimable by nobody at all.

SEQUENTIAL. Two authenticated workers on one host mean two concurrent sessions
for one subscriber account, and no publisher here has been asked whether that is
tolerated -- the same unknown that keeps the standalone authenticated worker count
at 1.

And the pool is a FLAG, not an env var, which is not a style choice:
`extraction-step` DEFINES the `&db_env` anchor that `classify-step` and
`enrich-step` alias, so an input-referencing entry in that list hands the
reference to templates that cannot resolve it. The file already carries a comment
saying that made the workflow unsubmittable once.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.utils.worker_pool import (
    ANONYMOUS,
    AUTHENTICATED,
    ENV_VAR,
    MIXED,
    POOLS,
    announce_pool,
    worker_pool,
)

yaml = pytest.importorskip("yaml")

MANIFEST = Path("k8s/argo/housekeeping-workflow.yaml")


@pytest.fixture(scope="module")
def spec() -> dict:
    return yaml.safe_load(MANIFEST.read_text())["spec"]


@pytest.fixture(scope="module")
def templates(spec) -> dict:
    return {t["name"]: t for t in spec["templates"]}


@pytest.fixture(scope="module")
def step_groups(templates) -> list[list[dict]]:
    return templates["housekeeping"]["steps"]


def _group_index(step_groups, name: str) -> int:
    for i, group in enumerate(step_groups):
        if any(s["name"] == name for s in group):
            return i
    raise AssertionError(f"no step named {name}")


def _args(step: dict) -> dict:
    return {p["name"]: p.get("value") for p in step["arguments"]["parameters"]}


def _step(step_groups, name: str) -> dict:
    for group in step_groups:
        for s in group:
            if s["name"] == name:
                return s
    raise AssertionError(f"no step named {name}")


class TestThereAreTwoPasses:
    def test_both_extraction_passes_exist(self, step_groups):
        assert _step(step_groups, "extract")
        assert _step(step_groups, "extract-credentialed")

    def test_the_anonymous_pass_says_anonymous(self, step_groups):
        assert _args(_step(step_groups, "extract"))["worker-pool"] == ANONYMOUS

    def test_the_credentialed_pass_says_authenticated(self, step_groups):
        step = _step(step_groups, "extract-credentialed")
        assert _args(step)["worker-pool"] == AUTHENTICATED

    def test_neither_is_mixed(self, step_groups):
        """`mixed` picks one driver policy and is wrong for the other half."""
        for name in ("extract", "extract-credentialed"):
            assert _args(_step(step_groups, name))["worker-pool"] != MIXED

    def test_both_use_the_same_template(self, step_groups):
        """One definition, two callers -- not a second copy to drift from."""
        for name in ("extract", "extract-credentialed"):
            assert _step(step_groups, name)["template"] == "extraction-step"


class TestTheyRunInOrderAndAlone:
    def test_the_credentialed_pass_is_its_own_step_group(self, step_groups):
        """Sequential, not parallel: one session per subscriber account."""
        assert _group_index(step_groups, "extract") != _group_index(
            step_groups, "extract-credentialed"
        )

    def test_it_runs_after_the_anonymous_pass(self, step_groups):
        assert _group_index(step_groups, "extract") < _group_index(
            step_groups, "extract-credentialed"
        )

    def test_it_is_not_fanned_out_over_workers(self, step_groups):
        """`withParam` would start one authenticated worker per list entry.

        The anonymous pass does fan out, deliberately. This one must not, for the
        same reason it is sequential.
        """
        assert "withParam" not in _step(step_groups, "extract-credentialed")
        assert "withParam" in _step(step_groups, "extract")

    def test_classification_and_enrichment_follow_both_passes(self, step_groups):
        """A record fetched by the credentialed pass must still be carried on.

        If classify ran before it, a paywalled article refetched tonight would
        wait a whole day for a label -- and the point of housekeeping is that a
        review decision completes in one run.
        """
        last_extract = _group_index(step_groups, "extract-credentialed")
        assert last_extract < _group_index(step_groups, "classify")
        assert _group_index(step_groups, "classify") < _group_index(
            step_groups, "enrich"
        )

    def test_both_passes_are_gated_on_something_being_owed(self, step_groups):
        """An empty rework table must not start a browser at all."""
        for name in ("extract", "extract-credentialed"):
            assert "anything-owed" in _step(step_groups, name)["when"]


class TestThePoolIsAFlagNotAnEnvVar:
    def test_the_template_declares_it_as_an_input(self, templates):
        names = [
            p["name"] for p in templates["extraction-step"]["inputs"]["parameters"]
        ]
        assert "worker-pool" in names

    def test_it_has_no_default(self, templates):
        """The file's own convention: a caller that passes nothing must not look
        correct. `classify-step` failing at submit is why."""
        for p in templates["extraction-step"]["inputs"]["parameters"]:
            if p["name"] == "worker-pool":
                assert "value" not in p and "default" not in p

    def test_the_command_passes_it_through(self, templates):
        command = templates["extraction-step"]["container"]["command"]
        assert "--worker-pool" in command
        assert "{{inputs.parameters.worker-pool}}" in command

    def test_the_shared_env_anchor_is_not_touched(self, templates):
        """The constraint that made this a flag.

        `extraction-step` defines `&db_env`; `classify-step` and `enrich-step`
        alias it. An entry referencing `inputs.parameters.worker-pool` in that
        list would be handed to templates that cannot resolve it.
        """
        for name in ("extraction-step", "classify-step", "enrich-step"):
            env = templates[name]["container"].get("env") or []
            assert not any(e.get("name") == ENV_VAR for e in env)

    def test_every_caller_supplies_it(self, step_groups, templates):
        """A required input with a caller that omits it is unsubmittable."""
        required = {
            p["name"]
            for p in templates["extraction-step"]["inputs"]["parameters"]
            if "value" not in p and "default" not in p
        }
        for group in step_groups:
            for step in group:
                if step.get("template") == "extraction-step":
                    assert required <= set(_args(step))

    def test_the_value_is_a_real_pool(self, step_groups):
        for name in ("extract", "extract-credentialed"):
            assert _args(_step(step_groups, name))["worker-pool"] in POOLS


class TestAnnouncePool:
    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch):
        monkeypatch.delenv(ENV_VAR, raising=False)

    def test_it_sets_the_pool(self):
        assert announce_pool(AUTHENTICATED) == AUTHENTICATED
        assert worker_pool() == AUTHENTICATED

    @pytest.mark.parametrize("value", [" Authenticated ", "ANONYMOUS", "mixed"])
    def test_it_is_case_and_space_insensitive(self, value):
        assert announce_pool(value) == value.strip().lower()

    def test_an_empty_value_leaves_the_environment_alone(self, monkeypatch):
        """So an unset Argo parameter does not silently change the pool."""
        monkeypatch.setenv(ENV_VAR, AUTHENTICATED)
        assert announce_pool(None) == AUTHENTICATED
        assert announce_pool("") == AUTHENTICATED

    def test_an_unrecognised_value_does_not_override(self, monkeypatch):
        monkeypatch.setenv(ENV_VAR, AUTHENTICATED)
        assert announce_pool("nonsense") == AUTHENTICATED

    def test_with_nothing_set_at_all_it_is_mixed(self):
        """The historical behaviour, and the documented default."""
        assert announce_pool(None) == MIXED

    def test_it_reports_the_pool_actually_in_force(self):
        """Returns what `worker_pool()` will say, not what it was handed."""
        assert announce_pool("nonsense") == worker_pool()


class TestTheExtractCommandTakesIt:
    def test_the_flag_exists_and_is_constrained(self):
        import argparse

        from src.cli.commands.extraction import add_extraction_parser

        parser = argparse.ArgumentParser()
        add_extraction_parser(parser.add_subparsers(dest="command"))
        args = parser.parse_args(["extract", "--worker-pool", AUTHENTICATED])
        assert args.worker_pool == AUTHENTICATED

    def test_it_defaults_to_none_so_the_environment_still_decides(self):
        import argparse

        from src.cli.commands.extraction import add_extraction_parser

        parser = argparse.ArgumentParser()
        add_extraction_parser(parser.add_subparsers(dest="command"))
        assert parser.parse_args(["extract"]).worker_pool is None

    def test_an_invalid_pool_is_refused_at_the_command_line(self):
        import argparse

        from src.cli.commands.extraction import add_extraction_parser

        parser = argparse.ArgumentParser()
        add_extraction_parser(parser.add_subparsers(dest="command"))
        with pytest.raises(SystemExit):
            parser.parse_args(["extract", "--worker-pool", "nonsense"])

    def test_the_pool_is_announced_before_anything_reads_it(self):
        """Order matters: `ContentExtractor` reads the driver reuse limit from the
        pool, and the queue request reads it again. Announcing it late would leave
        a worker asking for credentialed hosts while recycling every three
        fetches."""
        import inspect

        from src.cli.commands import extraction

        source = inspect.getsource(extraction.handle_extraction_command)
        body = "\n".join(
            line for line in source.splitlines() if not line.strip().startswith("#")
        )
        assert "announce_pool(" in body
        assert body.index("announce_pool(") < body.index("extractor_cls")
