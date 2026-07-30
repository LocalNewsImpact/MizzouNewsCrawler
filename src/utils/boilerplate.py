"""What is furniture and what is an article.

One definition, shared by everything that needs to tell reporting apart from the
scaffolding around it: the content cleaner, which removes furniture, and
telemetry, which decides whether an extraction actually captured a story.

Two ideas, in order:

1. **Vocabulary.** Some text is furniture wherever it appears. A phrase that a
   human cleaner removed from articles on many different publishers is site
   plumbing, not one newsroom's prose. That list is derived, not guessed — see
   BOILERPLATE_MARKERS.
2. **Shape.** What survives is then judged on whether it reads like writing:
   function-word density, capitalisation, and how much of the vocabulary belongs
   to websites rather than to the world.

Neither alone is enough, and the failures of each are what motivate the other —
recorded at each threshold below so the next person can retune against fresh
data rather than taste.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------

# DERIVED, NOT GUESSED. Produced by diffing 15,656 hand-cleaned articles against
# the same records as extracted (BigQuery mizzou_analytics.articles, joined on
# url), keeping only segments the cleaner removed on FOUR OR MORE distinct
# hosts. That host count is the test of whether a phrase is site furniture or
# one publisher's prose.
#
# An earlier hand-written list of plausible-sounding paywall phrases scored 2%
# recall against labelled data. These are what the corpus actually contains, and
# the counts are why they matter: "Please enable it in your browser settings"
# appeared 953 times, "Login to continue reading" 548 times across 16 hosts.
#
# Datelines ("KANSAS CITY, Mo.") and photo credits survive that diff too, but
# they are article content being MOVED to another field rather than discarded,
# so they are deliberately absent here.
#
# Phrase-level on purpose: bare words like "subscribe" appear inside real
# articles ("subscribers to the service said..."); whole prompts do not.
BOILERPLATE_MARKERS: tuple[str, ...] = (
    # paywall / registration walls
    "javascript is required for you to be able to read premium content",
    "please enable it in your browser settings",
    "login to continue reading",
    "sign up for complimentary access",
    "please log in to continue",
    "need an account?",
    "this item is available in full to subscribers",
    "non-subscribers",
    "click here to see your options for becoming a subscriber",
    "otherwise, click here to view your options for subscribing",
    "print and web subscribers",
    "subscribe now!",
    # consent / advertising furniture
    "we use cookies to help our site function properly",
    "featured local savings",
    # comment-policy block (ships as many short lines, hence the fragments)
    "please avoid obscene, vulgar, lewd",
    "racist or sexually-oriented language",
    "threats of harming another",
    "person will not be tolerated",
    "don't knowingly lie about anyone",
    "no racism, sexism or any sort of -ism",
    "that is degrading to another person",
    "use the 'report' link on",
    "each comment to let us know of abusive posts",
    "we'd love to hear eyewitness",
    "accounts, the history behind an article",
    # recirculation
    "previous post",
    "next post",
    # site navigation chrome. Mined separately from the cleaned/raw diff, which
    # could not see these: nav text survived on BOTH sides of that comparison,
    # so it never appeared as something a cleaner had removed. Found instead by
    # cross-host repetition across the stored corpus, where "skip to main
    # content" occurs on 46 distinct publishers and 985 articles — no newsroom
    # writes that. 2,879 of 94,459 stored articles (3.0%) carry one of these.
    "skip to main content",
    "toggle navigation",
    "main menu",
    "advanced search",
    "e-edition",
    "photo galleries",
)

# Words belonging to the plumbing of a website rather than to a story. Unlike
# the phrases above these are single words, so they are counted as a RATE rather
# than matched: an article may mention a subscriber once, while a registration
# form says "account", "password" and "e-mail" every other line.
UTILITY_WORDS = re.compile(
    r"\b(subscribe|subscriber|account|password|login|log in|sign up|e-?mail|"
    r"cookies|advertisement|newsletter|click here|browser)\b",
    re.IGNORECASE,
)

# Function words. Their density is what separates written English from a
# scraped control.
FUNCTION_WORDS = frozenset(
    "the a an and or but of to in on for with is are was were said he she it "
    "that this from at by as has have had not".split()
)

_SEGMENT_SPLIT = re.compile(r"[\n\r]+|(?<=[.!?])\s+")

# --------------------------------------------------------------------------
# Thresholds, with the measurements that chose them
# --------------------------------------------------------------------------

# Function-word density below which text is a list, a form or a menu.
# Measured on 1,036 labelled production extractions: median 0.137 for bodies
# flagged as boilerplate/paywall against 0.286 for the rest.
#     < 0.12 -> 38% of flagged bodies caught,  2.5% collateral
#     < 0.16 -> 64% caught,                    4.9% collateral
# The known false positive is agate — sports scores, election returns, real
# estate transfers — legitimate local copy carrying almost no function words.
MIN_PROSE_DENSITY = 0.14

# Capitalisation above which text is a run of proper nouns rather than prose.
# Density alone is fooled by the corpus's most common non-article: a country
# dropdown scraped from a registration form (5,308 chars, byte-identical across
# four hosts) scores 0.21 on density because "United States of America" is full
# of function words. Median capitalisation was 0.664 for flagged bodies against
# 0.217 for the rest — a cleaner 3x separation than density's 2x.
MAX_CAPITALIZATION = 0.60

# Utility words per 100 words, above which the text is site plumbing.
# The sharpest of the three: median 4.13 for flagged bodies against 0.00 for the
# rest — most real articles contain none of these words at all. Adding it took
# recall from 39% to 85%.
MAX_UTILITY_WORD_RATE = 3.0


# --------------------------------------------------------------------------
# Measures
# --------------------------------------------------------------------------


def segments(text: str) -> list[str]:
    """Split into lines and sentences — the unit boilerplate travels in."""
    if not text:
        return []
    return [s.strip() for s in _SEGMENT_SPLIT.split(text) if s and s.strip()]


def is_boilerplate_segment(segment: str) -> bool:
    """Whether a single line or sentence is known furniture."""
    lowered = segment.lower()
    return any(marker in lowered for marker in BOILERPLATE_MARKERS)


# A navigation menu is not one segment, it is a RUN of them. Extractors emit
# nav bars one item per line — "Home", "Categories", "Classifieds", "Columns" —
# so every item is a 1-word segment and no per-segment rule reaches it. What
# gives a menu away is the run: many consecutive short, capitalised fragments
# with no sentence punctuation between them.
#
# Calibrated against 23 hand-marked articles: at these settings the rule removes
# 32.7% of a marked article's text against 1.4% of an unmarked one — a 23:1
# ratio. Looser settings (shorter runs, longer fragments) gain little and cost
# collateral; see the sweep in the commit message.
MENU_ITEM_MAX_WORDS = 4
MENU_RUN_MIN_ITEMS = 6
# A menu label is mostly capitalised and carries almost no function words.
_MENU_MIN_CAPS = 0.6
_MENU_MAX_FUNCTION = 0.34


def _is_menu_item(segment: str) -> bool:
    """Whether a segment looks like one entry in a navigation menu."""
    words = segment.split()
    if not (1 <= len(words) <= MENU_ITEM_MAX_WORDS):
        return False
    if segment.rstrip().endswith((".", "!", "?")):
        return False  # a sentence, however short
    letters = re.findall(r"[A-Za-z][A-Za-z']*", segment)
    if not letters:
        return False
    caps = sum(1 for w in letters if w[0].isupper()) / len(letters)
    if caps < _MENU_MIN_CAPS:
        return False
    fn = sum(1 for w in letters if w.lower() in FUNCTION_WORDS) / len(letters)
    return fn <= _MENU_MAX_FUNCTION


def _drop_menu_runs(segs: list[str]) -> list[str]:
    """Drop runs of consecutive menu items from an already-split segment list.

    Deliberately requires a RUN. A single capitalised fragment is far too weak a
    signal on its own — "Mayor John Smith" would qualify — but six of them in a
    row with no sentence between is a nav bar, not writing.

    Takes and returns a LIST rather than text on purpose. Re-joining to a string
    between passes destroys the line boundaries that segmentation produced, and
    a later phrase match then applies to a segment that has swallowed the whole
    article — which deleted entire stories before a test caught it.
    """
    flags = [_is_menu_item(s) for s in segs]
    kept: list[str] = []
    i = 0
    while i < len(segs):
        if flags[i]:
            j = i
            while j < len(segs) and flags[j]:
                j += 1
            if j - i < MENU_RUN_MIN_ITEMS:
                kept.extend(segs[i:j])  # too short to be a menu; keep it
            i = j
        else:
            kept.append(segs[i])
            i += 1
    return kept


def strip_menu_runs(body: str) -> str:
    """Text-in, text-out wrapper over _drop_menu_runs, for callers and tests."""
    if not body:
        return ""
    return " ".join(_drop_menu_runs(segments(body))).strip()


def strip_boilerplate(body: str) -> str:
    """Remove the segments of a body that are walls or furniture.

    Segment-level rather than whole-body, so a single "subscribe today" line at
    the foot of a real story removes that line and keeps the story. A whole-body
    keyword test cannot do this — it would discard the article too.
    """
    if not body:
        return ""
    # Both passes share ONE segment list. Menus go first — they are structural
    # and would otherwise survive, because each item is a one-word segment that
    # no phrase or shape test reaches alone — but the list is never re-joined
    # between passes, or the phrase pass would match against a segment that had
    # swallowed the article.
    segs = _drop_menu_runs(segments(body))
    kept = [s for s in segs if not is_boilerplate_segment(s)]
    return " ".join(kept).strip()


def prose_density(text: str) -> float:
    """Share of words that are function words — how much this reads as writing."""
    words = re.findall(r"[a-zA-Z']+", text.lower())
    if not words:
        return 0.0
    return sum(1 for w in words if w in FUNCTION_WORDS) / len(words)


def capitalization_ratio(text: str) -> float:
    """Share of words beginning with a capital.

    Reporting is mostly lowercase; a scraped list of proper nouns — countries,
    place names, section menus — is mostly not.
    """
    words = re.findall(r"[A-Za-z][A-Za-z']*", text)
    if not words:
        return 0.0
    return sum(1 for w in words if w[0].isupper()) / len(words)


def utility_word_rate(text: str) -> float:
    """Website-plumbing words per 100 words.

    Shape misses text that reads like writing but is about the site rather than
    the world — registration prompts, newsletter pitches, cookie notices.
    """
    words = re.findall(r"[a-zA-Z']+", text)
    if not words:
        return 0.0
    return 100 * len(UTILITY_WORDS.findall(text)) / len(words)


def looks_like_article(body: str | None) -> bool:
    """Whether a body is a story rather than a wall, a form or a menu.

    Content-first: a paywall prompt fails however many characters it runs to,
    because what is measured is the writing that survives the strip, not the
    byte count of whatever the page returned.

    There is deliberately no word-count floor. One was measured and was actively
    harmful: a >=60-word floor caught 2% of flagged bodies while failing 13.7%
    of good ones, because local news genuinely runs short.
    """
    if not body or not body.strip():
        return False
    stripped = strip_boilerplate(body)
    if prose_density(stripped) < MIN_PROSE_DENSITY:
        return False  # a list or a menu, not writing
    if capitalization_ratio(stripped) > MAX_CAPITALIZATION:
        return False  # a run of proper nouns: a dropdown, a section index
    return utility_word_rate(stripped) <= MAX_UTILITY_WORD_RATE


def looks_like_furniture(text: str) -> bool:
    """Whether a candidate block is furniture — the inverse question.

    Used by the content cleaner to decide whether a block it is considering for
    removal really is scaffolding. Deliberately NOT `not looks_like_article(...)`:
    that would call anything short furniture, and a two-sentence paragraph in the
    middle of a story is not. This asks for positive evidence of scaffolding.

    Thin wrapper over classify_furniture() since 2026-07-28. Callers that need to
    know WHICH kind fired -- and in particular whether it is recoverable -- should
    use that directly; this bool is kept for the call sites that only ever asked
    "is this scaffolding".
    """
    return classify_furniture(text) is not None


# Paywall/registration prompts specifically, as opposed to the consent banners
# and comment-policy blocks that BOILERPLATE_MARKERS also covers. Same
# derivation discipline: phrase-level, because bare words like "subscribe"
# occur inside real reporting ("subscribers to the service said...") while
# whole prompts do not.
#
# Split out from BOILERPLATE_MARKERS because the two answer different
# questions. That list asks "should this segment be stripped?"; this one asks
# "is the page a wall instead of a story?" -- which decides whether a browser
# would help (it would not; the wall is served to browsers too) and whether the
# record should be filed as paywalled rather than retried.
# Moved here verbatim from content_cleaner_balanced.py so the cleaner and the
# capture gate read ONE list instead of drifting apart. The cleaner strips
# these; note it deliberately includes newsletter asks ("subscribe to our
# newsletter"), which are furniture but NOT walls -- a newsletter prompt sits
# beside a readable story.
SUBSCRIPTION_MARKERS: tuple[str, ...] = (
    "subscribe to our newsletter",
    "sign up for updates",
    "get daily updates",
    "subscribe now",
    "join our mailing list",
    "email updates",
    "available in full to subscribers",
    "this item is available in full to subscribers",
    "to continue reading please log in or subscribe",
    "to continue reading please login or subscribe",
    "please log in to continue reading",
    "please login to continue reading",
    "need an account print subscribers",
)

# The wall-specific subset, plus prompts observed in production that the
# stripping list does not carry (greenfieldvedette.com serves "This content is
# for subscribers only"). Newsletter asks are excluded on purpose: they are
# furniture on a readable page, not a wall in place of one.
PAYWALL_MARKERS: tuple[str, ...] = tuple(
    dict.fromkeys(
        (
            "available in full to subscribers",
            "this item is available in full to subscribers",
            "to continue reading please log in or subscribe",
            "to continue reading please login or subscribe",
            "please log in to continue reading",
            "please login to continue reading",
            "need an account print subscribers",
            # observed in production, absent from the stripping list
            "this content is for subscribers only",
            "login to continue reading",
            "please log in to continue",
            "sign up for complimentary access",
            "click here to see your options for becoming a subscriber",
            "otherwise, click here to view your options for subscribing",
            "click here to start your free trial",
            "subscribe to continue reading",
            "to continue reading, please subscribe",
            "start your free trial",
            "for subscribers only",
        )
    )
)


def looks_like_paywall(text: str | None) -> str | None:
    """The paywall prompt a body contains, or None.

    Returns the matched phrase rather than a bool so callers can record WHICH
    prompt fired -- the same reasoning as capture-quality telemetry: a verdict
    you cannot audit is a verdict you cannot tune.

    Matches on the raw body, NOT the stripped one: strip_boilerplate removes
    these very phrases, so checking after the strip would find nothing.

    Thin wrapper over classify_furniture() since 2026-07-28 -- see the section
    below for why paywalls stopped being their own detector. The literal list
    is still consulted first, so the evidence returned for a wall this project
    already had a phrase for is that exact phrase.
    """
    found = classify_furniture(text)
    if found is not None and found.kind == PAYWALL:
        return found.evidence
    return None


# --------------------------------------------------------------------------
# One detector, and what KIND of furniture it found
# --------------------------------------------------------------------------
#
# Paywall prompts, cookie modals, nav bars and comment policies all answer ONE
# question: is this block scaffolding rather than reporting? They were three
# separate mechanisms in three files -- looks_like_furniture() here (shape),
# looks_like_paywall() here (literal PAYWALL_MARKERS), and an inline
# _cmp_dump_markers list in crawler/__init__.py (literal, five vendor strings).
# The comment above PAYWALL_MARKERS already conceded the point: these are
# paywall prompts "as opposed to the consent banners ... that BOILERPLATE_MARKERS
# also covers" -- same category, three implementations.
#
# That split is exactly how kq2.com slipped through. Its Cloudflare cookie table
# is not WPConsent or OneTrust, so none of the five strings matched, and 11 of 17
# articles in one 4-hour window were stored with 27,372 chars of cookie
# disclosure as the article body -- all of them already CIN-labelled, sitting in
# the corpus. Adding kq2's phrase fixes kq2 and misses the next vendor; the
# header of this module already records that a hand-written list of plausible
# paywall phrases scored 2% recall.
#
# What actually differs between these is DOWNSTREAM, not detection. It is a
# label on the finding, not a reason for a separate code path:
#
#   PAYWALL   content exists but is withheld -- retryable with credentials
#   CONSENT   cookie/GDPR modal: pure noise, nothing to recover
#   PROMO     newsletter ask: furniture beside a readable story
#   POLICY    comment rules, also noise
#   NAV       menus, e-edition links, section indexes
#   UNKNOWN   shape says scaffolding, vocabulary cannot say which kind
#
# Only PAYWALL is recoverable, and that is the one bit callers need in order to
# choose a status: paywall vs not_article.
PAYWALL = "paywall"
CONSENT = "consent"
PROMO = "promotion"
POLICY = "comment_policy"
NAV = "navigation"
#: Matched one of BOILERPLATE_MARKERS -- the list DERIVED by diffing 15,656
#: hand-cleaned articles and keeping only segments a human cleaner removed on
#: four or more distinct hosts. That provenance is why this is its own kind and
#: not UNKNOWN: it is VOCABULARY evidence (precise, local, human-validated),
#: not a shape estimate, so a segment carrying one may be removed. Before this
#: existed such matches fell through to UNKNOWN, which is deliberately
#: NOT segment-removable, so the best-evidenced list in the module could not
#: actually remove anything -- the TownNews "Javascript is required ... premium
#: content" notice survived excision on real joplinglobe.com articles even
#: though its exact sentence is the FIRST entry in BOILERPLATE_MARKERS.
BOILERPLATE = "boilerplate"
UNKNOWN = "furniture"

#: Kinds that mean "the page has a story we did not get", as opposed to "this
#: block is noise". Only these justify a retry with credentials.
RECOVERABLE_KINDS: frozenset[str] = frozenset({PAYWALL})

#: Kinds a SEGMENT may be deleted for. Everything except UNKNOWN, and the
#: exclusion is the important part.
#:
#: UNKNOWN is the shape verdict -- prose density, capitalisation, utility-word
#: rate -- and those thresholds were measured on whole bodies (medians over
#: 1,036 labelled extractions). A single sentence has far too little text to
#: estimate a rate from, so applying them per-segment deletes real writing:
#: "Voters who want to continue receiving mail ballots must sign up again this
#: year" scores 7.1 utility words per 100 and is a news sentence.
#:
#: So the two layers keep different jobs, which is also why this is not just a
#: tuning constant: VOCABULARY and CONCEPTS are local and precise, and may
#: remove a segment; SHAPE is statistical and only ever judges a whole body
#: (via looks_like_furniture at the capture gate). Menus are the exception that
#: proves it -- they are structural, so _drop_menu_runs handles them by RUN
#: rather than by per-segment shape.
_SEGMENT_REMOVABLE: frozenset[str] = frozenset(
    {PAYWALL, CONSENT, PROMO, POLICY, NAV, BOILERPLATE}
)


class Furniture(NamedTuple):
    """A furniture finding: what kind, and the evidence that decided it.

    Evidence is carried for the same reason looks_like_paywall() returned a
    phrase instead of a bool -- a verdict you cannot audit is a verdict you
    cannot tune.
    """

    kind: str
    evidence: str

    @property
    def recoverable(self) -> bool:
        return self.kind in RECOVERABLE_KINDS


# Concept matching, not phrase matching.
#
# The user's framing, 2026-07-28: this heuristic is a core function of the app
# and "exact matching like this does not scale". Every vendor words its banner
# differently, so a list of whole prompts needs a new entry per CMS forever.
# What does NOT vary is the SHAPE of the demand: a wall names something you
# cannot do (read on) and something you must do first (subscribe, log in). Match
# those two ideas near each other and the wording stops mattering.
#
# This is the practical meaning of "semantic" without putting a model in the
# extraction hot path: concepts composed of alternatives, required to co-occur.
# Every alternative is anchored to READING or to a CONTENT NOUN. An earlier
# draft allowed bare "to continue" and bare "access", which turns local news
# into paywalls wholesale: "To continue the program, residents must register by
# Friday" carries an access word and a gate word within a sentence and is a
# story about a parks department. The anchor is what makes the concept a wall
# rather than a coincidence.
_CONTENT_NOUN = r"(?:article|story|content|piece|report|post)"
_ACCESS_INTENT = re.compile(
    r"(?:continue|keep|finish|start)\s+reading"
    r"|continue\s+to\s+read"
    r"|read(?:ing)?\s+(?:the\s+)?(?:full|rest|remainder|entire)\b"
    rf"|read\s+(?:this|the)\s+{_CONTENT_NOUN}"
    rf"|view\s+(?:this|the)\s+(?:full\s+)?{_CONTENT_NOUN}"
    rf"|see\s+the\s+(?:full|rest|entire)\s+{_CONTENT_NOUN}"
    rf"|access\s+(?:to\s+)?(?:this|the)\s+(?:full\s+)?{_CONTENT_NOUN}"
    rf"|unlock\s+(?:this|the|full)\s*{_CONTENT_NOUN}?",
    re.IGNORECASE,
)
_GATE_ACTION = re.compile(
    r"subscri(?:be|ption|ber)|log\s?in|sign\s?in|sign\s?up|register"
    r"|create\s+an?\s+account|free\s+trial|purchase|paid\s+plan|become\s+a\s+member",
    re.IGNORECASE,
)
# Entitlement language is a wall on its own -- it states the restriction without
# needing to name an action ("for subscribers only").
_ENTITLEMENT = re.compile(
    r"(?:subscribers?|members?|premium)[- ]only"
    r"|only\s+(?:available\s+)?(?:to|for)\s+subscribers"
    r"|available\s+in\s+full\s+to\s+subscribers"
    r"|subscriber\s+account"
    # Stands alone rather than needing a gate action beside it. "Unlimited
    # access" is subscription marketing and essentially never news prose --
    # 0 hits across 180 real stories in the 2026-07-28 export. It was an
    # access-intent at first, which failed to fire on "Members get unlimited
    # access for less than a dollar a week": the sentence names no action
    # because the entitlement IS the pitch.
    r"|unlimited\s+(?:digital\s+)?access",
    re.IGNORECASE,
)

# Bare "premium content" is NOT an entitlement on its own. Removed from
# _ENTITLEMENT on 2026-07-30 after it condemned four legitimate joplinglobe.com
# articles: TownNews injects "Javascript is required for you to be able to read
# premium content. Please enable it in your browser settings." INLINE, mid-body,
# with the story continuing around it --
#
#     "...deft hands at displaying unique things in creative ways. x Javascript
#      is required for you to be able to read premium content. Please enable it
#      in your browser settings. So did I see something I would buy? Yep, but I
#      resisted temptation."
#
# so classify_furniture() returned PAYWALL for the whole article. That is the
# all-or-nothing failure this module exists to avoid: the notice is one
# sentence of furniture inside real reporting, and the correct response is to
# excise that sentence, not condemn the body.
#
# The phrase still earns a PAYWALL verdict when it appears in an actual
# entitlement claim ("this is premium content for subscribers"), which the
# access-intent/gate-action pairing in _gated() already catches, and the full
# JS-notice sentence is ALREADY the first entry in BOILERPLATE_MARKERS, so
# segment-level removal is unaffected. What changed is only that the bare
# phrase can no longer, by itself, condemn a whole body.
_PREMIUM_CONTENT_PHRASE = re.compile(r"premium\s+content", re.IGNORECASE)
# How close the two halves must sit. A story that mentions reading in one
# paragraph and a subscription in another is not a wall; a prompt puts them in
# the same breath.
_GATE_WINDOW = 120

_CONSENT_VOCAB = re.compile(
    r"\bcookies?\b|\bconsent\b|\bgdpr\b|\bccpa\b|\btrackers?\b"
    r"|\bthird[- ]party\b|\bopt[- ]out\b|\bprivacy\s+preferences?\b",
    re.IGNORECASE,
)
# Cookie tables list a lifetime for every row. Vendor-independent: the unit is
# the give-away, not the wording around it.
_DURATION_TOKEN = re.compile(
    r"\b\d+\s*(?:second|minute|hour|day|week|month|year)s?\b"
    r"|\bsession\b|\bpersistent\b|\bexpir(?:es|ation|y)\b",
    re.IGNORECASE,
)
# Vendor tokens still earn their place as a fast, unambiguous path -- they just
# are no longer the ONLY path. kq2's Cloudflare names are here now, but the
# density rule below is what catches the vendor nobody has seen yet.
_CONSENT_VENDOR = re.compile(
    r"wpconsent|onetrust|cookieconsent|cookiebot|trustarc|quantcast"
    r"|__cf_bm|cf_ob_info|_ga\b|_gid\b|\bcookie[-_]?(?:policy|notice|banner)\b",
    re.IGNORECASE,
)
# Consent vocabulary per 100 words. A story ABOUT privacy law mentions cookies a
# handful of times in 800 words (~0.5); a disclosure table repeats the word on
# every row. Set well above prose and well below a table.
_CONSENT_RATE = 2.0
_CONSENT_MIN_DURATIONS = 3

# The consent NOTICE, as opposed to the cookie table. One or two sentences, so
# the density rule cannot see it -- there is not enough text to measure a rate
# from -- and the shape rules can only ever return UNKNOWN, which is not
# removable by design. Without a CONSENT verdict it survived into the body:
# four stltoday.com rows in the 2026-07-28 export are this notice plus dialog
# chrome plus a photo caption, with no article at all, and they were labelled
# Political life and Civic information.
_CONSENT_NOTICE = re.compile(
    r"(?:this\s+(?:website|site)\s+(?:uses|utilizes)|we\s+use)[^.]{0,80}cookies"
    r"|cookies?\s+to\s+(?:enable|improve|analyse|analyze|personalise|personalize)"
    r"|accept\s+all\s+cookies|manage\s+(?:your\s+)?(?:cookie\s+)?preferences"
    r"|cookie\s+policy|privacy\s+policy",
    re.IGNORECASE,
)
_PROMO = re.compile(
    r"subscribe\s+to\s+our\s+newsletter|sign\s+up\s+for\s+(?:updates|our|the)"
    r"|join\s+our\s+mailing\s+list|get\s+(?:daily|breaking|weekly)\s+updates"
    r"|email\s+updates|delivered\s+to\s+your\s+inbox",
    re.IGNORECASE,
)
_POLICY = re.compile(
    r"obscene,\s*vulgar|racist\s+or\s+sexually|threats\s+of\s+harming"
    r"|knowingly\s+lie\s+about|sort\s+of\s+-ism|report'?\s+link"
    r"|abusive\s+posts|degrading\s+to\s+another",
    re.IGNORECASE,
)
_NAV = re.compile(
    r"skip\s+to\s+main\s+content|toggle\s+navigation|main\s+menu"
    r"|advanced\s+search|e-edition|photo\s+galleries|previous\s+post|next\s+post"
    # Modal and clipboard chrome that ships with the consent notice above.
    r"|(?:beginning|end)\s+of\s+dialog\s+window|escape\s+will\s+cancel"
    r"|opens?\s+(?:in\s+a\s+new|an\s+external)\s+(?:window|website)"
    r"|copied\s+to\s+clipboard",
    re.IGNORECASE,
)

# Which literal list maps to which kind, so a phrase this project already
# derived from real data keeps naming itself as the evidence rather than being
# replaced by a generic concept name.
_MARKER_KINDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (PAYWALL_MARKERS, PAYWALL),
    (SUBSCRIPTION_MARKERS, PROMO),
)


# Share of the text a SINGLE token may occupy before the block is filler.
#
# Found by challenging the control set rather than by design: four stltoday.com
# rows in the 2026-07-28 export are site chrome plus literal "word word word
# word ..." placeholder text, and one is CIN-labelled Economic Development at
# 0.41 confidence. Their most common token is 71% of the body. Across the 176
# genuine stories in the same export the worst case is 12.6% -- a 5.6x gap, the
# widest separation of any signal measured here.
#
# Vendor-independent and language-independent, which is the point: it describes
# degenerate text rather than anyone's markup.
MAX_TOKEN_REPETITION = 0.25

# Below this many words, rates and densities are noise rather than measurement.
# Matches the floor _consent_dump already uses.
_MIN_MEASURABLE_WORDS = 40


def _max_token_share(text: str) -> float:
    """Share of the text taken by its single most common word."""
    words = re.findall(r"[a-z']+", text.lower())
    if len(words) < _MIN_MEASURABLE_WORDS:
        return 0.0
    counts: dict[str, int] = {}
    for w in words:
        counts[w] = counts.get(w, 0) + 1
    return max(counts.values()) / len(words)


def _long_enough_to_measure(text: str) -> bool:
    return len(re.findall(r"[a-zA-Z']+", text)) >= _MIN_MEASURABLE_WORDS


def _consent_dump(text: str, lowered: str) -> str | None:
    """Whether a block is a cookie-disclosure table, by shape not by vendor.

    The kq2 case: a 27,372-char Cloudflare table with no phrase any list held.
    Two independent signals have to agree -- saturation of consent vocabulary
    AND repeated lifetime values -- because either alone has an obvious false
    positive (an article about GDPR; a transit timetable).
    """
    words = re.findall(r"[a-zA-Z']+", lowered)
    if len(words) < 40:
        return None
    hits = len(_CONSENT_VOCAB.findall(lowered))
    if hits == 0:
        return None
    rate = hits * 100.0 / len(words)
    durations = len(_DURATION_TOKEN.findall(lowered))
    if rate >= _CONSENT_RATE and durations >= _CONSENT_MIN_DURATIONS:
        return f"consent vocabulary {rate:.1f}/100w with {durations} lifetimes"
    return None


def _gated(lowered: str) -> str | None:
    """A wall: something withheld, and the thing you must do to get it.

    Searches BOTH directions around the access-intent match. Found 2026-07-29
    on a real maryvilleforum.com wall this missed entirely:

        "Your current subscription does not provide access to this content."

    The gate action ("subscription") sits BEFORE the access-intent phrase
    ("access to this content") in that sentence -- a forward-only window never
    sees it. Real walls order these both ways ("please log in to access this
    article" vs "your subscription does not provide access to this content"),
    so the search has to be symmetric, not just extended.
    """
    entitle = _ENTITLEMENT.search(lowered)
    if entitle:
        return entitle.group(0).strip()
    for m in _ACCESS_INTENT.finditer(lowered):
        forward = lowered[m.start() : m.end() + _GATE_WINDOW]
        backward = lowered[max(0, m.start() - _GATE_WINDOW) : m.end()]
        action = _GATE_ACTION.search(forward) or _GATE_ACTION.search(backward)
        if action:
            return f"{m.group(0).strip()} ... {action.group(0).strip()}"
    return None


def classify_furniture(text: str | None) -> Furniture | None:
    """What kind of furniture this block is, or None if it reads as reporting.

    THE one detector. Order matters and encodes precedence rather than taste:

    1. Literal markers first, so a wall this project already derived a phrase
       for reports that phrase as its evidence (auditable, and it keeps the
       marker lists doing real work rather than rotting).
    2. Concepts next -- these generalise to vendors nobody has seen.
    3. Shape last, which can say "scaffolding" but not which kind.

    PAYWALL outranks the noise kinds throughout: a wall wrapped in a nav menu is
    still a wall, and calling it navigation would throw away the one finding
    that says a story exists behind it.
    """
    if not text or not text.strip():
        return None
    lowered = text.lower()

    for markers, kind in _MARKER_KINDS:
        for marker in markers:
            if marker in lowered:
                return Furniture(kind, marker)

    gate = _gated(lowered)
    if gate:
        return Furniture(PAYWALL, gate)

    dump = _consent_dump(text, lowered)
    if dump:
        return Furniture(CONSENT, dump)
    vendor = _CONSENT_VENDOR.search(text)
    if vendor:
        return Furniture(CONSENT, vendor.group(0).strip())
    notice = _CONSENT_NOTICE.search(lowered)
    if notice:
        return Furniture(CONSENT, notice.group(0).strip())

    for pattern, kind in ((_POLICY, POLICY), (_PROMO, PROMO), (_NAV, NAV)):
        m = pattern.search(lowered)
        if m:
            return Furniture(kind, m.group(0).strip())

    if is_boilerplate_segment(text):
        return Furniture(BOILERPLATE, "boilerplate marker")
    if utility_word_rate(text) > MAX_UTILITY_WORD_RATE:
        return Furniture(UNKNOWN, f"utility words {utility_word_rate(text):.1f}/100w")
    repetition = _max_token_share(text)
    if repetition > MAX_TOKEN_REPETITION:
        return Furniture(UNKNOWN, f"one token is {repetition:.0%} of the text")
    if _long_enough_to_measure(text) and prose_density(text) < MIN_PROSE_DENSITY:
        return Furniture(UNKNOWN, f"prose density {prose_density(text):.2f}")
    if capitalization_ratio(text) > MAX_CAPITALIZATION:
        return Furniture(UNKNOWN, f"capitalisation {capitalization_ratio(text):.2f}")
    return None


# A furniture line longer than this is edited sentence-by-sentence rather than
# dropped whole, because at that length it is likely to be an extractor's
# unbroken run of banner-plus-story rather than a banner alone. Set from the
# stltoday captures, whose consent notices run ~300 chars while the mixed
# banner-and-story lines run 1,500-2,200.
MAX_WHOLE_LINE_DROP = 400


def excise_furniture_lines(body: str | None) -> tuple[str, frozenset[str]]:
    """Drop whole LINES that are furniture, leaving everything else byte-exact.

    The write-path variant, and deliberately much more conservative than
    strip_furniture(). It differs in exactly two ways, both of which were
    forced by measuring strip_furniture against 161 real stored bodies:

    1. **Layout is preserved.** strip_furniture rejoins with " ", which
       collapses every newline in the body. On those 161 bodies that alone
       rewrote 149 of them -- 90% -- for no editorial gain. Storing a
       reformatted body is a destructive edit even when no words are lost.

    2. **No menu-run removal.** _drop_menu_runs is a RUN heuristic tuned for
       nav bars, and on stored bodies it eats agate: it removed a
       maconhomepress.com honor roll ("Class 1 Macey Harrington Team GPA: 3.55
       Jordan Harrington Jessalyn Parks ...") as though it were a menu. This
       module's own thresholds already name that risk -- "the known false
       positive is agate: sports scores, election returns, real estate
       transfers, legitimate local copy carrying almost no function words".
       Detecting furniture can afford that; editing a stored article cannot.

    So this removes only what VOCABULARY and CONCEPTS positively identify --
    consent notices, walls, comment policies, nav chrome -- and never anything
    judged on shape alone. Returns the kept text and the kinds removed, so the
    caller can let the kind pick the status.
    """
    if not body or not body.strip():
        return "", frozenset()
    kept_lines: list[str] = []
    kinds: set[str] = set()
    for line in body.splitlines():
        if not line.strip():
            kept_lines.append(line)
            continue
        found = classify_furniture(line)
        if found is None or found.kind not in _SEGMENT_REMOVABLE:
            kept_lines.append(line)
            continue
        if len(line) <= MAX_WHOLE_LINE_DROP:
            kinds.add(found.kind)
            continue
        # A LONG line judged furniture is not necessarily furniture all the way
        # through -- extractors that emit no paragraph breaks put the banner and
        # the story on one line. Dropping it whole is the all-or-nothing bug in
        # miniature: one stltoday.com capture carries its consent notice and
        # "ST. LOUIS COUNTY -- A worker hired to paint the KSDK television
        # transmission tower helped save a man who climbed it" in a single
        # 2,177-char line, and dropping the line lost the story.
        #
        # So go a level finer INSIDE the line and keep what survives. The line
        # boundary itself is preserved either way, so layout never changes.
        inner = [s for s in segments(line) if _keeps(s, kinds)]
        if inner:
            kept_lines.append(" ".join(inner))
        else:
            kinds.add(found.kind)
    return "\n".join(kept_lines).strip(), frozenset(kinds)


def _keeps(segment: str, kinds: set[str]) -> bool:
    """Whether a sentence survives, recording the kind when it does not."""
    found = classify_furniture(segment)
    if found is not None and found.kind in _SEGMENT_REMOVABLE:
        kinds.add(found.kind)
        return False
    return True


# Minimum characters of unbroken clean text to be believed as body copy inside a
# block already condemned as a disclosure table.
#
# MEASURED, on the real 27,372-char kq2 capture. Its table breaks into 39 runs
# of segments carrying no cookie word, no lifetime and no vendor token -- the
# prose in the vendors' own descriptions -- and the LARGEST is 387 chars. A real
# 1,476-char story appended to that same table forms one unbroken 1,463-char
# run. So the story is ~4x the biggest thing the table can produce.
#
# Prose density was tried first and does not separate these at all: the table's
# clean runs score 0.211-0.357 and real stories 0.221-0.367, because Cloudflare
# and Google write their cookie descriptions in ordinary English. Length is what
# actually distinguishes them.
#
# The known cost: a genuinely SHORT story glued to a full cookie table is lost
# and the row is filed not_article. That is the safer of the two failures and
# the honest one -- the alternative, which is what production did, was to store
# the cookie table AS the story and let it be CIN-labelled. A visible
# not_article can be re-filed; a plausible-looking mislabel cannot be found.
MIN_EMBEDDED_PROSE_RUN = 500


def _longest_prose_runs(segs: list[str]) -> str:
    """Keep only substantial unbroken runs of table-signal-free segments.

    Runs, not individual segments, because a banner and a story are contiguous
    REGIONS of a page rather than interleaved sentences. Judging segment by
    segment kept 3,648 chars of scattered vendor prose ("The Ray ID of the
    original failed request.") that no per-sentence rule can tell from writing.
    """
    runs: list[list[str]] = []
    current: list[str] = []
    for seg in segs:
        if (
            _CONSENT_VOCAB.search(seg)
            or _DURATION_TOKEN.search(seg)
            or _CONSENT_VENDOR.search(seg)
        ):
            if current:
                runs.append(current)
                current = []
        else:
            current.append(seg)
    if current:
        runs.append(current)
    kept = [" ".join(r) for r in runs if len(" ".join(r)) >= MIN_EMBEDDED_PROSE_RUN]
    return " ".join(kept).strip()


class Stripped(NamedTuple):
    """What surgical removal left, and what it took."""

    text: str
    removed: tuple[Furniture, ...]

    @property
    def kinds(self) -> frozenset[str]:
        return frozenset(f.kind for f in self.removed)

    @property
    def recoverable(self) -> bool:
        """Whether anything removed means a story is being withheld."""
        return any(f.recoverable for f in self.removed)


def strip_furniture(body: str | None) -> Stripped:
    """Remove the furniture segments and keep everything else.

    SURGICAL, and that is the whole point. The consent guard this replaces did
    ``text_content = None`` -- one marker anywhere discarded the entire capture,
    so a page carrying a banner AND a story lost the story too. Removal is
    per-segment, so a cookie table above the article takes the table only.

    The caller decides status from what is LEFT plus ``.kinds``: prose survived
    means store it, nothing survived plus a recoverable kind means paywall,
    nothing survived otherwise means not_article. That decision does not belong
    here -- this function reports, it does not adjudicate.
    """
    if not body or not body.strip():
        return Stripped("", ())
    segs = _drop_menu_runs(segments(body))
    kept: list[str] = []
    removed: list[Furniture] = []
    for seg in segs:
        found = classify_furniture(seg)
        if found is None or found.kind not in _SEGMENT_REMOVABLE:
            kept.append(seg)
        else:
            removed.append(found)
    text = " ".join(kept).strip()
    # Then ask the same question of what SURVIVED, because a disclosure table is
    # a property of the whole block and not of any one sentence in it. The real
    # kq2 capture is 27,372 chars with no line breaks at all, so it segments
    # into ordinary-looking sentences -- "This cookie is used to store the
    # user's cookie consent preferences. 30 days" -- and not one of them carries
    # enough lifetimes on its own to be condemned. Only the 4,319-word whole
    # does: 189 lifetimes at 3.3 consent words per 100.
    #
    # This deliberately runs even when segments were already removed. Gating it
    # on `not removed` meant a page whose vendor strings matched a few segments
    # had its whole-body check skipped, and 24,819 of those 27,372 chars were
    # kept as the article body -- the exact bug, surviving the fix meant to
    # remove it.
    if text:
        whole = _consent_dump(text, text.lower())
        if whole:
            # EXCISE the table, do not condemn the page. Returning "" here was
            # the naive version and it reintroduced the original sin from the
            # other direction: a capture holding the banner AND a story lost the
            # story, which is the whole failure this rewrite exists to end.
            #
            # Inside a block already established as a disclosure dump, any one
            # of the three table signals is enough to drop a sentence -- a much
            # lower bar than the whole-body rate, and safe precisely because it
            # is scoped to a block that has already been condemned.
            #
            # The lifetime token has to be in here. Consent vocabulary alone
            # left 11,984 chars of this very table standing, because rows like
            # "session __cfruid Used by the content network, Cloudflare, to
            # identify trusted web traffic" never say "cookie" -- the column
            # heading did, once, 4,000 words earlier. Every row carries a
            # lifetime, which is what makes it a row.
            #
            # "30 days" can of course appear in real writing. That is an
            # acceptable trade HERE and only here: this predicate never runs on
            # a block that was not already condemned as a disclosure table.
            return Stripped(
                _longest_prose_runs(kept),
                (*removed, Furniture(CONSENT, whole)),
            )
    return Stripped(text, tuple(removed))
