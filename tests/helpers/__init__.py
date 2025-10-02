"""Shared testing helpers and fixtures for the NewsCrawler test suite."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Dict, Tuple

__all__ = [
    "create_sqlite_db",
    "sqlite_builder",
    "build_filesystem",
    "FakeSpacyDoc",
    "FakeSpacyNlp",
    "FakeSpacySpan",
    "FakeStorySniffer",
]


_EXPORTS: dict[str, tuple[str, str]] = {
    "create_sqlite_db": ("tests.helpers.sqlite", "create_sqlite_db"),
    "sqlite_builder": ("tests.helpers.sqlite", "sqlite_builder"),
    "build_filesystem": ("tests.helpers.filesystem", "build_filesystem"),
    "FakeSpacyDoc": ("tests.helpers.externals", "FakeSpacyDoc"),
    "FakeSpacyNlp": ("tests.helpers.externals", "FakeSpacyNlp"),
    "FakeSpacySpan": ("tests.helpers.externals", "FakeSpacySpan"),
    "FakeStorySniffer": ("tests.helpers.externals", "FakeStorySniffer"),
}


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(name)

    module_name, attribute = _EXPORTS[name]
    module = import_module(module_name)
    value = getattr(module, attribute)
    globals()[name] = value
    return value


if TYPE_CHECKING:  # pragma: no cover - import-time hinting only
    from tests.helpers.externals import (  # noqa: F401
        FakeSpacyDoc,
        FakeSpacyNlp,
        FakeSpacySpan,
        FakeStorySniffer,
    )
    from tests.helpers.filesystem import build_filesystem  # noqa: F401
    from tests.helpers.sqlite import (  # noqa: F401
        create_sqlite_db,
        sqlite_builder,
    )
