"""The deploy rebuilds an image when what goes into it changes.

build-and-deploy-services.yml decides which images to rebuild by matching
the pushed paths against one pattern per image. The patterns were written
by hand, apart from the Dockerfiles, and drifted three times: #423
(2026-07-26) touched only src/cli/ and src/reporting/ and built nothing;
#453 (2026-08-12) touched only src/crawler/ and left the processor on the
previous commit's crawler code while the deploy reported success; and
after both were added, src/mcmetadata/ -- the extraction parser --
src/config.py, src/telemetry/ and src/lookups/ still matched nothing.

Each Dockerfile already says what its image contains. These read that,
and hold each pattern to it: every tracked path an image copies matches
the pattern that rebuilds it. The migrator is the one exception, and it
is held to what alembic/env.py imports instead (see below).
"""

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github/workflows/build-and-deploy-services.yml"
ALEMBIC_ENV = ROOT / "alembic/env.py"

# The workflow's flag for each image, and the Dockerfile that builds it.
IMAGES = {
    "BASE": "Dockerfile.base",
    "ML_BASE": "Dockerfile.ml-base",
    "PROCESSOR": "Dockerfile.processor",
    "API": "Dockerfile.api",
    "CRAWLER": "Dockerfile.crawler",
    "MIGRATOR": "Dockerfile.migrator",
    "ENRICHMENT": "Dockerfile.enrichment",
}

# Paths a push to main routinely carries that must build nothing. If one
# of these matches, the filter has been widened past the images and every
# push rebuilds everything.
NOT_IN_ANY_IMAGE = (
    "README.md",
    "docs/DEPLOYMENT.md",
    "tests/test_something.py",
    ".github/workflows/ci.yml",
    "Makefile",
    "gcp/cloudbuild/cloudbuild-processor.yaml",
)


def _patterns() -> dict[str, str]:
    """Each `grep -qE '<pattern>'` in the workflow, keyed by the flag the
    match sets. The pattern is an ERE; everything these use (alternation,
    groups, escaped dots) means the same to Python's re."""
    found = dict(
        re.findall(
            r"grep -qE '([^']+)'; then\n\s*([A-Z_]+)=true",
            WORKFLOW.read_text(),
        )
    )
    return {flag: pattern for pattern, flag in found.items()}


def _tracked() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout
    return out.splitlines()


def _copied(dockerfile: str) -> list[str]:
    """The sources of every COPY/ADD in the Dockerfile, from the build
    context. `COPY --from=` copies from another stage, not the context."""
    lines = (ROOT / dockerfile).read_text().splitlines()
    joined: list[str] = []
    for line in lines:
        if joined and joined[-1].endswith("\\"):
            joined[-1] = joined[-1][:-1] + " " + line.strip()
        else:
            joined.append(line)
    sources: list[str] = []
    for line in joined:
        words = line.split()
        if not words or words[0] not in ("COPY", "ADD"):
            continue
        if any(w.startswith("--from") for w in words):
            continue
        args = [w for w in words[1:] if not w.startswith("--")]
        sources.extend(args[:-1])
    assert sources, f"{dockerfile} copies nothing?"
    return sources


def _tracked_under(source: str, tracked: list[str]) -> list[str]:
    """Every tracked path a COPY source brings in. A source the repository
    does not track (the model weights Cloud Build fetches itself) cannot
    arrive in a push, so no pattern needs to match it."""
    source = source.rstrip("/")
    return [p for p in tracked if p == source or p.startswith(source + "/")]


def test_every_image_has_a_pattern():
    patterns = _patterns()
    assert set(IMAGES) <= set(patterns), set(IMAGES) - set(patterns)


@pytest.mark.parametrize("flag", [f for f in IMAGES if f != "MIGRATOR"])
def test_everything_an_image_copies_rebuilds_it(flag):
    pattern = re.compile(_patterns()[flag])
    tracked = _tracked()
    unmatched = []
    for source in _copied(IMAGES[flag]):
        for path in _tracked_under(source, tracked):
            if not pattern.search(path):
                unmatched.append(path)
    assert not unmatched, (
        f"{IMAGES[flag]} copies these, and a push touching only them would "
        f"not rebuild it:\n  " + "\n  ".join(sorted(unmatched)[:20])
    )


def test_the_migrator_is_rebuilt_by_what_alembic_imports():
    """The migrator copies src/ whole and runs only what alembic/env.py
    imports from it. Matching all of src/ would rebuild it -- and run the
    migration job against production -- on every code push, so its
    pattern names the imported modules, and this holds it to env.py rather
    than to a list kept by hand."""
    pattern = re.compile(_patterns()["MIGRATOR"])
    tracked = _tracked()
    imported = set(
        re.findall(r"^\s*from (src(?:\.\w+)*) import", ALEMBIC_ENV.read_text(), re.M)
    )
    imported |= set(
        re.findall(r"^\s*import (src(?:\.\w+)*)", ALEMBIC_ENV.read_text(), re.M)
    )
    assert imported, "alembic/env.py no longer imports from src/?"

    unmatched = []
    for module in imported:
        # `from src import config` names the package; the module is the
        # first thing after `src` that exists as a file or a directory.
        parts = module.split(".")[1:]
        if not parts:
            continue
        as_file = "src/" + "/".join(parts) + ".py"
        as_dir = "src/" + "/".join(parts[:1])
        source = as_file if as_file in tracked else as_dir
        for path in _tracked_under(source, tracked):
            if not pattern.search(path):
                unmatched.append(path)
    for source in _copied(IMAGES["MIGRATOR"]):
        if source.rstrip("/") == "src":
            continue
        for path in _tracked_under(source, tracked):
            if not pattern.search(path):
                unmatched.append(path)
    assert not unmatched, "\n  ".join(sorted(set(unmatched))[:20])


def test_the_paths_that_were_missed_are_matched_now():
    """The ones each drift missed, pinned."""
    patterns = {flag: re.compile(p) for flag, p in _patterns().items()}
    for path, flags in {
        "src/cli/commands/extraction.py": ("PROCESSOR", "API", "CRAWLER", "ENRICHMENT"),
        "src/crawler/discovery.py": ("PROCESSOR", "CRAWLER"),
        "src/mcmetadata/content.py": ("PROCESSOR", "CRAWLER"),
        "src/config.py": ("PROCESSOR", "API", "CRAWLER", "MIGRATOR", "ENRICHMENT"),
        "lookups/site_rules.csv": ("CRAWLER",),
        "alembic/env.py": ("API", "MIGRATOR"),
    }.items():
        for flag in flags:
            assert patterns[flag].search(path), f"{path} does not rebuild {flag}"


def test_a_push_that_touches_no_image_builds_nothing():
    patterns = _patterns()
    hits = [
        (path, flag)
        for path in NOT_IN_ANY_IMAGE
        for flag, pattern in patterns.items()
        if re.search(pattern, path)
    ]
    assert not hits, hits
