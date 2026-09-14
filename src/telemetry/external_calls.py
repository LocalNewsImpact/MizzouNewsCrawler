"""A row per call to somebody else's service.

WHY A CONTEXT MANAGER and not a `record()` you call afterwards: a call
site that has to remember to record is a call site that will eventually
not, and the failures are exactly the calls that must not go missing --
an exception path is the one a `record()` after the call never reaches.
Wrapping the call means the row is written whether it returns or raises,
and the outcome is derived from what actually happened rather than from
what the caller believed happened.

    with recorder.call("mediacloud", "story_list", subject_id=a.id) as c:
        stories = api.story_list(...)

`c` carries what the caller knows and the wrapper cannot see -- the wait
the rate limiter imposed, the attempt number, anything worth keeping in
`meta`.

WHAT IT IS FOR. Not cost: MediaCloud is free. The questions are whether
we are being a good neighbour (`waited_ms` against the configured rate),
whether the service is up (failures arriving together), and whether we
are being blocked (429 and 403, which need a different response from a
timeout). See the migration for the measurement behind each.

TELEMETRY MUST NOT BREAK THE CALLER. A failure to write a row is logged
at error and swallowed -- the work is the point and the observation is
not. It is logged loudly rather than passed over, because silence here
would be indistinguishable from making no calls at all, which is the
exact confusion this table exists to end.
"""

from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

from sqlalchemy import text

LOG = logging.getLogger(__name__)

#: The outcome classes. Three, because the response to each differs: a
#: rate limit is backed off, an outage is waited out, a client error is a
#: defect in us.
OK = "ok"
API_ERROR = "api_error"
ERROR = "error"

_INSERT = text("""
    INSERT INTO external_api_calls
        (service, operation, duration_ms, waited_ms, outcome,
         status_code, error_class, attempt, subject_type, subject_id,
         dataset_id, meta)
    VALUES
        (:service, :operation, :duration_ms, :waited_ms, :outcome,
         :status_code, :error_class, :attempt, :subject_type, :subject_id,
         :dataset_id, :meta)
    """)


@dataclass
class Call:
    """What one call knows about itself while it is being made."""

    service: str
    operation: str
    subject_type: str | None = None
    subject_id: str | None = None
    dataset_id: str | None = None
    attempt: int = 1
    #: What a rate limiter held back before the call was allowed. The
    #: politeness evidence: a run that never waits is a limiter that is
    #: not binding.
    waited_ms: int | None = None
    #: The HTTP status, where the caller can see one. An exception class
    #: alone cannot tell a 429 from a 500.
    status_code: int | None = None
    #: Set when the caller knows better than the exception -- a client
    #: that returns an error rather than raising it.
    outcome: str | None = None
    error_class: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def failed(
        self,
        outcome: str,
        *,
        status_code: int | None = None,
        error_class: str | None = None,
    ) -> None:
        """Record a failure the call returned rather than raised.

        `MediaCloudDetector.detect` catches its own exceptions and turns
        them into a status string, so by the time the wrapper's `except`
        would see one there is nothing left to catch. Without this, every
        such call would be recorded `ok`.
        """
        self.outcome = outcome
        if status_code is not None:
            self.status_code = status_code
        if error_class is not None:
            self.error_class = error_class


class ExternalCallRecorder:
    """Writes the rows. One per call, on the way out."""

    def __init__(self, engine, *, logger: logging.Logger | None = None) -> None:
        self.engine = engine
        self.log = logger or LOG

    @contextmanager
    def call(self, service: str, operation: str, **kwargs: Any) -> Iterator[Call]:
        record = Call(service=service, operation=operation, **kwargs)
        started = time.monotonic()
        try:
            yield record
        except BaseException as exc:
            # The row is written for the failure too -- these are the
            # calls that matter most, and they are the ones a `record()`
            # after the call would never reach.
            record.outcome = ERROR
            record.error_class = type(exc).__name__
            if record.status_code is None:
                record.status_code = _status_code_of(exc)
            self._write(record, _elapsed_ms(started))
            raise
        else:
            # `failed()` may have been called inside the block, for a
            # client that returns its errors.
            if record.outcome is None:
                record.outcome = OK
            self._write(record, _elapsed_ms(started))

    def _write(self, record: Call, duration_ms: int) -> None:
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    _INSERT,
                    {
                        "service": record.service,
                        "operation": record.operation,
                        "duration_ms": duration_ms,
                        "waited_ms": record.waited_ms,
                        "outcome": record.outcome,
                        "status_code": record.status_code,
                        "error_class": record.error_class,
                        "attempt": record.attempt,
                        "subject_type": record.subject_type,
                        "subject_id": record.subject_id,
                        "dataset_id": record.dataset_id,
                        "meta": json.dumps(record.meta) if record.meta else None,
                    },
                )
        except Exception:
            # Loud, not silent: no rows and no complaint reads exactly
            # like making no calls, which is the confusion this table
            # exists to end.
            self.log.error(
                "could not record %s.%s call telemetry",
                record.service,
                record.operation,
                exc_info=True,
            )


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _status_code_of(exc: BaseException) -> int | None:
    """The HTTP status behind an exception, when it carries one.

    Clients disagree on where they put it: some set `status_code` on the
    exception, others hang a response object off it. Both are read,
    because a 429 recorded as "some exception" is a blocking signal
    thrown away.
    """
    code = getattr(exc, "status_code", None)
    if code is None:
        code = getattr(getattr(exc, "response", None), "status_code", None)
    return code if isinstance(code, int) else None
