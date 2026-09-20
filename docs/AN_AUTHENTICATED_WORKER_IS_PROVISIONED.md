# A credentialed host needs a worker of its own

The work queue hands a worker one domain and at most three articles per
request, then rotates. That is what keeps a publisher from seeing a hundred
consecutive requests, and it is correct. It also means a credentialed host is
visited in short bursts — and the Selenium driver that holds its login is
shared between every domain that worker touches.

`ContentExtractor._authenticated_domains` is cleared every time that driver is
recycled, and the pipeline sets `SELENIUM_DRIVER_REUSE_LIMIT=3` (lowered from 10
to stay under PerimeterX). So a worker working through mixed domains signs in to
a paywalled host on roughly every visit. Across the 1,038 WSU links behind seven
paywalled publishers that is a great many logins, each one a login form
submitted to a publisher who is watching — and `cascadiadaily.com` enforces a
lockout counter.

## Why the obvious fix is wrong

Raise the limit when the driver holds a session:

```python
if cls._authenticated_domains:
    return cls._shared_driver_reuse_limit_authenticated
```

`_authenticated_domains` accumulates for the life of the process and is only
ever cleared on recycle, so the first successful login raises the limit for
**every** fetch after it — including the anonymous domains in the same batch,
which were getting rotation precisely so a publisher cannot fingerprint one
machine working steadily through its site. That trades away the thing the limit
exists for, on hosts that never asked.

The limit is not the problem. Mixing the two kinds of work in one driver is.

## The shape

A worker handles one kind of host and says so, and each kind keeps the setting
it needs:

| pool | asks the queue for | reuse limit | why |
| --- | --- | --- | --- |
| `anonymous` | `requires_login=False` | 3 | rotation is the point |
| `authenticated` | `requires_login=True` | 50 | the session identifies us anyway; recycling only costs logins |
| `mixed` | no filter | 3 | the historical behaviour, and the default |

Both still rotate *between* domains of their own kind. The cooldowns, the
per-domain caps and the failure pauses are unchanged — segregation is about
which pool a worker draws from, not about how politely it draws.

**One setting decides both**, because they cannot disagree: a worker that asks
for credentialed domains and recycles every three fetches is the churn this
exists to stop, and a worker that holds its driver for fifty fetches while
serving anonymous domains is the fingerprint the limit exists to avoid.
`EXTRACTION_WORKER_POOL` is that setting; `src/utils/worker_pool.py` is the one
place it is read.

`mixed` is the default on purpose. An unrecognised value resolves to it rather
than failing, because a worker is a batch job: refusing to start would leave the
backlog untouched and report a failure an operator reads as "extraction is
broken".

## What each part does

**The queue filter.** `WorkRequest.requires_login` reaches
`_get_available_domains`, which appends `AND s.requires_login = :requires_login`
only when it is set — appended rather than written as
`(:requires_login IS NULL OR ...)`, which Postgres cannot plan, for the same
reason the dataset filter is.

**`False` is an assertion, not an absent filter.** This is the part that makes
the rest work. Adding an authenticated worker changes nothing on its own: a
credentialed domain is offered to whichever worker asks first, so an ordinary
worker picks it up and logs in anyway. `news-pipeline-template`'s
`extraction-step` therefore takes a `worker-pool` parameter, and every ordinary
caller passes `anonymous`:

- the pipeline DAG's `extract-content` task
- `dataset-extraction`

**Needing a login is not being able to perform one.** When asked for
credentialed hosts the queue also requires `auth_type` and `auth_secret_name`.
Without that check the authenticated worker is handed a host it cannot sign in
to, fetches it anonymously, and stores whatever the paywall served — a failure
that arrives as content rather than as an error.

**The hole that leaves, and where it shows.** A host with `requires_login` and
no credentials is excluded from the anonymous pool on `requires_login = false`
and from the authenticated pool on the credentials check. It is in neither, and
nothing fetches it. That is a hole, not a resolution, so `/stats` names it:

| field | says |
| --- | --- |
| `credentialed_available` | links at `article` on a host that needs a login, whatever its state |
| `credentialed_claimable` | of those, what an authenticated worker could actually be served |
| `credentialed_unclaimable` | host → why the rest cannot be (paused, or no credentials) |
| `pool_last_request_age` | pool → seconds since a worker asked for it |

A missing `authenticated` key with `credentialed_claimable` above zero is the
starvation case: work is ready and nobody has come for it. `get_stats` logs a
warning when it sees exactly that, because a count that never moves is not a
signal anyone reads.

```bash
kubectl exec -n production deploy/work-queue -- \
  curl -s localhost:8080/stats | python -m json.tool
```

**The worker.** `k8s/argo/authenticated-extraction-workflow.yaml`. One replica,
`worker-pool=authenticated`, the slow request profile (90/180/420 rather than
5/15/30), `log-level=DEBUG` because a first run is watched, and
`extraction-step` by `templateRef` so the tuning and the 40-odd env entries
stay in one definition. `scripts/apply-manifests.sh` applies it — a template
that lives only in the repository is a worker that cannot run, and it is now the
only thing that fetches credentialed hosts.

## Why one worker

The queue rations by domain: beyond one worker per domain they wait. Seven
paywalled WSU hosts therefore support at most seven, and fewer is fine because
each holds its sessions.

More to the point, two authenticated workers on the same host mean two
concurrent sessions for one subscriber account. The WSU credentials are single
accounts and no publisher here has been asked whether it tolerates that. **This
is the one question still open**, and it is why the count is 1 rather than a
number chosen for throughput. A second worker buys wall-clock and nothing else.

## Still open

1. **Per-host login concurrency is unknown.** See above. Until it is known per
   host, one authenticated worker per dataset is the safe provisioning.
2. **Credentialed rework goes through housekeeping, which is `mixed`.**
   `news-housekeeping` runs `extract --rework` and sets no pool, so a
   credentialed link that a review decision rewound could be fetched by a
   worker that recycles every three fetches. Setting it to `anonymous` would be
   worse: the authenticated worker does not run `--rework`, so that work would
   be claimable by nobody. Today this cannot fire — all seven credentialed
   sources are `paused`, and the queue offers only `active` ones — but it is a
   hole waiting for the day one of them is left active.
3. **No schedule fires the authenticated worker**, deliberately: every
   paywalled host's first run is watched live, one publisher at a time.

## Running a paywalled host

One host at a time, watched. The queue offers whatever is `active`, so the host
under test is the only credentialed source that may be un-paused:

```sql
-- 1. confirm nothing else credentialed is active
SELECT host_norm, status FROM sources WHERE requires_login;
-- 2. un-pause exactly one
UPDATE sources SET status = 'active' WHERE host_norm = 'ptleader.com';
```

```bash
# 3. check the work is claimable, then run it watching
kubectl exec -n production deploy/work-queue -- \
  curl -s localhost:8080/stats | python -m json.tool
argo submit -n production --from workflowtemplate/authenticated-extraction \
  -p dataset=WSU-Washington-State --watch
```

```sql
-- 4. pause it again before the next host
UPDATE sources SET status = 'paused' WHERE host_norm = 'ptleader.com';
```

`ptleader.com` first: its credentials are the ones proven against a live login.
