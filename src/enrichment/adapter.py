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
import logging
import os
import re
from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal
from functools import wraps
from importlib import import_module
from pathlib import Path
from typing import Any, Callable, Iterator

from src.enrichment.cost import call_cost
from src.enrichment.types import ArticleInput, StepResult

logger = logging.getLogger(__name__)

#: How many times one node is asked before the article is given up on.
#:
#: Two, not more: the failures seen are a model sampling something its own
#: validator refuses, and a second draw is usually valid. A third would
#: mostly pay again for a prompt the model cannot satisfy. Retrying here
#: rather than in the orchestrator is what keeps the article's earlier
#: steps, which are otherwise discarded and re-paid for.
STEP_ATTEMPTS = 2

#: The OpenRouter providers this pipeline will accept for its model.
#:
#: `deepseek/deepseek-v3.2` is one model name in front of a pool of
#: providers, and OpenRouter chooses between them per request. The pool
#: changed under us. From the trace export in
#: gs://mizzou-openrouter-logs/openrouter-traces:
#:
#:     2026-08-22, 14,441 articles enriched clean
#:         AtlasCloud 24, SiliconFlow 5, Baidu 1  (of 30 sampled)
#:     2026-09-07, 46% of articles failing
#:         StreamLake 90, Friendli 19, AtlasCloud 5, Baidu 5, Alibaba 1
#:         (of 120 sampled)
#:
#: StreamLake appears in none of the August traces and serves three
#: quarters of today's. The failures are all one step returning a
#: confidence outside 0.0-1.0, which backfield's schema refuses -- so the
#: model name, the prompts, the validator and the vendored wheels are all
#: unchanged, and the answers are not.
#:
#: An article needs nine consecutive validations, so a per-call defect
#: rate on a provider serving most of the traffic compounds into a
#: per-article one. That is the 46%.
#:
#: Set ENRICHMENT_PROVIDERS to override without a deploy. Empty means no
#: pin, which is the behaviour that produced this.
ENRICHMENT_PROVIDERS = tuple(
    name.strip()
    for name in os.getenv("ENRICHMENT_PROVIDERS", "AtlasCloud,SiliconFlow,Baidu").split(
        ","
    )
    if name.strip()
)

PROMPTS_DIR = Path(__file__).parent / "prompts"
GATE_PROMPT_VERSION = "content_gate-v1"
GATE_WINDOW_CHARS = 800
FOCUS_PROMPT_VERSION = "focus-v1"
FOCUS_MAX_CHARS = 20000
DEFAULT_TIMEOUT_S = 300

_USAGE_ACC: ContextVar[list | None] = ContextVar("enrichment_usage_acc", default=None)
_CALLBACK_REGISTERED = False

#: Which dataset the calls being made right now are for. Read by the wrapper
#: below and sent as LiteLLM's `user`, which OpenRouter records as
#: `external_user` on the generation -- the only field that survives the trip
#: and can say what the money was spent on.
_DATASET: ContextVar[str | None] = ContextVar("enrichment_dataset", default=None)
_WRAPPED = False


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


def _label_calls_with_the_dataset() -> None:
    """Send `user` on every completion, once per process.

    The steps this module runs directly can pass `user` themselves. The
    node steps cannot: they call through agate_runtime into agate_nodes,
    which makes its own requests and has no idea a dataset exists. Those
    are the larger share of the bill, so labelling only what we call
    directly would attribute a fraction and leave the rest looking like
    overhead.

    So the label goes on at the one place every call passes through --
    litellm itself. This module already reaches into litellm to collect
    usage; this is the same reach for the same reason, and the wrapper is
    a pass-through in every respect but the one keyword.

    `user` is not overwritten where a caller set it, so the direct calls
    keep saying what they already say.
    """
    global _WRAPPED
    if _WRAPPED:
        return
    try:
        import litellm
    except ImportError:
        # Absent in the crawler venv, present in the enrichment image --
        # the same best-effort as the usage callback above.
        return

    inner = litellm.completion

    @wraps(inner)
    def labelled(*args: Any, **kwargs: Any) -> Any:
        dataset = _DATASET.get()
        if dataset and not kwargs.get("user"):
            kwargs["user"] = dataset
        if ENRICHMENT_PROVIDERS:
            # Routing goes in extra_body: litellm passes it through to
            # OpenRouter untouched. Verified against the trace export --
            # a pinned call was served by SiliconFlow, an unpinned control
            # issued seconds later by AtlasCloud, so the constraint binds
            # rather than being quietly dropped.
            #
            # A caller that has already asked for providers keeps its own.
            extra = dict(kwargs.get("extra_body") or {})
            extra.setdefault(
                "provider",
                {"only": list(ENRICHMENT_PROVIDERS), "allow_fallbacks": False},
            )
            kwargs["extra_body"] = extra
        return inner(*args, **kwargs)

    litellm.completion = labelled
    _WRAPPED = True


@contextmanager
def for_dataset(slug: str | None) -> Iterator[None]:
    """Label every completion made inside this block."""
    _label_calls_with_the_dataset()
    token = _DATASET.set(slug or None)
    try:
        yield
    finally:
        _DATASET.reset(token)


def _labelled(fn: Callable[..., StepResult]) -> Callable[..., StepResult]:
    """Run a step with its article's dataset on every completion inside it.

    On the steps rather than around the orchestrator: every path to a model
    goes through one of these, each already holds the article, and the
    orchestrator can keep being handed a stand-in adapter by its tests
    without knowing this exists.
    """

    @wraps(fn)
    def run(article: ArticleInput, *args: Any, **kwargs: Any) -> StepResult:
        with for_dataset(getattr(article, "dataset_slug", None)):
            return fn(article, *args, **kwargs)

    return run


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
    attempts: int = STEP_ATTEMPTS,
) -> StepResult:
    """Run one node, retrying it rather than losing the article.

    A step failing does not fail the step's article gracefully: the
    orchestrator discards EVERY result it has collected and rewinds the
    article whole, so five good steps are thrown away and paid for again
    because the sixth returned something unparseable.

    Measured on 191 articles enriched on 2026-09-07: 87 of them -- 46% --
    came back with nothing written, and the sampled cause was one step,
    `temporal_orientation`, returning a confidence outside 0.0-1.0 which
    the response validator refuses. Every earlier step had passed. About
    $0.46 of $1.38 bought results that were dropped.

    The rate is per-article, not per-call: an article needs nine
    consecutive validations, so a modest per-call defect rate compounds.
    Retrying the one step is the cheapest place to break that chain,
    because the model is sampling and a second draw is usually valid.

    The failure is also logged. Those 87 recorded no reason anywhere --
    the outcome carries the error and `persist_outcome` writes only the
    attempt counter for a transient failure -- so finding this needed
    articles re-run through the orchestrator by hand.
    """
    _register_usage_callback()
    last_error: str | None = None

    for attempt in range(1, attempts + 1):
        token = _USAGE_ACC.set([])
        try:
            fn = _load(node)
            payload = fn(params, inputs)
            if not isinstance(payload, dict):
                raise TypeError(
                    f"node returned {type(payload).__name__}, expected dict"
                )
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
            last_error = f"{type(exc).__name__}: {exc}"[:500]
            logger.warning(
                "enrichment step %s failed on attempt %d of %d: %s",
                step,
                attempt,
                attempts,
                last_error,
            )
        finally:
            _USAGE_ACC.reset(token)

    return StepResult(
        step=step,
        ok=False,
        payload=None,
        error=last_error,
        input_tokens=0,
        output_tokens=0,
        cost_usd=Decimal("0"),
    )


@_labelled
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


@_labelled
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


@_labelled
def run_places(article: ArticleInput, model: str) -> StepResult:
    return _run_node(
        "places",
        "place_extract",
        {"model": model},
        {"text": _article_text(article)},
        model,
    )


@_labelled
def run_people(article: ArticleInput, model: str) -> StepResult:
    return _run_node(
        "people",
        "person_extract",
        {"model": model},
        {"text": _article_text(article)},
        model,
    )


@_labelled
def run_organizations(article: ArticleInput, model: str) -> StepResult:
    return _run_node(
        "organizations",
        "organization_extract",
        {"model": model},
        {"text": _article_text(article)},
        model,
    )


_VALID_VERDICTS = {"news", "paywall", "not_news"}


@_labelled
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
            # Which dataset paid for this call. LiteLLM forwards `user`
            # to OpenRouter, which records it as `external_user` on the
            # generation, so the billed cost can be split the way the
            # recorded cost already is. Without it every trace we have
            # collected says only that the money was spent -- the cost
            # page shows a per-dataset figure for the recorded side and
            # nothing at all for the billed one.
            user=article.dataset_slug,
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


@_labelled
def run_focus(article: ArticleInput, model: str) -> StepResult:
    """The central-geography claim: which one city/town is this story about.

    Direct litellm call like the gate. Instructions lead and the article text
    trails so the shared prefix caches across articles. The model's central
    answer feeds point resolution; its mention list is advisory (place_extract
    remains the mention source of record). Validated 5-for-5 against stories
    where the name-match heuristic failed (2026-08-21)."""
    try:
        import litellm

        text = (
            f"Headline: {article.title}\n\n{(article.content or '')[:FOCUS_MAX_CHARS]}"
        )
        prompt = (PROMPTS_DIR / "focus.md").read_text().replace("{text}", text)
        response = litellm.completion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
            timeout=DEFAULT_TIMEOUT_S,
            temperature=0,
            response_format={"type": "json_object"},
            user=article.dataset_slug,
        )
        raw = response.choices[0].message.content or ""
        raw = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.M).strip()
        parsed = json.loads(raw)
        central = parsed.get("central") or {}
        if not central.get("city"):
            raise ValueError("no central city in focus response")
        usage = response.usage
        tokens_in = int(getattr(usage, "prompt_tokens", 0) or 0)
        tokens_out = int(getattr(usage, "completion_tokens", 0) or 0)
        return StepResult(
            step="focus",
            ok=True,
            payload={
                "central": {
                    "city": str(central.get("city"))[:120],
                    "state": str(central.get("state") or "")[:40] or None,
                },
                "mentions": [
                    {
                        "city": str(m.get("city"))[:120],
                        "state": str(m.get("state") or "")[:40] or None,
                    }
                    for m in (parsed.get("mentions") or [])
                    if isinstance(m, dict) and m.get("city")
                ][:25],
                "rationale": str(parsed.get("rationale", ""))[:300],
                "prompt_version": FOCUS_PROMPT_VERSION,
            },
            error=None,
            input_tokens=tokens_in,
            output_tokens=tokens_out,
            cost_usd=call_cost(model, tokens_in, tokens_out),
        )
    except Exception as exc:
        return StepResult(
            step="focus",
            ok=False,
            payload=None,
            error=f"{type(exc).__name__}: {exc}"[:500],
            input_tokens=0,
            output_tokens=0,
            cost_usd=Decimal("0"),
        )
