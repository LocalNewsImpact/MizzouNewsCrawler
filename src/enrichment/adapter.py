"""The only module permitted to import backfield.

Each function calls one backfield node (or, for the content gate, litellm
directly), converts the result into a StepResult, and converts any exception
into StepResult(ok=False). Nothing here raises for a model failure and nothing
here touches the database (docs/BACKFIELD_IMPLEMENTATION.md §2).

Token usage: backfield's nodes do not return usage, so a litellm success
callback accumulates it into a ContextVar for the duration of each call. The
callback is registered once, lazily; with no accumulator set it is a no-op, so
other litellm users in the process are unaffected.
"""

from __future__ import annotations

import json
import re
from contextvars import ContextVar
from decimal import Decimal
from importlib import import_module
from pathlib import Path
from typing import Any, Callable

from src.enrichment.cost import call_cost
from src.enrichment.types import ArticleInput, StepResult

PROMPTS_DIR = Path(__file__).parent / "prompts"
GATE_PROMPT_VERSION = "content_gate-v1"
GATE_WINDOW_CHARS = 800
DEFAULT_TIMEOUT_S = 300

_USAGE_ACC: ContextVar[list | None] = ContextVar("enrichment_usage_acc", default=None)
_CALLBACK_REGISTERED = False


def _register_usage_callback() -> None:
    """Attach a usage collector to litellm, once per process."""
    global _CALLBACK_REGISTERED
    if _CALLBACK_REGISTERED:
        return
    try:
        import litellm
    except ImportError:
        # Absent in the crawler venv; present in the enrichment image via
        # backfield-ai. Without it, node calls fail on their own and usage
        # accounting is moot — so registration is best-effort.
        return

    def _collect(kwargs, completion_response, start_time, end_time):  # noqa: ANN001
        acc = _USAGE_ACC.get()
        if acc is None:
            return
        usage = getattr(completion_response, "usage", None)
        if usage is not None:
            acc.append(
                (
                    int(getattr(usage, "prompt_tokens", 0) or 0),
                    int(getattr(usage, "completion_tokens", 0) or 0),
                )
            )

    litellm.success_callback.append(_collect)
    _CALLBACK_REGISTERED = True


def _load(node: str) -> Callable[[dict, dict], dict]:
    """Resolve a backfield node runner. Isolated so tests can patch it."""
    module = import_module(f"agate_runtime.nodes.{node}")
    return getattr(module, f"run_{node}")


def _article_text(article: ArticleInput) -> str:
    return f"Headline: {article.title}\n\n{article.content}"


def _run_node(
    step: str,
    node: str,
    params: dict[str, Any],
    inputs: dict[str, Any],
    model: str,
) -> StepResult:
    _register_usage_callback()
    token = _USAGE_ACC.set([])
    try:
        fn = _load(node)
        payload = fn(params, inputs)
        if not isinstance(payload, dict):
            raise TypeError(f"node returned {type(payload).__name__}, expected dict")
        usage = _USAGE_ACC.get() or []
        tokens_in = sum(u[0] for u in usage)
        tokens_out = sum(u[1] for u in usage)
        return StepResult(
            step=step,
            ok=True,
            payload=payload,
            error=None,
            input_tokens=tokens_in,
            output_tokens=tokens_out,
            cost_usd=call_cost(model, tokens_in, tokens_out),
        )
    except Exception as exc:  # a model failure is a result, not an exception
        return StepResult(
            step=step,
            ok=False,
            payload=None,
            error=f"{type(exc).__name__}: {exc}"[:500],
            input_tokens=0,
            output_tokens=0,
            cost_usd=Decimal("0"),
        )
    finally:
        _USAGE_ACC.reset(token)


def run_scope(article: ArticleInput, model: str) -> StepResult:
    return _run_node(
        "scope",
        "article_metadata",
        {
            "model": model,
            "prompt_preset": "geographic_scope",
            "meta_type": "geographic_scope",
            "llmTimeout": DEFAULT_TIMEOUT_S,
        },
        {"text": _article_text(article)},
        model,
    )


def run_preset(article: ArticleInput, preset: str, model: str) -> StepResult:
    return _run_node(
        preset,
        "article_metadata",
        {
            "model": model,
            "prompt_preset": preset,
            "meta_type": preset,
            "llmTimeout": DEFAULT_TIMEOUT_S,
        },
        {"text": _article_text(article)},
        model,
    )


def run_places(article: ArticleInput, model: str) -> StepResult:
    return _run_node(
        "places",
        "place_extract",
        {"model": model},
        {"text": _article_text(article)},
        model,
    )


def run_people(article: ArticleInput, model: str) -> StepResult:
    return _run_node(
        "people",
        "person_extract",
        {"model": model},
        {"text": _article_text(article)},
        model,
    )


def run_organizations(article: ArticleInput, model: str) -> StepResult:
    return _run_node(
        "organizations",
        "organization_extract",
        {"model": model},
        {"text": _article_text(article)},
        model,
    )


_VALID_VERDICTS = {"news", "paywall", "not_news"}


def run_content_gate(
    article: ArticleInput, model: str, prefix_chars: int = GATE_WINDOW_CHARS
) -> StepResult:
    """Head+middle windows, direct litellm call (docs/BACKFIELD_IMPLEMENTATION.md §5.6)."""
    try:
        import litellm

        body = article.content or ""
        mid = max(0, len(body) // 2 - prefix_chars // 2)
        text = (
            f"Headline: {article.title}\n\n"
            f"START:\n{body[:prefix_chars]}\n\n"
            f"MIDDLE:\n{body[mid:mid + prefix_chars]}"
        )
        prompt = (PROMPTS_DIR / "content_gate.md").read_text().replace("{text}", text)
        response = litellm.completion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=60,
            timeout=DEFAULT_TIMEOUT_S,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or ""
        # Some providers wrap JSON in a code fence despite response_format.
        raw = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.M).strip()
        parsed = json.loads(raw)
        verdict = parsed.get("verdict")
        if verdict not in _VALID_VERDICTS:
            raise ValueError(f"verdict {verdict!r} not in {sorted(_VALID_VERDICTS)}")
        usage = response.usage
        tokens_in = int(getattr(usage, "prompt_tokens", 0) or 0)
        tokens_out = int(getattr(usage, "completion_tokens", 0) or 0)
        return StepResult(
            step="content_gate",
            ok=True,
            payload={
                "verdict": verdict,
                "reason": str(parsed.get("reason", ""))[:200],
                "prompt_version": GATE_PROMPT_VERSION,
            },
            error=None,
            input_tokens=tokens_in,
            output_tokens=tokens_out,
            cost_usd=call_cost(model, tokens_in, tokens_out),
        )
    except Exception as exc:
        return StepResult(
            step="content_gate",
            ok=False,
            payload=None,
            error=f"{type(exc).__name__}: {exc}"[:500],
            input_tokens=0,
            output_tokens=0,
            cost_usd=Decimal("0"),
        )
