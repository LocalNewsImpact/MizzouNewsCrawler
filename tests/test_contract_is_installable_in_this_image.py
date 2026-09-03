"""The contract must be fetchable by the image that needs it.

This image is a single stage and installs no git: its apt line is gcc,
g++, libpq-dev, wget, ca-certificates and procps. A `git+https`
requirement cannot be fetched without git, so the build failed at pip
install -- after the requirement had already been merged.

Adding git would ship it to the runtime image for the sake of one
build-time fetch. datadesk installs the same tag over git+https because its
build is multi-stage and git never leaves the builder; this one uses the
release tarball, which needs nothing.
"""

from pathlib import Path

import pytest

REQUIREMENTS = Path("requirements-base.txt")
DOCKERFILE = Path("Dockerfile.base")


def _requirement_lines():
    return [
        line.strip()
        for line in REQUIREMENTS.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def test_no_requirement_needs_git_unless_the_image_has_it():
    """The defect this pins. A git dependency and no git is a build that
    fails, and it failed only after merge because nothing checked."""
    image_has_git = "procps git" in DOCKERFILE.read_text()
    git_requirements = [
        line
        for line in _requirement_lines()
        if line.startswith("git+") or " @ git+" in line
    ]
    assert (
        image_has_git or not git_requirements
    ), f"these need git, which this image does not install: {git_requirements}"


def test_the_contract_is_pinned_to_a_tag():
    """Never a branch: a shape must not change under a test run."""
    line = next(
        line for line in _requirement_lines() if line.startswith("lnic-contracts")
    )
    assert "/v" in line or "@v" in line


@pytest.mark.parametrize("archive", ["refs/tags/"])
def test_the_contract_comes_from_a_tagged_archive(archive):
    line = next(
        line for line in _requirement_lines() if line.startswith("lnic-contracts")
    )
    assert archive in line
