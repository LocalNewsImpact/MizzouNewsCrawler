# A credentialed host needs a worker of its own

The work queue hands a worker one domain and at most three articles per
request, then rotates. That is what keeps a publisher from seeing a hundred
consecutive requests, and it is correct. It also means a credentialed host is
visited in short bursts — and the Selenium driver that holds its login is
shared between every domain that worker touches.

`ContentExtractor._authenticated_domains` is cleared every time that driver is
recycled, and `SELENIUM_DRIVER_REUSE_LIMIT` defaults to 10 uses. So a worker
working through mixed domains signs in to a paywalled host roughly every third
visit. Across the 1,038 WSU links behind seven paywalled publishers that is a
great many logins, each one a login form submitted to a publisher who is
watching.

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

| worker | asks the queue for | reuse limit | why |
| --- | --- | --- | --- |
| anonymous | `requires_login=False` | 10 | rotation is the point |
| authenticated | `requires_login=True` | higher | the session identifies us anyway; recycling only costs logins |

Both still rotate *between* domains of their own kind. The cooldowns, the
per-domain caps and the failure pauses are unchanged — segregation is about
which pool a worker draws from, not about how politely it draws.

Two halves of that are implemented, and neither is switched on:

- `WorkRequest.requires_login` is the queue half. `None` mixes, which is the
  historical behaviour and what every current caller gets; `/work/request`
  accepts and forwards the flag, and `_get_available_domains` appends
  `AND s.requires_login = :requires_login` only when it is set.
- `EXTRACTION_AUTHENTICATED_WORKER` is the worker half, read once into
  `ContentExtractor._authenticated_worker`. When set, the driver takes
  `SELENIUM_DRIVER_REUSE_LIMIT_AUTHENTICATED` (default 50) instead of
  `SELENIUM_DRIVER_REUSE_LIMIT` (default 10). It is a property of the WORKER,
  not of what the driver has managed to log in to so far.

Nothing sets either yet, on purpose: wiring the pipeline to send
`requires_login=False` without an authenticated worker running is what causes
problem 2 below.

## What is NOT solved, and must be before this is switched on

**1. An anonymous worker must exclude credentialed domains explicitly.**
Adding an authenticated worker changes nothing on its own: a credentialed domain
is still offered to whichever worker asks first, so an anonymous worker picks it
up and logs in anyway. The pipeline has to set `requires_login=False` on its
ordinary workers, which means `news-pipeline-template`'s `extraction-step` needs
the flag too — not just the authenticated template.

**2. Credentialed work starves if no authenticated worker is running.**
Once anonymous workers exclude those domains, nothing else takes them. A
paywalled backlog then sits at `article` indefinitely and the run reports
success, because "no work for me" and "no work at all" look identical to a
worker. `/stats` should report credentialed work outstanding and whether any
worker has asked for it, so the gap is visible rather than inferred from a
count that never moves.

**3. How many authenticated workers.**
The queue rations by domain: beyond one worker per domain they wait. Seven
paywalled WSU hosts therefore support at most seven, and fewer is fine because
each holds its sessions. One worker is the starting point — it logs in to each
host once and rotates among them — and the reason to add a second is wall-clock,
not throughput per host.

**4. Login concurrency.**
Two authenticated workers on the same host mean two sessions for one account.
Whether a publisher tolerates that varies, and the WSU credentials are single
accounts. Until that is known per host, one authenticated worker per dataset is
the safe provisioning.

**5. Which hosts qualify is already recorded, and is not the same question as
whether we can get in.** `sources.requires_login` is the flag the queue filter
reads. `auth_secret_name` says whether credentials exist;
`chinookobserver.com` and `www.wenatcheeworld.com` have neither and are paused.
A host with `requires_login=true` and no usable credentials belongs in neither
pool, and the filter as written would hand it to the authenticated worker.

## Until then

The paywalled WSU runs are done one host at a time, with the other credentialed
sources paused, so the pool the queue can offer contains exactly one
credentialed domain and nothing anonymous. That needs no segregation: there is
nothing to mix. It is also how a first run on a paywalled host should be done
anyway — watched, one publisher at a time — so the provisioning work is not
blocking it.
