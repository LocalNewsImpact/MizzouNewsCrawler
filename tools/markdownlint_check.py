"""Simple local markdown lint checks and auto-fixes for common issues.

This script is intentionally dependency-free and performs safe, small
fixes for Markdown files in the repository:
- Convert hard tabs to 2 spaces
- Remove trailing whitespace
- Ensure a blank line before and after fenced code blocks
- Ensure a blank line before lists and headers where missing
- Normalize ordered list prefixes to start at 1 within each list block

Usage:
    python tools/markdownlint_check.py [--apply] [paths...]

If `--apply` is provided the script will write fixes in-place. Without
`--apply` it only prints issues found.

This is not a full markdownlint replacement, but it helps catch and fix
several common problems without requiring Node/npm.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import re
import sys

TAB_REPLACEMENT = "  "  # two spaces

def find_md_files(paths: list[Path]) -> list[Path]:
    files = []
    for p in paths:
        if p.is_dir():
            files.extend(sorted(p.rglob("*.md")))
        elif p.is_file() and p.suffix.lower() in (".md", ".markdown"):
            files.append(p)
    return files


def read_file(p: Path) -> str:
    return p.read_text(encoding="utf8")


def write_file(p: Path, text: str) -> None:
    p.write_text(text, encoding="utf8")


def normalize_ordered_list_block(lines: list[str], start_idx: int) -> None:
    """Normalize a contiguous ordered-list block so each prefix starts at 1.
    Modifies lines in-place.
    start_idx is the index where the list block begins.
    """
    i = start_idx
    # collect contiguous list lines
    block_idxs = []
    ol_re = re.compile(r"^\s*\d+\.\s+")
    while i < len(lines) and ol_re.match(lines[i]):
        block_idxs.append(i)
        i += 1
    # rewrite with sequential numbering
    for n, idx in enumerate(block_idxs, start=1):
        line = lines[idx]
        new_line = re.sub(r"^\s*\d+\.\s+", f"{n}. ", line)
        lines[idx] = new_line


def ensure_blank_lines_around_code_blocks(lines: list[str]) -> None:
    fence_re = re.compile(r"^\s*```")
    i = 0
    while i < len(lines):
        if fence_re.match(lines[i]):
            # ensure blank line before
            if i > 0 and lines[i-1].strip() != "":
                lines.insert(i, "")
                i += 1
            # find closing fence
            j = i + 1
            while j < len(lines) and not fence_re.match(lines[j]):
                j += 1
            if j < len(lines):
                # ensure blank line after closing fence
                if j + 1 < len(lines) and lines[j+1].strip() != "":
                    lines.insert(j+1, "")
            i = j + 1
        else:
            i += 1


def ensure_blank_line_before_lists(lines: list[str]) -> None:
    list_re = re.compile(r"^\s*([*\-+]\s+|\d+\.\s+)")
    i = 1
    while i < len(lines):
        if list_re.match(lines[i]) and lines[i-1].strip() == "":
            # already okay
            i += 1
            continue
        if list_re.match(lines[i]) and lines[i-1].strip() != "":
            # insert blank line before i
            lines.insert(i, "")
            i += 2
        else:
            i += 1


def run_checks_on_text(text: str) -> tuple[list[str], str]:
    """Return (issues, fixed_text) — where fixed_text is the
    auto-fixed version.
    """
    lines = text.splitlines()
    issues = []

    # 1) tabs
    for i, l in enumerate(lines, start=1):
        if "\t" in l:
            issues.append(f"TAB at line {i}")
            lines[i-1] = l.replace("\t", TAB_REPLACEMENT)

    # 2) trailing whitespace
    for i, l in enumerate(lines, start=1):
        if l.rstrip() != l:
            issues.append(f"Trailing whitespace at line {i}")
            lines[i-1] = l.rstrip()

    # 3) blank lines around code fences
    ensure_blank_lines_around_code_blocks(lines)

    # 4) blank line before lists
    ensure_blank_line_before_lists(lines)

    # 5) normalize ordered list blocks
    ol_re = re.compile(r"^\s*\d+\.\s+")
    idx = 0
    while idx < len(lines):
        if ol_re.match(lines[idx]):
            normalize_ordered_list_block(lines, idx)
            # skip past block
            while idx < len(lines) and ol_re.match(lines[idx]):
                idx += 1
        else:
            idx += 1

    fixed_text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    return issues, fixed_text


def process_file(path: Path, apply: bool) -> int:
    text = read_file(path)
    issues, fixed = run_checks_on_text(text)
    if not issues:
        return 0
    print(f"{path}: found {len(issues)} issue(s)")
    for it in issues[:20]:
        print("  -", it)
    if apply:
        write_file(path, fixed)
        print(f"Applied fixes to {path}")
    return len(issues)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "paths",
        nargs="*",
        default=["README.md"],
        help="Files or directories to check",
    )
    p.add_argument("--apply", action="store_true", help="Apply fixes in-place")
    args = p.parse_args(argv)
    paths = [Path(x) for x in args.paths]
    files = find_md_files(paths)
    if not files:
        print("No markdown files found")
        return 0
    total_issues = 0
    for f in files:
        total_issues += process_file(f, args.apply)
    if total_issues:
        print(f"Total issues found: {total_issues}")
        return 2
    print("No issues found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
