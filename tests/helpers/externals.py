"""Test doubles for third-party dependencies used throughout the project."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Mapping, Optional


@dataclass
class FakeSpacySpan:
    """Lightweight spaCy span replacement."""

    text: str
    label_: str
    start_char: int = 0
    end_char: Optional[int] = None

    def __post_init__(self) -> None:  # pragma: no cover - trivial arithmetic
        if self.end_char is None:
            self.end_char = self.start_char + len(self.text)


@dataclass
class FakeSpacyDoc:
    """Minimal spaCy ``Doc`` replacement exposing ``ents``."""

    text: str
    ents: List[FakeSpacySpan]


class FakeSpacyNlp:
    """Callable object emulating spaCy's language pipeline for tests."""

    def __init__(
        self,
        *,
        entities: Mapping[str, Iterable[FakeSpacySpan]] | None = None,
        factory: Callable[[str], Iterable[FakeSpacySpan]] | None = None,
    ) -> None:
        self._entities: Dict[str, List[FakeSpacySpan]] = {
            text: list(spans) for text, spans in (entities or {}).items()
        }
        self._factory = factory
        self.calls: List[str] = []

    def add_entities(self, text: str, spans: Iterable[FakeSpacySpan]) -> None:
        self._entities.setdefault(text, []).extend(spans)

    def reset(self) -> None:
        self._entities.clear()
        self.calls.clear()

    def __call__(self, text: str) -> FakeSpacyDoc:
        self.calls.append(text)
        spans = list(self._entities.get(text, []))
        if self._factory is not None:
            spans.extend(self._factory(text))
        return FakeSpacyDoc(text=text, ents=list(spans))

    def make_doc(self, text: str) -> FakeSpacyDoc:
        return FakeSpacyDoc(text=text, ents=[])


class FakeStorySniffer:
    """Configurable stand-in for ``storysniffer.StorySniffer``."""

    def __init__(
        self,
        *,
        decision: bool | Callable[[str], bool] | Mapping[str, bool] = True,
        exception: (
            Callable[[str], Exception] | Mapping[str, Exception] | None
        ) = None,
    ) -> None:
        self._decision = decision
        self._exception = exception
        self.calls: List[str] = []

    def guess(self, url: str) -> bool:
        self.calls.append(url)

        if self._exception is not None:
            if callable(self._exception):
                raise self._exception(url)
            if url in self._exception:
                raise self._exception[url]

        if callable(self._decision):
            return bool(self._decision(url))
        if isinstance(self._decision, Mapping):
            return bool(self._decision.get(url, False))
        return bool(self._decision)
