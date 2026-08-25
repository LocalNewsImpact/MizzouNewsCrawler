"""The pre-push hook, run rather than read.

Four times now the hook has refused pushes that were fine, and three of
those failures shared a shape: an environment assumption that held in the
primary checkout and nowhere else, failing later and blaming something
else. Reading the script did not catch any of them, and neither did review
-- the most recent was an assignment placed below the block that reads it,
where both lines are individually correct and only their order is wrong.

So these tests generate the hook the way a developer does, put it in a
scratch repository, and run it. They stop before the expensive steps: what
has broken repeatedly is environment resolution in the first seconds, not
the test suites, and a test that needed Docker and a full pytest run would
be skipped in exactly the situations that matter.
"""

import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP_HOOKS = REPO_ROOT / "scripts" / "setup-hooks.sh"


def _hook_body() -> str:
    """The hook exactly as scripts/setup-hooks.sh writes it."""
    script = SETUP_HOOKS.read_text()
    match = re.search(
        r"cat > \"\$REPO_ROOT/\.git/hooks/pre-push\" << 'EOF'\n(.*?)\nEOF\n",
        script,
        re.S,
    )
    assert match, "the heredoc that writes the hook was not found"
    return match.group(1)


def test_the_hook_is_valid_shell():
    body = _hook_body()
    result = subprocess.run(["bash", "-n"], input=body, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_every_variable_is_assigned_before_it_is_read():
    """The failure that shipped: VENV_DIR="$REPO_ROOT/.venv" sat sixty lines
    above the assignment of REPO_ROOT, so it expanded to "/.venv" and the
    hook refused every push. Unset variables are the recurring shape, so
    this checks the whole hook rather than that one pair."""
    body = _hook_body()
    assigned: set[str] = set()
    problems: list[str] = []
    for lineno, line in enumerate(body.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        # Only BARE reads count. "${VAR:-default}", "${VAR:=x}" and
        # "${VAR+x}" are how a script reads optional external input
        # deliberately, and flagging them would make this test noise.
        bare = re.findall(
            r"\$(?:\{([A-Z][A-Z0-9_]{2,})\}|([A-Z][A-Z0-9_]{2,})\b)", line
        )
        for braced, plain in bare:
            name = braced or plain
            if name in assigned or name in os.environ:
                continue
            # Set by git when it invokes the hook, or by the shell itself.
            if name in {"PATH", "HOME", "PWD", "SHELL", "PIPESTATUS", "EOF"}:
                continue
            problems.append(f"line {lineno}: ${name} read before assignment")
        for name in re.findall(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]{2,})=", line):
            assigned.add(name)
        for name in re.findall(r"^\s*read\s+(?:-r\s+)?([A-Z][A-Z0-9_]{2,})", line):
            assigned.add(name)
    assert not problems, "\n".join(problems)


@pytest.mark.skipif(
    subprocess.run(["which", "git"], capture_output=True).returncode != 0,
    reason="git is required to build a scratch repository",
)
def test_the_hook_resolves_its_environment_in_a_fresh_checkout(tmp_path):
    """Install the hook the way a developer does and run it far enough to
    prove it found the repository, the virtualenv and the tooling.

    The hook is stopped before its first expensive step: reaching that step
    is the assertion. Every failure of this class has happened in the
    seconds before it."""
    scratch = tmp_path / "checkout"
    scratch.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=scratch, check=True)
    (scratch / ".venv" / "bin").mkdir(parents=True)
    # A virtualenv the hook can find, whose python answers the tooling check.
    stub = scratch / ".venv" / "bin" / "python"
    stub.write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        '  *"ruff --version"*) echo "ruff 0.0.0-stub"; exit 0 ;;\n'
        "  *) exit 0 ;;\n"
        "esac\n"
    )
    stub.chmod(0o755)

    hook_path = scratch / ".git" / "hooks" / "pre-push"
    hook_path.write_text(_hook_body())
    hook_path.chmod(0o755)

    # Stop at the first heavy step; reaching it is what is being asserted.
    marker = "PREPUSH_REACHED_FIRST_STEP"
    body = hook_path.read_text().replace(
        "python -m ruff check .",
        f'echo "{marker}"; exit 0; python -m ruff check .',
        1,
    )
    hook_path.write_text(body)

    result = subprocess.run(
        ["bash", str(hook_path), "origin", "https://example.invalid/repo.git"],
        cwd=scratch,
        input="refs/heads/main abc123 refs/heads/main def456\n",
        text=True,
        capture_output=True,
        timeout=120,
    )
    combined = result.stdout + result.stderr

    assert "No virtualenv found" not in combined, (
        "the hook could not find the virtualenv it was given:\n" + combined
    )
    assert "/.venv" not in combined, (
        "the hook resolved a path from an unset variable:\n" + combined
    )
    assert marker in combined or result.returncode == 0, (
        "the hook did not reach its first step:\n" + combined
    )
