"""14,441 articles enriched clean on 2026-08-22. Two weeks later, 46% of a
191-article run failed, with no change to this repository.

`deepseek/deepseek-v3.2` is one model name in front of a pool of
providers, and OpenRouter picks between them per request. The pool moved.
From the trace export in gs://mizzou-openrouter-logs/openrouter-traces:

    2026-08-22 (clean)    AtlasCloud 24, SiliconFlow 5, Baidu 1   of 30
    2026-09-07 (46% fail) StreamLake 90, Friendli 19, AtlasCloud 5,
                          Baidu 5, Alibaba 1                      of 120

StreamLake appears in none of the August traces and served three quarters
of today's. Every failure was one step, `temporal_orientation`, returning
a confidence outside 0.0-1.0 that backfield's schema refuses. The model
name, the prompts, the validator and the vendored wheels are unchanged;
the answers are not.

An article needs nine consecutive validations to finish, so a per-call
defect rate on a provider serving most of the traffic compounds into the
per-article one.
"""

import os
from unittest.mock import MagicMock

import pytest

from src.enrichment import adapter


@pytest.fixture
def litellm_stub(monkeypatch):
    """A stubbed litellm, plus a handle on the call the wrapper delegates to.

    The wrapper replaces `litellm.completion`, so asserting on the module
    attribute afterwards inspects the wrapper rather than what it passed
    on. `inner` is what actually receives the request.
    """
    import sys

    stub = MagicMock()
    inner = MagicMock(return_value="response")
    stub.completion = inner
    stub.success_callback = []
    monkeypatch.setitem(sys.modules, "litellm", stub)
    monkeypatch.setattr(adapter, "_WRAPPED", False)
    return stub, inner


def test_no_pin_means_the_request_constrains_nothing(litellm_stub):
    """UNPINNED BY DEFAULT. With no pin the request carries no `provider`
    block at all, so OpenRouter routes across the whole pool."""
    stub, inner = litellm_stub
    adapter._label_calls_with_the_dataset()
    stub.completion(model="openrouter/deepseek/deepseek-v3.2", messages=[])

    sent = inner.call_args.kwargs
    assert "provider" not in (sent.get("extra_body") or {})


def test_the_pin_is_empty_by_default():
    """The pin was AtlasCloud, SiliconFlow, Baidu -- the pool that enriched
    14,441 articles in August -- and it was removed on 2026-09-14.

    It was answering the wrong question. The September failures were read
    as providers returning "a confidence outside 0.0-1.0"; they were
    returning percentages, which `_on_a_unit_scale` now normalises before
    backfield parses. The pin was a way of selecting providers that
    happened to share our scale.

    It also had a cost. OpenRouter routes by price within a pin, so every
    call went to the cheapest member -- which on 2026-09-14 returned 400 to
    594 of 594 requests while reporting healthy -- and `allow_fallbacks:
    False` left nowhere to go. 99 of 111 articles failed and burned an
    attempt each."""
    assert adapter.ENRICHMENT_PROVIDERS == ()


def test_a_pin_still_binds_when_one_is_asked_for(litellm_stub, monkeypatch):
    """Removing the default does not remove the mechanism: a provider that
    turns out to be genuinely wrong can still be excluded without a
    deploy."""
    monkeypatch.setattr(adapter, "ENRICHMENT_PROVIDERS", ("SiliconFlow",))
    stub, inner = litellm_stub
    adapter._label_calls_with_the_dataset()
    stub.completion(model="openrouter/deepseek/deepseek-v3.2", messages=[])

    provider = inner.call_args.kwargs["extra_body"]["provider"]
    assert provider["only"] == ["SiliconFlow"]
    assert provider["allow_fallbacks"] is False


def test_a_caller_that_chose_its_own_providers_keeps_them(litellm_stub):
    """The pin is a default, not an override."""
    stub, inner = litellm_stub
    adapter._label_calls_with_the_dataset()
    stub.completion(
        model="openrouter/deepseek/deepseek-v3.2",
        messages=[],
        extra_body={"provider": {"only": ["Baidu"]}},
    )

    sent = inner.call_args.kwargs

    assert sent["extra_body"]["provider"]["only"] == ["Baidu"]


def test_other_extra_body_keys_survive(litellm_stub):
    stub, inner = litellm_stub
    adapter._label_calls_with_the_dataset()
    stub.completion(
        model="openrouter/deepseek/deepseek-v3.2",
        messages=[],
        extra_body={"transforms": ["middle-out"]},
    )

    sent = inner.call_args.kwargs

    assert sent["extra_body"]["transforms"] == ["middle-out"]
    # And nothing is added: unpinned, the wrapper contributes no `provider`
    # block, so a caller's extra_body comes through as written.
    assert "provider" not in sent["extra_body"]


def test_a_pin_can_be_applied_without_a_deploy(monkeypatch):
    """The env var reads the same way it always did; only the default
    changed. A provider found to be genuinely wrong -- not merely counting
    in percent -- can be excluded without shipping code."""
    monkeypatch.setenv("ENRICHMENT_PROVIDERS", "SiliconFlow, Baidu")
    providers = tuple(
        name.strip()
        for name in os.getenv("ENRICHMENT_PROVIDERS", "").split(",")
        if name.strip()
    )
    assert providers == ("SiliconFlow", "Baidu")


def test_no_setting_means_no_pin(monkeypatch):
    monkeypatch.delenv("ENRICHMENT_PROVIDERS", raising=False)
    providers = tuple(
        name.strip()
        for name in os.getenv("ENRICHMENT_PROVIDERS", "").split(",")
        if name.strip()
    )
    assert providers == ()
