"""The deploy must apply the repo's template, not re-edit the cluster's copy.

Deploys used to read the live WorkflowTemplate, change only its image tags,
and write it back. Everything else in k8s/argo/base-pipeline-workflow.yaml was
therefore unreachable: the cluster copy was seeded by hand and drifted
indefinitely. On 2026-07-26 it still carried an extraction-worker cap of 10 --
superseded months earlier -- and lacked MIZZOU_SQUID_PROXY_URL, so the second
proxy was unreachable and a validation run spawned 10 workers instead of 2.

These tests pin the two properties that matter: repo content reaches the
cluster, and a deploy of one service never rolls another one back.
"""

import pathlib

import pytest
import yaml

from scripts.render_workflow_template import (
    KNOWN_SERVICES,
    apply_tags,
    main,
    parse_live_tags,
)

REPO_TEMPLATE = pathlib.Path("k8s/argo/base-pipeline-workflow.yaml")

TEMPLATE_SNIPPET = """\
apiVersion: argoproj.io/v1alpha1
kind: WorkflowTemplate
spec:
  templates:
    - name: discovery-step
      container:
        image: us-central1-docker.pkg.dev/proj/repo/crawler:OLD
        env:
          - name: MIZZOU_SQUID_PROXY_URL
            value: keep-me
    - name: extraction-step
      container:
        image: us-central1-docker.pkg.dev/proj/repo/crawler:OLD
    - name: wait-for-candidates
      container:
        image: us-central1-docker.pkg.dev/proj/repo/processor:OLD
"""

LIVE_JSON = """{
  "spec": {"templates": [
    {"container": {"image": "us-central1-docker.pkg.dev/proj/repo/crawler:LIVECRAWL"}},
    {"container": {"image": "us-central1-docker.pkg.dev/proj/repo/processor:LIVEPROC"}}
  ]}
}"""


class TestParseLiveTags:
    def test_reads_tags_per_service(self):
        assert parse_live_tags(LIVE_JSON) == {
            "crawler": "LIVECRAWL",
            "processor": "LIVEPROC",
        }

    def test_malformed_json_is_not_fatal(self):
        """A cluster read that returns junk must not break the deploy."""
        assert parse_live_tags("not json") == {}
        assert parse_live_tags("") == {}

    def test_ignores_unknown_services(self):
        other = '{"spec":{"templates":[{"container":{"image":"reg/redis:7"}}]}}'
        assert parse_live_tags(other) == {}


class TestApplyTags:
    def test_deployed_service_gets_this_builds_sha(self):
        out, applied = apply_tags(TEMPLATE_SNIPPET, "crawler", "NEWSHA", {})
        assert "crawler:NEWSHA" in out
        assert applied["crawler"] == ("NEWSHA", 2)

    def test_other_services_keep_their_live_tag(self):
        """A crawler deploy must not roll the processor back to the repo's
        tag -- those lag, because a separate job maintains them."""
        out, applied = apply_tags(
            TEMPLATE_SNIPPET, "crawler", "NEWSHA", {"processor": "LIVEPROC"}
        )
        assert "processor:LIVEPROC" in out
        assert "processor:OLD" not in out
        assert applied["processor"] == ("LIVEPROC", 1)

    def test_service_neither_built_nor_live_keeps_repo_value(self):
        out, applied = apply_tags(TEMPLATE_SNIPPET, "crawler", "NEWSHA", {})
        assert "processor:OLD" in out
        assert "processor" not in applied

    def test_repo_content_survives_substitution(self):
        """THE regression: everything other than tags must reach the cluster."""
        out, _ = apply_tags(TEMPLATE_SNIPPET, "crawler", "NEWSHA", {})
        assert "MIZZOU_SQUID_PROXY_URL" in out
        assert "keep-me" in out

    def test_output_is_still_valid_yaml(self):
        out, _ = apply_tags(TEMPLATE_SNIPPET, "crawler", "NEWSHA", {})
        doc = yaml.safe_load(out)
        assert doc["kind"] == "WorkflowTemplate"

    def test_unknown_service_substitutes_nothing(self):
        out, applied = apply_tags(TEMPLATE_SNIPPET, "nosuch", "NEWSHA", {})
        assert applied == {}
        assert out == TEMPLATE_SNIPPET


@pytest.mark.skipif(not REPO_TEMPLATE.exists(), reason="repo template not present")
class TestAgainstTheRealTemplate:
    """Guard the specific content that was found missing in production."""

    def test_real_template_renders_and_keeps_its_content(self):
        rendered, applied = apply_tags(
            REPO_TEMPLATE.read_text(),
            "crawler",
            "abc1234",
            {"processor": "613a942"},
        )

        assert applied["crawler"][0] == "abc1234"
        assert applied["processor"][0] == "613a942"
        # The two settings that had silently failed to reach production.
        assert rendered.count("MIZZOU_SQUID_PROXY_URL") >= 1
        assert "min(2, max(2" in rendered
        assert all(
            isinstance(d, (dict, type(None))) for d in yaml.safe_load_all(rendered)
        )

    def test_every_known_service_reference_is_taggable(self):
        text = REPO_TEMPLATE.read_text()
        for svc in KNOWN_SERVICES:
            if f"/{svc}:" not in text:
                continue
            rendered, applied = apply_tags(text, svc, "ZZZ", {})
            assert applied[svc][1] >= 1, f"{svc} references were not substituted"


class TestMainDoesNotTouchClusterOnFailure:
    def test_missing_template_exits_nonzero(self, capsys):
        rc = main(["crawler", "SHA", "--template", "does/not/exist.yaml"])
        assert rc == 1
        assert "Cannot read" in capsys.readouterr().out

    def test_print_only_never_calls_kubectl(self, monkeypatch, tmp_path, capsys):
        """--print-only is the safe way to inspect a render."""
        import scripts.render_workflow_template as mod

        monkeypatch.setattr(
            mod,
            "kubectl_apply",
            lambda *a, **k: pytest.fail("must not touch the cluster"),
        )
        monkeypatch.setattr(
            mod, "fetch_live_tags", lambda: pytest.fail("must not read cluster")
        )
        path = tmp_path / "tpl.yaml"
        path.write_text(TEMPLATE_SNIPPET)

        rc = main(["crawler", "NEWSHA", "--template", str(path), "--print-only"])

        assert rc == 0
        assert "crawler:NEWSHA" in capsys.readouterr().out

    def test_validation_failure_aborts_before_real_apply(self, monkeypatch, tmp_path):
        """The server-side dry run must gate the real apply, so a malformed
        template fails the build instead of half-applying."""
        import scripts.render_workflow_template as mod

        calls = []

        def fake_apply(rendered, dry_run):
            calls.append(dry_run)
            return (1, "", "invalid template") if dry_run else (0, "ok", "")

        monkeypatch.setattr(mod, "fetch_live_tags", dict)
        monkeypatch.setattr(mod, "kubectl_apply", fake_apply)
        path = tmp_path / "tpl.yaml"
        path.write_text(TEMPLATE_SNIPPET)

        rc = main(["crawler", "NEWSHA", "--template", str(path)])

        assert rc == 1
        assert calls == [True], "real apply must not run after a failed dry run"
