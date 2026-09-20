"""Which pool of hosts an extraction worker draws from.

The work queue hands a worker one domain and at most three articles, then
rotates, and one Selenium driver serves all of them. Recycling that driver
clears every authenticated session it holds, so a worker that fetches both
credentialed and anonymous hosts has to choose between two bad options: recycle
on the ordinary schedule and pay a fresh login on each paywalled host's next
turn, or hold the driver longer and stop rotating for the anonymous hosts,
which is the one thing rotation exists to do.

Segregating the work removes the choice. A worker declares which kind of host
it handles, asks the queue for that kind only, and takes the driver limit that
kind needs.

ONE setting decides both, because they cannot disagree: a worker that asks for
credentialed domains and recycles every ten fetches is the churn this exists to
stop, and a worker that holds its driver for fifty fetches while serving
anonymous domains is the fingerprint the limit exists to avoid.

`MIXED` is the default and the historical behaviour. It is not a third kind of
worker -- it is the absence of segregation, and it stays the default because
switching the pipeline to `ANONYMOUS` without an authenticated worker running
leaves credentialed work with nobody to claim it. See
docs/AN_AUTHENTICATED_WORKER_IS_PROVISIONED.md.
"""

from __future__ import annotations

import os

#: Draws only credentialed domains (`sources.requires_login`), and keeps its
#: driver for `SELENIUM_DRIVER_REUSE_LIMIT_AUTHENTICATED` fetches.
AUTHENTICATED = "authenticated"
#: Draws only domains that need no login, and rotates on the ordinary limit.
ANONYMOUS = "anonymous"
#: Draws both, and rotates on the ordinary limit. The historical behaviour.
MIXED = "mixed"

POOLS = (AUTHENTICATED, ANONYMOUS, MIXED)

ENV_VAR = "EXTRACTION_WORKER_POOL"


def worker_pool(environ: dict[str, str] | None = None) -> str:
    """The pool this process serves, from the environment.

    An unrecognised value is MIXED rather than an error. A worker is a batch
    job: refusing to start would leave the backlog untouched and report a
    failure the operator reads as "extraction is broken", where mixing is
    exactly what every worker did before this setting existed.
    """
    env = os.environ if environ is None else environ
    value = (env.get(ENV_VAR) or "").strip().lower()
    return value if value in POOLS else MIXED


def requires_login_filter(pool: str) -> bool | None:
    """What this pool asks the queue for, as `WorkRequest.requires_login`.

    `None` means "do not filter", which is not the same as False: False is an
    assertion that this worker handles anonymous hosts ONLY, and is what stops
    an ordinary worker signing in to a paywalled publisher because it happened
    to ask first.
    """
    if pool == AUTHENTICATED:
        return True
    if pool == ANONYMOUS:
        return False
    return None


def holds_logins(pool: str) -> bool:
    """Whether this worker's driver is expected to carry a login.

    Only the authenticated pool does. It is a property of the POOL, not of what
    the driver has managed to sign in to so far: keying it on
    `ContentExtractor._authenticated_domains` was the first attempt, and since
    that set accumulates for the life of the process, one successful login
    stopped rotating every anonymous domain the same worker went on to fetch.
    """
    return pool == AUTHENTICATED
