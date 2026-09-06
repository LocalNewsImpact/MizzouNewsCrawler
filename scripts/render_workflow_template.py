#!/usr/bin/env python3
"""Render the Argo WorkflowTemplate from the repo with image tags applied.

Deploys used to read the LIVE template out of the cluster, rewrite only its
image tags, and push it back -- so nothing else in
k8s/argo/base-pipeline-workflow.yaml could ever reach production. The cluster
copy was seeded once by hand and drifted from the repo indefinitely: on
2026-07-26 it still carried an extraction-worker cap of 10 (superseded months
earlier by 702cd559) and lacked the MIZZOU_SQUID_PROXY_URL env from #416, so
the second proxy was unreachable and a run spawned 10 workers instead of 2.

The rendering lives here, rather than in a shell heredoc, so it can be tested:
this decides what production runs.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

KNOWN_SERVICES: tuple[str, ...] = ("crawler", "processor", "api")

DEFAULT_TEMPLATE = "k8s/argo/base-pipeline-workflow.yaml"
TEMPLATE_NAME = "news-pipeline-template"
NAMESPACE = "production"


def parse_live_tags(template_json: str) -> dict[str, str]:
    """Image tags in a live WorkflowTemplate, keyed by service."""
    tags: dict[str, str] = {}
    try:
        doc = json.loads(template_json)
    except (ValueError, TypeError):
        return tags
    for tmpl in doc.get("spec", {}).get("templates", []):
        image = (tmpl.get("container") or {}).get("image", "")
        match = re.search(r"/([a-z-]+):([\w.-]+)$", image)
        if match and match.group(1) in KNOWN_SERVICES:
            tags[match.group(1)] = match.group(2)
    return tags


def apply_tags(
    rendered: str, service_type: str, new_sha: str, live_tags: dict[str, str]
) -> tuple[str, dict[str, tuple[str, int]]]:
    """Substitute image tags into the repo template.

    The service being deployed takes this build's SHA; every other service
    keeps the tag it is currently running, so a crawler deploy cannot roll the
    processor back to whatever tag the repo file happens to carry. A service
    that is neither built here nor live keeps whatever the repo says -- which
    is now a `${SERVICE_TAG}` placeholder rather than a tag that went stale
    the moment it was written, so that case is caught by
    `unresolved_images` instead of quietly deploying an old image.
    """
    applied: dict[str, tuple[str, int]] = {}
    for svc in KNOWN_SERVICES:
        tag = new_sha if svc == service_type else live_tags.get(svc)
        if not tag:
            continue
        # A literal tag or a `${SERVICE_TAG}` placeholder: the template
        # carries placeholders, and a cluster copy read back carries
        # whatever tag it is running.
        pattern = re.compile(rf"(image:\s*\S*/{svc}):(?:[\w.-]+|\$\{{[A-Z_]+\}})")
        rendered, count = pattern.subn(rf"\g<1>:{tag}", rendered)
        if count:
            applied[svc] = (tag, count)
    return rendered, applied


#: An image line still carrying a placeholder after substitution.
UNRESOLVED = re.compile(r"^\s*image:\s*\S*:\$\{[A-Z_]+\}\s*$", re.M)


def unresolved_images(rendered: str) -> list[str]:
    """Image lines whose tag was never filled in.

    Reaching the cluster with `crawler:${CRAWLER_TAG}` would be an invalid
    reference that the apply may well accept and every pod then fail on.
    The build stops instead: a service neither built nor live has no tag
    anybody has chosen, and guessing one is what the placeholders replaced.
    """
    return [line.strip() for line in UNRESOLVED.findall(rendered)]


def fetch_live_tags() -> dict[str, str]:
    try:
        out = subprocess.run(
            [
                "kubectl",
                "get",
                "workflowtemplate",
                TEMPLATE_NAME,
                "-n",
                NAMESPACE,
                "-o",
                "json",
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        print(
            f"ℹ️  No live template to read ({detail.strip()[:120]}); using repo tags."
        )
        return {}
    return parse_live_tags(out)


def kubectl_apply(rendered: str, dry_run: bool) -> tuple[int, str, str]:
    """Apply the template server-side.

    A client-side `kubectl apply` cannot update this object at all:

        metadata.resourceVersion: Invalid value: 0: must be specified for
        an update

    The rendered manifest carries no resourceVersion (correctly -- it is
    generated from the repo, not read from the cluster), so the client-side
    path demands one and fails every time. Server-side apply resolves the
    merge on the API server and needs no resourceVersion. --force-conflicts
    takes ownership of the fields last written by the old client-side applier,
    which otherwise conflict on every field this manifest sets.
    """
    cmd = ["kubectl", "apply", "--server-side", "--force-conflicts", "-f", "-"]
    if dry_run:
        cmd.append("--dry-run=server")
    proc = subprocess.run(cmd, input=rendered, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service_type", help="crawler | processor | api")
    parser.add_argument("sha", help="image tag produced by this build")
    parser.add_argument("--template", default=DEFAULT_TEMPLATE)
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="render and print without touching the cluster",
    )
    args = parser.parse_args(argv)

    try:
        with open(args.template) as fh:
            rendered = fh.read()
    except OSError as exc:
        print(f"❌ Cannot read {args.template}: {exc}")
        print("   Run from the repository root (the Cloud Build workspace).")
        return 1

    live = {} if args.print_only else fetch_live_tags()
    if live:
        print(
            "   Currently live: "
            + ", ".join(f"{k}:{v}" for k, v in sorted(live.items()))
        )

    rendered, applied = apply_tags(rendered, args.service_type, args.sha, live)
    if not applied:
        print("⚠️  No image references substituted; applying repo file as-is.")
    for svc, (tag, count) in sorted(applied.items()):
        marker = " (this build)" if svc == args.service_type else " (preserved)"
        print(f"  ✓ {svc}:{tag} x{count}{marker}")

    if args.print_only:
        print(rendered)
        return 0

    stranded = unresolved_images(rendered)
    if stranded:
        print("❌ Image tags were never resolved:")
        for line in stranded:
            print(f"   {line}")
        print(
            "   That service was not built here and is not running in the "
            "cluster, so nothing named a tag for it."
        )
        return 1

    # Validate server-side first: a malformed template must fail the build
    # rather than half-apply to production.
    for dry_run in (True, False):
        code, out, err = kubectl_apply(rendered, dry_run=dry_run)
        if code != 0:
            stage = "validation" if dry_run else "apply"
            print(f"❌ Template {stage} failed:\n{err}")
            return 1
        print(out.strip())

    print(f"✅ WorkflowTemplate applied from {args.template}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
