#!/usr/bin/env python3
"""Assert a built image actually contains its declared dependencies.

Service images build ``FROM`` the base image, so a dependency added to
requirements-base.txt only reaches them once the base has been rebuilt AND the
dependent build pulls that new base. When those race, the dependent image is
built on the *previous* base — the build still reports SUCCESS, the image ships
missing a package, and the failure only surfaces at runtime in whatever code
imported it.

That is exactly what happened on 2026-07-20: two merges a minute apart raced,
crawler shipped without google-cloud-storage, and the raw-HTML archive silently
no-opped in production for hours because it is (correctly) fail-soft.

Run this inside the freshly built image, before it is deployed:

    docker run --rm -v "$PWD:/repo:ro" IMAGE \\
        python /repo/scripts/verify_image_dependencies.py \\
        /repo/requirements-base.txt /repo/requirements-crawler.txt

Exits non-zero listing every declared package that is missing or too old, so a
stale-base build fails loudly at build time instead of silently at runtime.
"""

from __future__ import annotations

import sys
from importlib.metadata import PackageNotFoundError, version

try:
    from packaging.requirements import Requirement

    HAVE_PACKAGING = True
except Exception:  # pragma: no cover - image without packaging installed
    HAVE_PACKAGING = False


def _parse(line: str):
    """Return (name, specifier) for a requirement line, or None to skip it."""
    line = line.split("#")[0].strip()
    if not line or line.startswith("-"):
        return None

    if HAVE_PACKAGING:
        try:
            req = Requirement(line)
        except Exception:
            return None
        # Environment markers (e.g. python_version) may legitimately exclude it.
        if req.marker is not None:
            return None
        return req.name, req.specifier

    # Fallback: name only, no version checking.
    for sep in (">=", "==", "<=", "~=", ">", "<", "["):
        if sep in line:
            line = line.split(sep)[0]
    return line.strip(), None


def check(paths: list[str]) -> int:
    missing: list[str] = []
    stale: list[str] = []
    checked = 0

    for path in paths:
        try:
            lines = open(path).read().splitlines()
        except OSError as exc:
            print(f"::error::cannot read {path}: {exc}")
            return 2

        for line in lines:
            parsed = _parse(line)
            if not parsed:
                continue
            name, spec = parsed
            try:
                installed = version(name)
            except PackageNotFoundError:
                missing.append(f"{name} (declared in {path})")
                continue
            except Exception:
                continue
            checked += 1
            if spec is not None and not spec.contains(installed, prereleases=True):
                stale.append(f"{name}{spec} but image has {installed} ({path})")

    print(f"checked {checked} declared dependencies across {len(paths)} file(s)")
    if not HAVE_PACKAGING:
        print("note: `packaging` unavailable — presence checked, versions not")

    if missing:
        print(f"\n❌ {len(missing)} declared dependency(ies) MISSING from image:")
        for m in missing:
            print(f"   - {m}")
        print(
            "\nThis usually means the image was built on a stale base image "
            "(a dependent build raced a base rebuild). Rebuild it after the "
            "base image has finished pushing."
        )
    if stale:
        print(f"\n❌ {len(stale)} dependency(ies) below the declared floor:")
        for s in stale:
            print(f"   - {s}")

    if missing or stale:
        return 1

    print("✅ image satisfies all declared dependencies")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        print("usage: verify_image_dependencies.py REQUIREMENTS [REQUIREMENTS ...]")
        return 2
    return check(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
