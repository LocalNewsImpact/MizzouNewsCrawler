"""Unit tests for `BylineCleaner`."""

from unittest.mock import MagicMock, patch

from src.utils.byline_cleaner import BylineCleaner


def test_clean_byline_strips_titles_and_prefixes():
    cleaner = BylineCleaner(enable_telemetry=False)

    result = cleaner.clean_byline("By Jane Doe, Staff Writer")

    assert result == ["Jane Doe"]


def test_clean_byline_splits_multiple_authors():
    cleaner = BylineCleaner(enable_telemetry=False)

    result = cleaner.clean_byline("By John Smith and Jane Doe")

    assert result == ["John Smith", "Jane Doe"]


def test_clean_byline_detects_wire_service_returns_metadata():
    cleaner = BylineCleaner(enable_telemetry=False)

    result = cleaner.clean_byline("Associated Press", return_json=True)

    assert isinstance(result, dict)
    assert result["authors"] == []
    assert result["wire_services"] == ["The Associated Press"]
    assert result["primary_wire_service"] == "The Associated Press"
    assert result["is_wire_content"] is True


def test_clean_byline_extracts_special_contributor():
    cleaner = BylineCleaner(enable_telemetry=False)

    result = cleaner.clean_byline("Jane Doe Special to The Post-Dispatch")

    assert result == ["Jane Doe"]


def test_clean_byline_removes_emails_from_authors():
    cleaner = BylineCleaner(enable_telemetry=False)

    result = cleaner.clean_byline("By Jane Doe jdoe@example.com")

    assert result == ["Jane Doe"]


def test_clean_byline_wire_service_passthrough_when_not_local():
    cleaner = BylineCleaner(enable_telemetry=False)

    def fake_wire_detection(byline: str) -> bool:
        cleaner._detected_wire_services.append("Reuters")
        return True

    with (
        patch.object(
            cleaner,
            "_is_wire_service",
            side_effect=fake_wire_detection,
        ),
        patch.object(
            cleaner,
            "_is_wire_service_from_own_source",
            return_value=False,
        ),
    ):
        result = cleaner.clean_byline("Reuters", return_json=True)

    assert isinstance(result, dict)
    assert result["wire_services"] == ["Reuters"]
    assert result["authors"] == []
    assert result["is_wire_content"] is True


def test_clean_byline_wire_service_from_local_source_continues_processing():
    cleaner = BylineCleaner(enable_telemetry=False)

    def fake_wire(byline: str) -> bool:
        cleaner._detected_wire_services.append("The Associated Press")
        return True

    with (
        patch.object(
            cleaner,
            "_is_wire_service",
            side_effect=fake_wire,
        ),
        patch.object(
            cleaner,
            "_is_wire_service_from_own_source",
            return_value=True,
        ),
        patch.object(
            cleaner,
            "_extract_special_contributor",
            return_value=None,
        ),
        patch.object(
            cleaner,
            "_remove_source_name",
            return_value="Reporter John",
        ),
        patch.object(
            cleaner,
            "_extract_authors",
            return_value=["Reporter John"],
        ),
        patch.object(
            cleaner,
            "_clean_author_name",
            side_effect=lambda value: value,
        ),
        patch.object(
            cleaner,
            "_deduplicate_authors",
            side_effect=lambda names: names,
        ),
        patch.object(
            cleaner,
            "_validate_authors",
            side_effect=lambda names: names,
        ),
    ):
        result = cleaner.clean_byline(
            "Associated Press",
            source_name="The Associated Press",
        )

    assert result == ["Reporter John"]
    assert cleaner._detected_wire_services == []


def test_clean_byline_smart_processing_path_deduplicates_names():
    cleaner = BylineCleaner(enable_telemetry=False)

    with (
        patch.object(
            cleaner,
            "_extract_special_contributor",
            return_value=None,
        ),
        patch.object(
            cleaner,
            "_extract_authors",
            return_value=["__SMART_PROCESSED__", "Jane Doe", "Jane Doe"],
        ),
        patch.object(
            cleaner,
            "_clean_author_name",
            side_effect=lambda name: name,
        ),
    ):
        result = cleaner.clean_byline("By Jane Doe", return_json=True)

    assert isinstance(result, dict)
    assert result["authors"] == ["Jane Doe"]
    assert result["is_wire_content"] is False


def test_is_wire_service_detects_and_tracks_normalized():
    cleaner = BylineCleaner(enable_telemetry=False)

    assert cleaner._is_wire_service("By AP") is True
    assert cleaner._detected_wire_services == ["The Associated Press"]

    assert cleaner._is_wire_service("Reuters") is True
    assert cleaner._detected_wire_services[-1] == "Reuters"


def test_is_wire_service_from_own_source_similarity():
    cleaner = BylineCleaner(enable_telemetry=False)

    assert cleaner._is_wire_service_from_own_source(
        "The Associated Press",
        "The Associated Press",
    ) is True
    assert cleaner._is_wire_service_from_own_source(
        "USA Today Network",
        "USA Today Network Tennessee",
    ) is True
    assert cleaner._is_wire_service_from_own_source(
        "Reuters",
        "Springfield Daily News",
    ) is False


def test_remove_source_name_removes_publication_suffix():
    cleaner = BylineCleaner(enable_telemetry=False)

    assert cleaner._remove_source_name(
        "By Jane Doe Springfield News-Leader",
        "Springfield News-Leader",
    ) == "By Jane Doe"
    assert cleaner._remove_source_name(
        "Springfield News-Leader",
        "Springfield News-Leader",
    ) == ""


def test_remove_source_name_drops_all_words_when_only_publication_remains():
    cleaner = BylineCleaner(enable_telemetry=False)

    assert (
        cleaner._remove_source_name(
            "By Springfield News-Leader",
            "Springfield News-Leader",
        )
        == ""
    )


def test_remove_source_name_partial_word_match_removes_publication_portion():
    cleaner = BylineCleaner(enable_telemetry=False)

    result = cleaner._remove_source_name(
        "By Jane Doe Springfield Voice",
        "The Springfield Voice",
    )

    assert result == "By Jane Doe"


def test_remove_source_name_preserves_remaining_words():
    cleaner = BylineCleaner(enable_telemetry=False)

    result = cleaner._remove_source_name(
        "Jane Doe Springfield Daily News Contributor",
        "Springfield Daily News",
    )

    assert result == "Jane Doe Contributor"


def test_refresh_publication_cache_forces_refresh():
    cleaner = BylineCleaner(enable_telemetry=False)

    with patch.object(
        cleaner,
        "get_publication_names",
        return_value=set(),
    ) as mock_get_pub_names:
        cleaner.refresh_publication_cache()

    mock_get_pub_names.assert_called_once_with(force_refresh=True)


def test_is_publication_name_handles_various_branches(monkeypatch):
    cleaner = BylineCleaner(enable_telemetry=False)

    publication_names = {
        "county journal",
        "local",
        "press",
        "gazette",
    }
    organization_names = {"county health department"}

    monkeypatch.setattr(
        cleaner,
        "get_publication_names",
        MagicMock(return_value=publication_names),
    )
    monkeypatch.setattr(
        cleaner,
        "get_organization_names",
        MagicMock(return_value=organization_names),
    )

    assert cleaner._is_publication_name("County Journal") is True
    assert cleaner._is_publication_name("County Health Department") is True
    assert cleaner._is_publication_name("AP News") is True
    assert (
        cleaner._is_publication_name("County Department Services")
        is True
    )
    assert cleaner._is_publication_name("Local Press Gazette") is True
    assert cleaner._is_publication_name("News, Local") is False
    assert cleaner._is_publication_name("AP") is False


def test_is_url_fragment_detects_patterns():
    cleaner = BylineCleaner(enable_telemetry=False)

    assert cleaner._is_url_fragment("") is False
    assert cleaner._is_url_fragment("two words here") is False
    assert cleaner._is_url_fragment("www.example.com") is True
    assert cleaner._is_url_fragment("http://example.com") is True
    assert cleaner._is_url_fragment("Www..Example.Com") is True


def test_extract_name_from_url_fragment_selects_name():
    cleaner = BylineCleaner(enable_telemetry=False)

    text = "Jane A. Doe • www.example.com"
    assert cleaner._extract_name_from_url_fragment(text) == "Jane A. Doe"
    assert cleaner._extract_name_from_url_fragment("www.example.com") == ""
    assert cleaner._extract_name_from_url_fragment("") == ""
    assert (
        cleaner._extract_name_from_url_fragment("Valid Name With No URL")
        == "Valid Name With No URL"
    )


def test_module_level_clean_byline_delegates_to_instance():
    from src.utils.byline_cleaner import clean_byline

    assert clean_byline("By Alex Smith") == ["Alex Smith"]


def test_extract_authors_supports_last_first_format():
    cleaner = BylineCleaner(enable_telemetry=False)

    assert cleaner._extract_authors("Doe, John") == ["John Doe"]


def test_extract_authors_smart_processing_multiple_parts():
    cleaner = BylineCleaner(enable_telemetry=False)

    authors = cleaner._extract_authors("Jane Doe, Editor, jdoe@example.com")

    assert authors[0] == "__SMART_PROCESSED__"
    assert "Jane Doe" in authors[1:]
    assert any(part.startswith("jdoe") for part in authors[1:])


def test_clean_author_name_strips_titles_and_normalizes():
    cleaner = BylineCleaner(enable_telemetry=False)

    with (
        patch.object(cleaner, "_is_publication_name", return_value=False),
        patch.object(cleaner, "_is_url_fragment", return_value=False),
        patch.object(
            cleaner,
            "_filter_organization_words",
            side_effect=lambda value: value,
        ),
    ):
        result = cleaner._clean_author_name("JANE DOE, Staff Writer")

    assert result == "Jane Doe"


def test_format_result_deduplicates_wire_services_and_authors():
    cleaner = BylineCleaner(enable_telemetry=False)
    cleaner._detected_wire_services = [
        "The Associated Press",
        "CNN NewsSource",
        "The Associated Press",
    ]
    cleaner._current_source_name = None

    result = cleaner._format_result(
        ["The Associated Press", "Jane Doe", "John Smith"],
        return_json=True,
    )

    assert isinstance(result, dict)
    assert result["authors"] == ["Jane Doe", "John Smith"]
    assert result["wire_services"] == [
        "The Associated Press",
        "CNN NewsSource",
    ]
    assert result["primary_wire_service"] == "The Associated Press"
    assert result["is_wire_content"] is True


def test_is_publication_name_respects_multiword_requirement():
    cleaner = BylineCleaner(enable_telemetry=False)

    with (
        patch.object(
            cleaner,
            "get_publication_names",
            return_value={"springfield news-leader"},
        ),
        patch.object(cleaner, "get_organization_names", return_value=set()),
    ):
        assert cleaner._is_publication_name("Springfield News-Leader") is True
        assert cleaner._is_publication_name("Reporter") is False


def test_clean_byline_filters_dynamic_publication_with_json_result():
    cleaner = BylineCleaner(enable_telemetry=False)

    with (
        patch.object(
            cleaner,
            "get_publication_names",
            return_value={"springfield community voice"},
        ),
        patch.object(
            cleaner,
            "get_organization_names",
            return_value=set(),
        ),
    ):
        result = cleaner.clean_byline(
            "Springfield Community Voice",
            return_json=True,
        )

    assert isinstance(result, dict)
    assert result["authors"] == []
    assert result["wire_services"] == []
    assert result["is_wire_content"] is False


def test_clean_byline_with_source_name_triggers_removal_branch():
    cleaner = BylineCleaner(enable_telemetry=False)

    result = cleaner.clean_byline(
        "By Jane Doe Metro Ledger",
        source_name="Metro Ledger",
    )

    assert result == ["Jane Doe"]


def test_is_url_fragment_and_extraction_behavior():
    cleaner = BylineCleaner(enable_telemetry=False)

    assert cleaner._is_url_fragment("www.example.com") is True
    assert cleaner._is_url_fragment("Jane Doe") is False
    assert (
        cleaner._extract_name_from_url_fragment("Jack Silberberg • .Com")
        == "Jack Silberberg"
    )


def test_deduplicate_authors_prefers_non_hyphenated_variants():
    cleaner = BylineCleaner(enable_telemetry=False)

    authors = cleaner._deduplicate_authors(
        ["Mary-Anne Smith", "Mary Anne Smith", "Another Author"]
    )

    assert authors == ["Mary Anne Smith", "Another Author"]


def test_validate_authors_filters_titles_and_short_entries():
    cleaner = BylineCleaner(enable_telemetry=False)

    result = cleaner._validate_authors(["Jane Doe", "Staff", "A", ""])

    assert result == ["Jane Doe"]


def test_remove_patterns_strips_emails_and_handles():
    cleaner = BylineCleaner(enable_telemetry=False)

    text = "Jane Doe jane@example.com (555)123-4567 @janedoe"

    assert cleaner._remove_patterns(text) == "Jane Doe"


def test_identify_part_type_classifications():
    cleaner = BylineCleaner(enable_telemetry=False)

    assert cleaner._identify_part_type("Photo by John Doe") == "photo_credit"
    assert cleaner._identify_part_type("jane@example.com") == "email"
    assert cleaner._identify_part_type("Senior Editor II") == "title"
    assert cleaner._identify_part_type("Community Impact Team") == "mixed"
    assert cleaner._identify_part_type("Jane Doe") == "name"


def test_extract_authors_handles_and_separation():
    cleaner = BylineCleaner(enable_telemetry=False)

    assert cleaner._extract_authors("Jane Doe and John Smith") == [
        "Jane Doe",
        "John Smith",
    ]


def test_extract_authors_returns_marker_without_names():
    cleaner = BylineCleaner(enable_telemetry=False)

    authors = cleaner._extract_authors(
        "Senior Editor II, Managing Director III"
    )

    assert authors == ["__SMART_PROCESSED__"]


def test_filter_organization_words_removes_org_terms():
    cleaner = BylineCleaner(enable_telemetry=False)

    with patch.object(cleaner, "_get_known_name_patterns", return_value={}):
        result = cleaner._filter_organization_words(
            "Jane Doe Communications Department"
        )

    assert result == "Jane Doe"


def test_filter_organization_words_removes_multiword_publication():
    cleaner = BylineCleaner(enable_telemetry=False)

    with (
        patch.object(
            cleaner,
            "get_publication_names",
            return_value={"springfield community voice"},
        ),
        patch.object(cleaner, "get_organization_names", return_value=set()),
        patch.object(cleaner, "_get_known_name_patterns", return_value={}),
    ):
        result = cleaner._filter_organization_words(
            "Jane Doe Springfield Community Voice"
        )

    assert result == "Jane Doe"


def test_filter_organization_words_returns_empty_when_only_organization():
    cleaner = BylineCleaner(enable_telemetry=False)

    with (
        patch.object(
            cleaner,
            "get_publication_names",
            return_value={"springfield community voice"},
        ),
        patch.object(cleaner, "get_organization_names", return_value=set()),
        patch.object(cleaner, "_get_known_name_patterns", return_value={}),
    ):
        result = cleaner._filter_organization_words(
            "Springfield Community Voice"
        )

    assert result == ""


def test_matches_known_name_pattern_detects_frequency():
    cleaner = BylineCleaner(enable_telemetry=False)

    patterns = {
        "jane_doe": 2,
        "first_jane": 5,
        "last_doe": 3,
    }

    assert cleaner._matches_known_name_pattern(["Jane", "Doe"], patterns)
    assert cleaner._matches_known_name_pattern(["Alex"], patterns) is False


def test_matches_known_name_pattern_uses_first_name_threshold():
    cleaner = BylineCleaner(enable_telemetry=False)

    patterns = {"first_jane": 5}

    assert cleaner._matches_known_name_pattern(["Jane", "Smith"], patterns)


def test_matches_known_name_pattern_uses_last_name_threshold():
    cleaner = BylineCleaner(enable_telemetry=False)

    patterns = {"last_doe": 3}

    assert cleaner._matches_known_name_pattern(["Alex", "Doe"], patterns)


def test_normalize_capitalization_handles_prefixes_and_suffixes():
    cleaner = BylineCleaner(enable_telemetry=False)

    assert (
        cleaner._normalize_capitalization("maria DE LA CRUZ jr.")
        == "Maria de la Cruz Jr."
    )
    assert (
        cleaner._normalize_capitalization("ANNE-MARIE SMITH")
        == "Anne-Marie Smith"
    )


def test_format_result_skips_wire_matching_source():
    cleaner = BylineCleaner(enable_telemetry=False)
    cleaner._detected_wire_services = ["Local Wire"]
    cleaner._current_source_name = "Local Wire"

    with patch.object(
        cleaner,
        "_is_wire_service_from_own_source",
        return_value=True,
    ):
        result = cleaner._format_result(
            ["Local Wire", "Jane Doe"],
            return_json=True,
        )

    assert isinstance(result, dict)
    assert result["wire_services"] == []
    assert result["authors"] == ["Local Wire", "Jane Doe"]
    assert result["is_wire_content"] is False


def test_clean_bulk_bylines_invokes_cleaner_per_entry():
    cleaner = BylineCleaner(enable_telemetry=False)

    with patch.object(
        cleaner,
        "clean_byline",
        side_effect=[["Jane Doe"], ["John Smith"]],
    ) as mock_clean:
        results = cleaner.clean_bulk_bylines(["By Jane Doe", "By John Smith"])

    assert results == [["Jane Doe"], ["John Smith"]]
    assert mock_clean.call_count == 2


def test_is_url_fragment_detects_malformed_www():
    cleaner = BylineCleaner(enable_telemetry=False)

    assert cleaner._is_url_fragment("Www..Com") is True


def test_clean_byline_handles_empty_input_returns_empty_json():
    cleaner = BylineCleaner(enable_telemetry=False)

    result = cleaner.clean_byline("", return_json=True)

    assert isinstance(result, dict)
    assert result["authors"] == []
    assert result["is_wire_content"] is False


def test_get_known_name_patterns_returns_empty_on_db_error():
    cleaner = BylineCleaner(enable_telemetry=False)

    with patch(
        "sqlite3.connect",
        side_effect=Exception("db error"),
    ):
        assert cleaner._get_known_name_patterns() == {}


def test_clean_byline_module_function_uses_class():
    from src.utils import byline_cleaner as module

    with patch.object(module, "BylineCleaner") as mock_cleaner:
        instance = mock_cleaner.return_value
        instance.clean_byline.return_value = ["Jane Doe"]

        result = module.clean_byline("By Jane Doe")

    instance.clean_byline.assert_called_once_with("By Jane Doe", False)
    assert result == ["Jane Doe"]


def test_clean_byline_records_wire_passthrough_telemetry():
    cleaner = BylineCleaner(enable_telemetry=True)
    telemetry = cleaner.telemetry

    with (
        patch.object(telemetry, "start_cleaning_session") as mock_start,
        patch.object(telemetry, "log_transformation_step") as mock_log,
        patch.object(telemetry, "finalize_cleaning_session") as mock_finalize,
    ):
        result = cleaner.clean_byline("Associated Press", return_json=True)

    assert isinstance(result, dict)
    assert result["is_wire_content"] is True
    mock_start.assert_called_once()
    assert mock_log.call_count >= 1
    log_kwargs = mock_log.call_args_list[0].kwargs
    assert log_kwargs["step_name"] == "wire_service_detection"
    assert log_kwargs["transformation_type"] == "classification"
    mock_finalize.assert_called_once()
    finalize_kwargs = mock_finalize.call_args.kwargs
    assert finalize_kwargs["cleaning_method"] == "wire_service_passthrough"
    assert finalize_kwargs["final_authors"] == ["Associated Press"]


def test_clean_byline_error_path_logs_telemetry():
    cleaner = BylineCleaner(enable_telemetry=True)
    cleaner._extract_authors = MagicMock(side_effect=RuntimeError("explode"))
    telemetry = cleaner.telemetry

    with (
        patch.object(telemetry, "start_cleaning_session") as mock_start,
        patch.object(telemetry, "log_transformation_step") as mock_log,
        patch.object(telemetry, "finalize_cleaning_session") as mock_finalize,
        patch.object(telemetry, "log_error") as mock_error,
    ):
        result = cleaner.clean_byline("By Jane Doe", return_json=True)

    assert isinstance(result, dict)
    assert result["authors"] == []
    mock_start.assert_called_once()
    assert mock_log.call_count >= 1
    mock_error.assert_called_once()
    error_args, _ = mock_error.call_args
    assert "Cleaning error" in error_args[0]
    finalize_kwargs = mock_finalize.call_args.kwargs
    assert finalize_kwargs["cleaning_method"] == "error_fallback"
    assert finalize_kwargs["final_authors"] == []
