# A login is witnessed at entry

How the crawler will know it is logged in to a publisher, and why the answer is
not a runtime check.

## What was learned on 2026-09-20

The first authenticated WSU extraction run exposed four things at once.

**There is no site-independent way to confirm a login.** Every candidate was
tested and each failed for a measured reason:

| candidate | why it fails |
| --- | --- |
| HTTP status on the article | `200` for the wall and `200` for the story; `401`/`WWW-Authenticate` is Basic and Bearer, not a cookie session |
| the article's content | a metered paywall gives an anonymous visitor two to four full articles — Yakima's own pattern that day was three stories, then a wall |
| a new cookie | Connext **updates** `nxt_YHR_YHRCONFIG_PROD` in place; the four cookies that appeared were analytics and PerimeterX |
| a per-host cookie shape | hundreds of hosts, dozens of vendors — nothing to learn once |
| text in the page source | `log out`, `logout` and `my account` are present logged **out** — the site ships both states and toggles visibility |
| the account page | `403`, with an Incapsula WAF in the path, so the status is not attributable to authentication |

**The confirmation used today is three guesses OR'd together** — did the URL
change, does `success_text` appear in the source, did the login trigger vanish.
On a homepage modal none holds. `www.yakimaherald.com` reported the identical
"did not confirm" at 16:43 on a session that was working and at 16:45 on one
that was not.

**The failure that mattered was upstream of confirmation.** The login never
ran. The trigger was looked up once, immediately after `driver.get()`, and
Connext renders it with JavaScript:

    16:43:01  form login: login trigger selector 'a[data-mg2-action='login']' not found
    16:43:41  Authenticated login: username/email field not found
    16:43:41  Login to yakimaherald.com did not confirm; continuing unauthenticated
    16:45:16  Article body is furniture, not prose - marking as not_article (7458 chars)

A school-board election story, fetched anonymously, captured as navigation
furniture, and filed `not_article` by gates that were working correctly.

**And the login works.** Driven in Playwright with the trigger polled for and
the click dispatched directly, the same selectors and credentials produced
`POST prod-amg-proxy-connext.azurewebsites.net/api/user → 200`, `Log In`
hidden, `My Account` visible. It was verified in July; the markup changed;
nothing said so for two months.

## The shape

Three moments, each with a different job.

### Entry: a person declares the login and watches it succeed

The person adding a credentialed source has the site open and knows what kind
of login it is. They declare:

| field | values |
| --- | --- |
| vendor (`auth_type`) | `form`, `auth0`, `newzware`, `etype`, `simplecirc`, … |
| login URL | where the form is, or the page whose modal opens it |
| path | `page` — the form is on the URL · `modal` — a control must be clicked first · `sso` — the URL redirects to the vendor |
| credentials | to Secret Manager, as now |

**Saving runs the login.** The same loop the crawler uses, with recording on,
executes right then and shows the result before the source is enabled:

    Logged in ✔   Connext /api/user → 200 · "Log In" hidden · "My Account" visible
                  selectors recorded · session cookie: nxt_YHR_YHRCONFIG_PROD

    Not logged in ✘   trigger found · modal opened · submit answered 401

That witnessed success **is** the affirmative signal. It is not inferred at
runtime from anything; a person saw the vendor accept the credentials, once, and
the recording of that — which network call answered, which controls flipped,
which selectors resolved — is stored as the host's recipe.

### Runtime: reproduce, retry once, refuse

The crawler's job is to reproduce a known-good login, not to discover one.

- poll for every element the recipe names — the trigger as well as the fields
  (the asymmetry that broke Yakima: 20 seconds for the field inside the modal,
  none for the control that opens it)
- click with a JavaScript fallback: the control can be visible, enabled and
  stable and still sit outside the viewport
- confirm against the recipe's recorded signals, all of which must hold
- on failure, log in again once on a fresh driver; then **refuse the host** —
  a link left owing a fetch is honest, a stored wall is not
- **never infer success from content.** Metered sites give free reads.

The refusal and the bounded retry are built (#635). Recording the outcome per
fetch — `authenticated_session: true|false` in `articles.metadata` — is what
lets "was this article fetched as a subscriber" be answered from data rather
than argued from body length.

### Drift: when the recipe stops resolving

A site redesigns and the stored selectors match nothing. The engine tries the
semantic ladder — `input[type=password]`, `autocomplete=username`, a control
whose text is *Log In* — and whether that succeeds or not, the source is
**flagged for re-validation**, visibly, the way `/stats` names each
credentialed host it cannot serve today. The person re-runs the entry step.
Nothing fetches walls quietly in the meantime.

## Why this scales where authoring does not

Vendors are dozens; sites are hundreds; and within one vendor the selectors
still differ per theme — Yakima and tdn are both BLOX and share nothing. So
nobody writes recipes. A person witnesses one login per site at entry, the
recording is the recipe, and the runtime only has to reproduce it. What varies
per site is captured by a human with the page open; what is stable per vendor
(the auth endpoint, the credential shape) is learned by the first witnessed
login on that vendor and reused.

The residual is the sites where the ladder bottoms out — CAPTCHA in the modal,
a novel SSO flow, a broken site. The design's job there is not to succeed but to
**say so by name**. A hundred sites where ninety log in and ten are listed as
needing a person is a working system. A hundred where all "succeed" and some
fetch walls is what this run had.

## What exists and what is new

| piece | state |
| --- | --- |
| `sources.auth_type`, `auth_config`, `auth_secret_name` | exist |
| refuse on unconfirmed login, retry once | #635, merged |
| poll for the trigger, wait for the modal | `fix/the-login-trigger-is-waited-for` |
| `auth_config.success_cookie`, honoured when set | #635; unset for every host |
| a `path` field; validate-on-save; the recording stored as the recipe | new — crawler half |
| the entry form and the ✔/✘ result | new — datadesk |
| `authenticated_session` written per fetch | new, small |
| a "needs re-validation" state reported by `/stats` | new, small |

The Playwright harness that found the Yakima cause is the validate-on-save step
with a person reading the output. It lives in the session scratchpad today and
belongs in `scripts/` once the entry step exists to call it.
