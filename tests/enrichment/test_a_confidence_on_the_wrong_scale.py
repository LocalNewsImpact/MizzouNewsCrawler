"""65 is 0.65. It was being read as a bad value and costing the article.

`deepseek-v3.2` is one model name in front of fifteen providers, and they
do not agree on the scale. Asked for "a number from 0.0 to 1.0", AtlasCloud
returned 65 where SiliconFlow returned 0.7 for the same kind of question --
both the model answering correctly, one in percent.

`agate_nodes.article_metadata.parse` validates `0.0 <= confidence <= 1.0`
in a pydantic field_validator, so a percentage raises INSIDE the vendored
package, before the orchestrator sees the payload. A step failing discards
every result the article has collected and re-pays for them, and an article
needs nine consecutive validations -- so a per-call scale mismatch compounds
into a per-article failure. That is the shape of the 46% on 2026-09-07,
which was read as one provider being defective rather than as two scales.

The response is put on one scale at the adapter's litellm seam, before
backfield parses it. These tests cover the rule, the walk, the wrapper, and
-- the one that matters -- that a rescaled payload actually satisfies the
real vendored validator.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.enrichment.adapter import _as_fraction, _on_a_unit_scale, _rescale


class TestTheRule:
    @pytest.mark.parametrize(
        "given,expected",
        [
            (65, 0.65),
            (80, 0.8),
            (100, 1.0),
            (1.5, 0.015),
            ("65", 0.65),
        ],
    )
    def test_a_percentage_becomes_a_fraction(self, given, expected):
        assert _as_fraction(given) == pytest.approx(expected)

    @pytest.mark.parametrize("given", [0, 0.0, 0.7, 0.95, 1, 1.0])
    def test_a_fraction_is_left_alone(self, given):
        """Including exactly 1, the one ambiguous value. 1.0 confident and
        1 percent are both expressible; a model that answers at all rarely
        answers one percent, and 1.0 is what the unit scale already meant."""
        assert _as_fraction(given) == given

    @pytest.mark.parametrize("given", [-1, -0.5, 101, 1000])
    def test_what_is_not_a_scale_difference_is_left_for_backfield(self, given):
        """Negative, or above 100, is not two scales -- it is a bad value,
        and backfield should still refuse it. Rescaling it would launder a
        real defect into a plausible number."""
        assert _as_fraction(given) == given

    @pytest.mark.parametrize("given", [None, "high", "", [], {}])
    def test_a_non_number_is_untouched(self, given):
        assert _as_fraction(given) == given


class TestTheWalk:
    def test_every_confidence_key_at_any_depth(self):
        payload = {
            "article_metadata": {"category": "local", "confidence": 65},
            "subject_confidence": 80,
            "score": 50,
            "nested": [{"need_confidence": 90}, {"confidence": 0.4}],
        }
        got = _rescale(payload)
        assert got["article_metadata"]["confidence"] == pytest.approx(0.65)
        assert got["subject_confidence"] == pytest.approx(0.8)
        assert got["score"] == pytest.approx(0.5)
        assert got["nested"][0]["need_confidence"] == pytest.approx(0.9)
        assert got["nested"][1]["confidence"] == pytest.approx(0.4)

    def test_it_does_not_touch_other_numbers(self):
        """A count, a year, a latitude -- none of them are confidences, and
        dividing one by 100 would be silent corruption."""
        payload = {"confidence": 65, "count": 65, "year": 2026, "lat": 37.9}
        got = _rescale(payload)
        assert got["confidence"] == pytest.approx(0.65)
        assert got["count"] == 65
        assert got["year"] == 2026
        assert got["lat"] == 37.9


def _response(content):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


class TestTheWrapperNeverBreaksACall:
    """This sits in front of every model call the pipeline makes. A response
    it cannot understand must come back untouched, never raise."""

    def test_it_rewrites_the_message_content(self):
        response = _response(json.dumps({"confidence": 65, "places": ["Doolittle"]}))
        got = json.loads(_on_a_unit_scale(response).choices[0].message.content)
        assert got["confidence"] == pytest.approx(0.65)
        assert got["places"] == ["Doolittle"]

    def test_a_response_already_on_the_unit_scale_is_not_rewritten(self):
        original = json.dumps({"confidence": 0.7})
        response = _response(original)
        assert _on_a_unit_scale(response).choices[0].message.content == original

    @pytest.mark.parametrize(
        "content",
        ["not json at all", "", "{broken", "[1,2,3]", None, 42],
    )
    def test_anything_unparseable_is_returned_untouched(self, content):
        response = _response(content)
        assert _on_a_unit_scale(response).choices[0].message.content == content

    def test_a_response_with_no_choices_is_returned_untouched(self):
        assert _on_a_unit_scale(SimpleNamespace(choices=None)) is not None
        assert _on_a_unit_scale(SimpleNamespace()) is not None


class TestTheVendoredValidatorAcceptsIt:
    """THE ONE THAT MATTERS. Every test above this is about our own code;
    the rejection happens inside `agate_nodes`, in a pydantic validator we
    do not own and must not patch. So assert against the real one."""

    def _model(self):
        parse = pytest.importorskip("agate_nodes.article_metadata.parse")
        for name in dir(parse):
            candidate = getattr(parse, name)
            fields = getattr(candidate, "model_fields", None)
            if isinstance(fields, dict) and "confidence" in fields:
                return candidate
        pytest.skip("no agate_nodes model with a confidence field")

    def test_a_percentage_is_refused_by_backfield(self):
        """The defect, stated against the real validator: this is why the
        step failed and the article was re-paid for."""
        from pydantic import ValidationError

        model = self._model()
        with pytest.raises(ValidationError, match="0.0 and 1.0"):
            model(category="local", confidence=65, rationale="x")

    def test_the_rescaled_value_is_accepted(self):
        """And the fix, against the same validator."""
        model = self._model()
        rescaled = _as_fraction(65)
        instance = model(category="local", confidence=rescaled, rationale="x")
        assert instance.confidence == pytest.approx(0.65)
