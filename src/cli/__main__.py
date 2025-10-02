"""Module entrypoint for ``python -m src.cli``."""

from __future__ import annotations

from .cli_modular import main

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
