from src.utils.discovery_outcomes import DiscoveryOutcome, DiscoveryResult


def test_discovery_result_success_properties():
    result = DiscoveryResult(
        outcome=DiscoveryOutcome.NEW_ARTICLES_FOUND,
        articles_found=5,
        articles_new=3,
        metadata={"source": "rss"},
    )

    assert result.is_success is True
    assert result.is_content_success is True
    assert result.is_technical_failure is False

    data = result.to_dict()
    assert data["outcome"] == DiscoveryOutcome.NEW_ARTICLES_FOUND.value
    assert data["articles_new"] == 3
    assert data["is_success"] is True
    assert data["source"] == "rss"


def test_discovery_result_failure_flags():
    result = DiscoveryResult(
        outcome=DiscoveryOutcome.TIMEOUT,
        error_details="connection timed out",
        http_status=504,
    )

    assert result.is_success is False
    assert result.is_content_success is False
    assert result.is_technical_failure is True

    data = result.to_dict()
    assert data["http_status"] == 504
    assert data["is_technical_failure"] is True
