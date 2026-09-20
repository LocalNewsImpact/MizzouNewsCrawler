"""Every route that marks an article wire records the decision in one place.

Three routes can set `status='wire'`: the structured-metadata hints, the byline
cleaner, and the ContentTypeDetector's tiers. Only the third built a
`detection_payload`, so only the third reached
`content_type_detection_telemetry`. The other two wrote
`articles.metadata.wire_detection` and nothing else.

That table carries `evidence`, `reason`, `version` and `dataset_id` per
decision, which is what makes a corpus-wide question answerable at all: the
`pbs.org` pattern matching inside `cascadepbs.org` was found across 5,258 rows
with one query. The same question about a canonical-based call meant reading
JSON out of article rows one at a time — and the key those rows were filed under
named the wrong rule, which sent the investigation at the wrong code twice.

`reason` carries the RULE that decided rather than a fixed string, because
"which rule marked this, and on what evidence" is the question the table exists
to answer.

Known gap, deliberately not papered over: the single-URL path
(`handle_extract_url_command`) has a wire branch of its own, and a payload built
there would go nowhere. It BUILDS an `ExtractionMetrics` and passes it to the
extractor, but never calls `telemetry.record_extraction` -- `_process_batch`
calls that at four points, the single-URL path at none. So it writes no
extraction telemetry of any kind, not just no content-type row.

That reads as deliberate: it is the `extract-url` CLI command, described in its
own docstring as being for "quick debugging and operational checks", invoked by
hand and by no k8s manifest. The consequence to know is that a repair made with
`extract-url` leaves no telemetry, so a corpus-wide query cannot see its
verdict. Giving that path `record_extraction` is a separate change.
"""

from __future__ import annotations

import inspect

from src.cli.commands import extraction


def _code(func) -> str:
    """Source with comment lines stripped.

    This module explains the telemetry table at length in prose; an assertion
    matching the explanation would pass with the payload removed.
    """
    return "\n".join(
        line
        for line in inspect.getsource(func).splitlines()
        if not line.strip().startswith("#")
    )


class TestThePayloadShape:
    def test_it_matches_what_the_table_stores(self):
        got = extraction._wire_detection_payload(
            rule="canonical_cross_domain", services=["Associated Press"]
        )
        # The same keys the ContentTypeDetector's own payload uses, so both
        # kinds of decision land in the same columns.
        for key in (
            "status",
            "confidence",
            "confidence_score",
            "reason",
            "evidence",
            "version",
            "detected_at",
        ):
            assert key in got, key

    def test_the_reason_is_the_rule(self):
        got = extraction._wire_detection_payload(
            rule="jsonld_author", services=["Reuters"]
        )
        assert got["reason"] == "jsonld_author"
        assert got["evidence"]["detected_by"] == "jsonld_author"

    def test_the_status_is_wire(self):
        got = extraction._wire_detection_payload(rule="meta_author", services=["NPR"])
        assert got["status"] == "wire"

    def test_the_services_and_evidence_are_carried(self):
        got = extraction._wire_detection_payload(
            rule="canonical_cross_domain",
            services=["PBS"],
            evidence=["canonical=https://www.pbs.org/x"],
            raw_source=["PBS NewsHour"],
        )
        assert got["evidence"]["wire_services"] == ["PBS"]
        assert got["evidence"]["detail"] == ["canonical=https://www.pbs.org/x"]
        assert got["evidence"]["raw_source_name"] == ["PBS NewsHour"]

    def test_it_is_versioned(self):
        got = extraction._wire_detection_payload(rule="x", services=["y"])
        assert got["version"] == extraction.WIRE_DETECTION_PAYLOAD_VERSION
        assert extraction.WIRE_DETECTION_PAYLOAD_VERSION


class TestEveryRouteInTheBatchRecordsIt:
    def test_the_structured_route_builds_a_payload(self):
        code = _code(extraction._process_batch)
        assert "rule=detection_key," in code

    def test_the_byline_route_builds_a_payload(self):
        code = _code(extraction._process_batch)
        assert 'rule="byline_wire_service"' in code

    def test_both_wire_routes_and_the_tier_route_assign_it(self):
        code = _code(extraction._process_batch)
        # Two wire routes call the builder; the tier route builds its own dict.
        assert code.count("_wire_detection_payload(") == 2
        # Four assignments: the per-iteration reset to None, plus the three
        # routes that can decide.
        assert code.count("detection_payload = ") == 4
        assert code.count("detection_payload = None") == 1

    def test_the_payload_reaches_the_telemetry_setter(self):
        """Assigning it is useless if nothing hands it to telemetry."""
        code = _code(extraction._process_batch)
        assert "set_content_type_detection(detection_payload)" in code
        # The setter must come after the routes that assign, or the wire calls
        # would hand over the previous iteration's value.
        first_assign = code.index("detection_payload = _wire_detection_payload(")
        setter = code.index("set_content_type_detection(detection_payload)")
        assert first_assign < setter

    def test_it_is_reset_each_iteration(self):
        code = _code(extraction._process_batch)
        assert "detection_payload = None" in code

    def test_the_tier_route_is_untouched(self):
        code = _code(extraction._process_batch)
        # It only runs when nothing has already called wire, so the two cannot
        # overwrite each other.
        assert 'if article_status == "extracted":' in code
        assert '"version": detection_result.detector_version' in code
