"""The dataset label has to be in the request body, not in a `user` keyword.

`article_enrichment.cost_usd` says what the pipeline BELIEVED each article
cost. OpenRouter's traces say what was actually charged. The cost page puts
them side by side, and splits the recorded side per dataset -- Mizzou $135.21,
WSU $4.62, VTCNI $0.14 on 2026-09-20. It cannot split the billed side, because
the only field that survives the trip is `external_user`, and OpenRouter sets
that from the `user` field of the request body.

We were sending it. `external_user` was still set on **2 of 193,081** traces in
30 days, and both of those were 13-token calls made by hand on 2026-09-14 to
prove the field works. Every real enrichment call -- all of them on the
"Backfield" API key, $97.76 of billed spend -- said only that the money was
spent.

`user` is a standard OpenAI parameter, but it is not in litellm's supported set
for the openrouter provider: 31 params for
`openrouter/deepseek/deepseek-v3.2-20251201`, and `user` is not among them. The
transform drops it before the request is built. Measured against litellm 1.97.0
by pointing `api_base` at a local listener and reading what arrived:

    user="WSU-Washington-State"        -> body keys: messages, model
    extra_body={"user": "WSU-..."}     -> body keys: messages, model, user

So the label goes in `extra_body`, which litellm passes through untouched --
the same route the provider pin already uses, and the same reason it works.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

from src.enrichment import adapter


@pytest.fixture
def litellm_stub(monkeypatch):
    """A stubbed litellm, plus a handle on the call the wrapper delegates to.

    The wrapper replaces `litellm.completion`, so asserting on the module
    attribute afterwards inspects the wrapper rather than what it passed on.
    """
    stub = MagicMock()
    inner = MagicMock(return_value="response")
    stub.completion = inner
    stub.success_callback = []
    monkeypatch.setitem(sys.modules, "litellm", stub)
    monkeypatch.setattr(adapter, "_WRAPPED", False)
    return stub, inner


def _sent(inner) -> dict:
    return inner.call_args.kwargs


class TestWhereTheLabelGoes:
    def test_it_is_in_the_request_body(self, litellm_stub):
        stub, inner = litellm_stub
        with adapter.for_dataset("WSU-Washington-State"):
            stub.completion(model="openrouter/x", messages=[])

        assert _sent(inner)["extra_body"]["user"] == "WSU-Washington-State"

    def test_it_is_not_passed_as_a_keyword(self, litellm_stub):
        """The whole defect. A `user` keyword is dropped by litellm's
        openrouter transform, so a call that carries it there is
        indistinguishable from one that says nothing."""
        stub, inner = litellm_stub
        with adapter.for_dataset("WSU-Washington-State"):
            stub.completion(model="openrouter/x", messages=[])

        assert "user" not in _sent(inner)

    def test_a_caller_that_passes_user_has_it_relocated(self, litellm_stub):
        """Honouring it where it sits would be honouring nothing."""
        stub, inner = litellm_stub
        adapter._label_calls_with_the_dataset()
        stub.completion(model="openrouter/x", messages=[], user="Mizzou-Missouri-State")

        sent = _sent(inner)
        assert "user" not in sent
        assert sent["extra_body"]["user"] == "Mizzou-Missouri-State"

    def test_a_callers_own_label_wins_over_the_context(self, litellm_stub):
        stub, inner = litellm_stub
        with adapter.for_dataset("WSU-Washington-State"):
            stub.completion(model="openrouter/x", messages=[], user="VT-Community-News")

        assert _sent(inner)["extra_body"]["user"] == "VT-Community-News"

    def test_no_dataset_means_no_label_rather_than_an_empty_one(self, litellm_stub):
        """`external_user: ""` would be a dataset named nothing, which reads on
        the cost page as a fourth dataset rather than as absent."""
        stub, inner = litellm_stub
        with adapter.for_dataset(None):
            stub.completion(model="openrouter/x", messages=[])

        assert "user" not in (_sent(inner).get("extra_body") or {})

    def test_it_does_not_disturb_the_provider_pin(self, litellm_stub, monkeypatch):
        """Both ride in `extra_body`; one must not overwrite the other."""
        monkeypatch.setattr(adapter, "ENRICHMENT_PROVIDERS", ("DeepSeek",))
        stub, inner = litellm_stub
        with adapter.for_dataset("WSU-Washington-State"):
            stub.completion(model="openrouter/x", messages=[])

        extra = _sent(inner)["extra_body"]
        assert extra["user"] == "WSU-Washington-State"
        assert extra["provider"]["only"] == ["DeepSeek"]

    def test_a_callers_extra_body_is_kept(self, litellm_stub):
        stub, inner = litellm_stub
        with adapter.for_dataset("WSU-Washington-State"):
            stub.completion(
                model="openrouter/x", messages=[], extra_body={"transforms": ["x"]}
            )

        extra = _sent(inner)["extra_body"]
        assert extra["transforms"] == ["x"]
        assert extra["user"] == "WSU-Washington-State"

    def test_the_label_is_per_article_not_per_process(self, litellm_stub):
        """Datasets interleave: the queue serves whatever is ready, and a
        process-wide label would bill one dataset for another's articles."""
        stub, inner = litellm_stub
        seen = []
        with adapter.for_dataset("WSU-Washington-State"):
            stub.completion(model="openrouter/x", messages=[])
            seen.append(_sent(inner)["extra_body"]["user"])
        with adapter.for_dataset("Mizzou-Missouri-State"):
            stub.completion(model="openrouter/x", messages=[])
            seen.append(_sent(inner)["extra_body"]["user"])
        assert seen == ["WSU-Washington-State", "Mizzou-Missouri-State"]


class TestEveryStepIsCovered:
    def test_each_step_carries_its_article_s_dataset(self):
        """The node steps are the larger share of the bill -- 193,081 calls for
        ~17,000 articles -- so labelling only the direct calls would attribute a
        fraction and leave the rest looking like overhead."""
        import inspect

        source = inspect.getsource(adapter)
        decorated = source.count("@_labelled")
        assert decorated >= 7, f"only {decorated} steps carry the label"

    def test_the_direct_calls_no_longer_pass_a_dead_keyword(self):
        """They used to pass `user=article.dataset_slug`, which read as working
        and was discarded by litellm. The wrapper labels them now."""
        import inspect

        source = inspect.getsource(adapter)
        assert "user=article.dataset_slug" not in source


class TestAgainstTheRealLibrary:
    """What litellm puts on the wire, read off a socket.

    Skipped where litellm is absent -- it is in no requirements file, arriving
    with backfield-ai in the enrichment image -- so the hermetic tests above are
    what guards this in CI. This one is why the code is shaped the way it is.
    """

    @staticmethod
    def _body_for(**kwargs) -> dict:
        """The body litellm sends, read off a socket in a FRESH interpreter.

        A subprocess rather than this one: the adapter's wrapper is installed on
        `litellm.completion` by a module global and stays installed, so a test
        that ran earlier would have it relocating `user` into `extra_body` --
        making the keyword appear to reach the wire. Unwrapping in-process is not
        an answer either; litellm decorates its own entry point, and unwrapping
        past that returns a function the call never completes through.
        """
        import json
        import subprocess
        import sys

        pytest.importorskip("litellm")
        script = (
            "import json, threading\n"
            "from http.server import BaseHTTPRequestHandler, HTTPServer\n"
            "captured = {}\n"
            "class H(BaseHTTPRequestHandler):\n"
            "    def do_POST(self):\n"
            "        n = int(self.headers.get('content-length', 0))\n"
            "        captured['body'] = json.loads(self.rfile.read(n) or b'{}')\n"
            "        p = json.dumps({'id': 'g', 'model': 'x', 'choices': [{'message':"
            " {'role': 'assistant', 'content': '{}'}, 'finish_reason': 'stop'}],"
            " 'usage': {'prompt_tokens': 1, 'completion_tokens': 1,"
            " 'total_tokens': 2}}).encode()\n"
            "        self.send_response(200)\n"
            "        self.send_header('content-type', 'application/json')\n"
            "        self.send_header('content-length', str(len(p)))\n"
            "        self.end_headers()\n"
            "        self.wfile.write(p)\n"
            "    def log_message(self, *a):\n"
            "        pass\n"
            "srv = HTTPServer(('127.0.0.1', 0), H)\n"
            "threading.Thread(target=srv.serve_forever, daemon=True).start()\n"
            "import sys, json as _j\n"
            "extra = _j.loads(sys.argv[1])\n"
            "import litellm\n"
            "litellm.suppress_debug_info = True\n"
            "try:\n"
            "    litellm.completion(model='openrouter/deepseek/deepseek-v3.2-20251201',"
            " messages=[{'role': 'user', 'content': 'hi'}], api_key='sk-test',"
            " api_base='http://127.0.0.1:%d' % srv.server_port, timeout=10, **extra)\n"
            "except Exception:\n"
            "    pass\n"
            "srv.shutdown()\n"
            "print('BODY:' + json.dumps(captured.get('body', {})))\n"
        )
        out = subprocess.run(
            [sys.executable, "-c", script, json.dumps(kwargs)],
            capture_output=True,
            text=True,
            timeout=180,
        )
        for line in out.stdout.splitlines():
            if line.startswith("BODY:"):
                return json.loads(line[len("BODY:") :])
        raise AssertionError(f"probe produced no body: {out.stdout[-400:]}")

    def test_a_user_keyword_never_reaches_the_wire(self):
        body = self._body_for(user="WSU-Washington-State")
        assert "user" not in body, "if this passes, the keyword works after all"

    def test_extra_body_does(self):
        body = self._body_for(extra_body={"user": "WSU-Washington-State"})
        assert body.get("user") == "WSU-Washington-State"

    def test_the_label_and_the_pin_both_survive_together(self):
        body = self._body_for(
            extra_body={
                "user": "WSU-Washington-State",
                "provider": {"only": ["DeepSeek"], "allow_fallbacks": False},
            }
        )
        assert body.get("user") == "WSU-Washington-State"
        assert body.get("provider", {}).get("only") == ["DeepSeek"]
