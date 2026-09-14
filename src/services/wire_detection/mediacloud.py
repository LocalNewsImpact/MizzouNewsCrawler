"""MediaCloud-based wire detection helpers."""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Iterator, Optional, Protocol, cast
from urllib.parse import urlparse


class SearchApiProtocol(Protocol):
    def story_list(
        self, **kwargs: Any
    ) -> tuple[list[dict], Any]:  # pragma: no cover - protocol definition
        ...


class _FallbackAPIResponseError(Exception):
    """Fallback error used when mediacloud dependency is missing."""

    status_code: int

    def __init__(self, message: str = "", status_code: int = 0) -> None:
        super().__init__(message)
        self.status_code = status_code


class _FallbackMCException(Exception):
    """Fallback exception mirroring mediacloud.MCException."""

    pass


APIResponseError: type[_FallbackAPIResponseError] = _FallbackAPIResponseError
MCException: type[_FallbackMCException] = _FallbackMCException
_SearchApiFactory: Callable[[str], SearchApiProtocol] | None = None


try:  # pragma: no cover - import guard exercised via unit tests
    from mediacloud.api import SearchApi as _ImportedSearchApi
    from mediacloud.error import APIResponseError as _ImportedAPIResponseError
    from mediacloud.error import MCException as _ImportedMCException
except (
    ModuleNotFoundError
):  # pragma: no cover - exercised in CI without dependency installed
    pass
else:
    APIResponseError = cast(
        "type[_FallbackAPIResponseError]", _ImportedAPIResponseError
    )
    MCException = cast("type[_FallbackMCException]", _ImportedMCException)
    _SearchApiFactory = _ImportedSearchApi  # type: ignore[assignment]


class MissingDependencyError(RuntimeError):
    """Raised when the mediacloud client library is not installed."""

    pass


DEFAULT_RATE_PER_MINUTE = 2.0
LOG = logging.getLogger(__name__)
_TOKEN_INITIALISED = False
_RESOLVED_TOKEN: Optional[str] = None


def _first_nonempty_env(keys: Iterable[str]) -> Optional[str]:
    for key in keys:
        value = os.getenv(key)
        if value:
            stripped = value.strip()
            if stripped:
                return stripped
    return None


def resolve_api_token(
    *,
    env_var: str = "MEDIACLOUD_API_TOKEN",
    secret_env_keys: tuple[str, ...] = (
        "MEDIACLOUD_SECRET_NAME",
        "MEDIACLOUD_API_SECRET_NAME",
    ),
    project_env_keys: tuple[str, ...] = (
        "GCP_PROJECT",
        "GOOGLE_CLOUD_PROJECT",
        "GCLOUD_PROJECT",
    ),
    logger: logging.Logger | None = None,
) -> Optional[str]:
    """Resolve the MediaCloud API token from environment or Secret Manager."""

    log = logger or LOG

    global _TOKEN_INITIALISED, _RESOLVED_TOKEN

    if _TOKEN_INITIALISED:
        return _RESOLVED_TOKEN

    token: Optional[str] = None

    existing = os.getenv(env_var)
    if existing and existing.strip():
        token = existing.strip()
    else:
        secret_name = _first_nonempty_env(secret_env_keys)
        if secret_name:
            try:
                from google.cloud import secretmanager  # type: ignore
            except Exception as exc:  # pragma: no cover - optional dependency
                log.warning(
                    "MediaCloud secret configured via %s but google-cloud-secret-manager is unavailable: %s",
                    ", ".join(secret_env_keys),
                    exc,
                )
            else:
                resource_name = secret_name
                if "/" not in resource_name:
                    project = _first_nonempty_env(project_env_keys)
                    if not project:
                        log.warning(
                            "MediaCloud secret '%s' configured but project env (%s) not set",
                            secret_name,
                            ", ".join(project_env_keys),
                        )
                        resource_name = ""
                    else:
                        resource_name = (
                            f"projects/{project}/secrets/{secret_name}/versions/latest"
                        )

                if resource_name:
                    try:
                        client = secretmanager.SecretManagerServiceClient()
                        response = client.access_secret_version(
                            request={"name": resource_name}
                        )
                        candidate = response.payload.data.decode("utf-8").strip()
                        if candidate:
                            token = candidate
                        else:
                            log.warning(
                                "MediaCloud secret '%s' returned an empty payload",
                                resource_name,
                            )
                    except Exception as exc:  # pragma: no cover - network/API failure
                        log.error(
                            "Failed to load MediaCloud API token from Secret Manager '%s': %s",
                            resource_name,
                            exc,
                        )

    if token:
        os.environ.setdefault(env_var, token)

    _RESOLVED_TOKEN = token
    _TOKEN_INITIALISED = True
    return _RESOLVED_TOKEN


@dataclass
class MediaCloudArticle:
    """Minimal article metadata required for MediaCloud lookups."""

    article_id: str
    source: str
    url: str
    title: str
    extracted_at: Optional[datetime]

    @property
    def host(self) -> str:
        return normalize_host(self.url)


@dataclass
class DetectionResult:
    """Structured result returned by ``MediaCloudDetector``."""

    article: MediaCloudArticle
    query: str
    story_count: int
    matched_story_count: int
    matched_hosts: list[str]
    matched_story_ids: list[str]
    status: str
    queried_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def has_matches(self) -> bool:
        return self.matched_story_count > 0

    def to_metadata(self) -> dict:
        """Return JSON-serialisable metadata for storage in the DB."""

        return {
            "article_id": self.article.article_id,
            "source": self.article.source,
            "query": self.query,
            "story_count": self.story_count,
            "matched_story_count": self.matched_story_count,
            "matched_hosts": list(self.matched_hosts),
            "matched_story_ids": list(self.matched_story_ids),
            "status": self.status,
            "queried_at": self.queried_at.isoformat(),
        }

    def to_wire_payload(self) -> dict:
        """Build a wire attribution payload compatible with ``articles.wire``."""

        payload = {
            "provider": "mediacloud",
            "detection_method": "headline_duplicate",
            "matched_hosts": list(self.matched_hosts),
            "matched_story_ids": list(self.matched_story_ids),
            "matched_story_count": self.matched_story_count,
            "story_count": self.story_count,
            "queried_at": self.queried_at.isoformat(),
            "query": self.query,
        }
        return payload


class RateLimiter:
    """Lightweight token bucket enforcing a minimum call interval."""

    def __init__(self, calls_per_minute: float) -> None:
        if calls_per_minute <= 0:
            raise ValueError("calls_per_minute must be positive")
        self._min_interval = 60.0 / calls_per_minute
        self._last_call: Optional[float] = None

    def wait(self) -> int:
        """Hold the caller back, and say for how long in milliseconds.

        It returned None, so how hard the limiter was working could not
        be observed -- and a limiter that never actually waits is a rate
        nobody is enforcing. The number is recorded on every call, which
        makes politeness a measurement rather than a claim.
        """
        if self._last_call is None:
            return 0
        elapsed = time.monotonic() - self._last_call
        sleep_for = self._min_interval - elapsed
        if sleep_for > 0:
            time.sleep(sleep_for)
            return int(sleep_for * 1000)
        return 0

    def record(self) -> None:
        self._last_call = time.monotonic()


def normalize_host(url: str) -> str:
    try:
        netloc = urlparse(url).netloc.lower()
    except ValueError:
        netloc = ""
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def parse_iso8601(value: str) -> Optional[datetime]:
    if not value:
        return None
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _status_code_of(exc: Exception) -> int | str:
    """The HTTP status behind an ``APIResponseError``, whichever class it is.

    The fallback defined above carries ``status_code``; the real
    ``mediacloud.error.APIResponseError`` takes ``(response, params, data)``
    and carries ``response.status_code`` instead. Reading the attribute
    directly therefore raised AttributeError from inside the handler
    whenever the dependency was installed -- which is production -- so a
    rate-limited lookup crashed the caller rather than returning
    ``api_error:429``. Every unit test passed, because without the package
    installed the fallback has the attribute.
    """

    code = getattr(exc, "status_code", None)
    if code is None:
        code = getattr(getattr(exc, "response", None), "status_code", None)
    return code if code is not None else "unknown"


def build_query(title: str) -> str:
    escaped = title.replace('"', '\\"')
    return f'"{escaped}"'


def summarize_matches(
    base: MediaCloudArticle,
    stories: Iterable[dict],
) -> tuple[int, list[str], list[str]]:
    matched_hosts: list[str] = []
    matched_story_ids: list[str] = []
    base_host = base.host
    for story in stories:
        story_url = story.get("url") or ""
        story_host = normalize_host(story_url)
        if not story_host or story_host == base_host:
            continue
        if story_host not in matched_hosts:
            matched_hosts.append(story_host)
        matched_story_ids.append(str(story.get("id")))
    return len(matched_story_ids), matched_hosts, matched_story_ids


class _NotRecorded:
    """Accepts everything a `Call` accepts and keeps none of it."""

    def __init__(self) -> None:
        self.meta: dict[str, Any] = {}

    def failed(self, *args: Any, **kwargs: Any) -> None:
        return None


class MediaCloudDetector:
    """Perform MediaCloud headline matching with rate limiting."""

    def __init__(
        self,
        search_api: SearchApiProtocol,
        *,
        rate_limiter: RateLimiter | None = None,
        logger: logging.Logger | None = None,
        call_recorder: Any | None = None,
    ) -> None:
        self.search_api = search_api
        self.rate_limiter = rate_limiter or RateLimiter(DEFAULT_RATE_PER_MINUTE)
        self.log = logger or LOG
        # Optional so a unit test and an offline run need no database.
        # Absent, nothing is recorded and nothing breaks -- which is why
        # the wiring is asserted by a test rather than assumed.
        self.call_recorder = call_recorder

    @classmethod
    def from_token(
        cls,
        token: str,
        *,
        rate_per_minute: float = DEFAULT_RATE_PER_MINUTE,
        logger: logging.Logger | None = None,
        call_recorder: Any | None = None,
    ) -> MediaCloudDetector:
        if not token:
            raise ValueError("MediaCloud API token is required")
        factory = _SearchApiFactory
        if factory is None:
            raise MissingDependencyError(
                "The 'mediacloud' package is not installed. Install the optional dependency "
                "with `pip install mediacloud` to enable MediaCloud detectors."
            )
        try:
            search_api = factory(token)
        except MCException as exc:  # pragma: no cover - constructor rarely fails
            raise RuntimeError(
                f"Failed to initialise MediaCloud client: {exc}"
            ) from exc
        return cls(
            search_api=search_api,
            rate_limiter=RateLimiter(rate_per_minute),
            logger=logger,
            # Passed through rather than defaulted here: production is
            # the only caller that has an engine, and a constructor that
            # quietly dropped this would leave the recording wired up
            # everywhere except where it runs.
            call_recorder=call_recorder,
        )

    @contextmanager
    def _recorded_call(
        self, article: MediaCloudArticle, waited_ms: int
    ) -> Iterator[Any]:
        """The call's telemetry row, or a stand-in that keeps the shape.

        `detect` is written once, against an object with `failed()` and
        `meta`. Without a recorder it gets one that discards -- rather
        than `detect` growing two code paths, one of which would then be
        the only one the offline tests exercise.
        """
        if self.call_recorder is None:
            yield _NotRecorded()
            return
        with self.call_recorder.call(
            "mediacloud",
            "story_list",
            subject_type="article",
            subject_id=article.article_id,
            waited_ms=waited_ms,
        ) as call:
            yield call

    def detect(self, article: MediaCloudArticle) -> DetectionResult:
        query = build_query(article.title)
        self.log.debug(
            "Submitting MediaCloud query '%s' for article %s", query, article.article_id
        )

        # What the limiter held back, measured rather than assumed: a
        # run that never waits is a rate nobody is enforcing.
        waited_ms = self.rate_limiter.wait()
        stories: list[dict]
        with self._recorded_call(article, waited_ms) as call:
            try:
                stories = self._story_list(article, query)
                status = "ok"
            except APIResponseError as exc:
                self.log.warning(
                    "MediaCloud API error for article %s: %s", article.article_id, exc
                )
                code = _status_code_of(exc)
                status = f"api_error:{code}"
                stories = []
                # The detector answers with a string rather than raising,
                # so the recorder is told: without this the call is
                # written `ok` and a 429 disappears.
                call.failed(
                    "api_error",
                    status_code=code if isinstance(code, int) else None,
                    error_class=type(exc).__name__,
                )
            except Exception as exc:  # noqa: BLE001
                self.log.exception(
                    "Unexpected MediaCloud failure for article %s", article.article_id
                )
                status = f"error:{exc.__class__.__name__}"
                stories = []
                call.failed("error", error_class=type(exc).__name__)
            finally:
                self.rate_limiter.record()
            call.meta["story_count"] = len(stories)

        story_count = len(stories)
        matched_count, matched_hosts, matched_story_ids = summarize_matches(
            article, stories
        )
        self.log.debug(
            "MediaCloud returned %d stories, %d matched hosts",
            story_count,
            len(matched_hosts),
        )

        return DetectionResult(
            article=article,
            query=query,
            story_count=story_count,
            matched_story_count=matched_count,
            matched_hosts=matched_hosts,
            matched_story_ids=matched_story_ids,
            status=status,
        )

    def _story_list(
        self,
        article: MediaCloudArticle,
        query: str,
        *,
        page_size: int = 100,
    ) -> list[dict]:
        extracted_at = article.extracted_at
        if extracted_at is None:
            start_date = end_date = datetime.utcnow().date()
        else:
            extracted_at = extracted_at.astimezone(timezone.utc)
            start_date = (extracted_at - timedelta(days=1)).date()
            end_date = (extracted_at + timedelta(days=1)).date()

        stories, _ = self.search_api.story_list(
            query=query,
            start_date=start_date,
            end_date=end_date,
            page_size=page_size,
        )
        return stories


def ensure_timezone(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
