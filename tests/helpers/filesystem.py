"""Helpers for constructing temporary filesystem layouts in tests."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, TypeAlias, Union

import pytest

FileWriter = Callable[[Path], Any]
StructurePayload: TypeAlias = Union[
    Mapping[str, "StructurePayload"],
    bytes,
    None,
    FileWriter,
    Any,
]
FilesystemStructure = Mapping[str, StructurePayload]


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _render_payload(
    path: Path, payload: StructurePayload, *, encoding: str
) -> None:
    if payload is None:
        path.mkdir(parents=True, exist_ok=True)
        return

    if isinstance(payload, dict):
        path.mkdir(parents=True, exist_ok=True)
        build_filesystem(path, payload, encoding=encoding)
        return

    if isinstance(payload, bytes):
        _ensure_parent(path)
        path.write_bytes(payload)
        return

    if callable(payload):
        _ensure_parent(path)
        payload(path)
        return

    _ensure_parent(path)
    path.write_text(str(payload), encoding=encoding)


def build_filesystem(
    base_path: Path,
    structure: FilesystemStructure,
    *,
    encoding: str = "utf-8",
) -> Path:
    """Materialise ``structure`` under ``base_path``.

    ``structure`` is a nested mapping where keys are relative filesystem paths
    and values describe what should be created:

    - ``dict``: creates a directory and recurses into it
    - ``None``: creates an empty directory
    - ``bytes``: writes binary file content
    - ``callable``: invoked with the target path for custom behaviour
    - everything else: converted to ``str`` and written as text
    """

    for name, payload in structure.items():
        target = base_path / name
        _render_payload(target, payload, encoding=encoding)

    return base_path


@pytest.fixture
def filesystem_builder(tmp_path):
    """Fixture that yields a helper to construct filesystem structures."""

    def _build(
        structure: FilesystemStructure, *, encoding: str = "utf-8"
    ) -> Path:
        return build_filesystem(tmp_path, structure, encoding=encoding)

    return _build
