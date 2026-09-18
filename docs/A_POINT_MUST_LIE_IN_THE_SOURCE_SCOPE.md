# A point must lie in a state the source can reach

The enrichment ladder geocodes the state the model reports. Nothing compares
that state to the states the source actually covers, so a model that names the
wrong one produces a point that resolves cleanly, carries a real GEOID and a
real latitude and longitude, and is in the wrong part of the country.

## What it looks like

Two of the 171 points in the WSU Washington corpus (2026-09-17):

| point | resolved GEOID | where that is | source |
|---|---|---|---|
| Quincy | 1762367 | Quincy, Illinois | khq.com (Spokane, WA) |
| Weston | 5586025 | Weston, Wisconsin | union-bulletin.com (Walla Walla, WA) |

The `article_places` row for the first reads:

    place: "Quincy, IL"  city: "Quincy"  state: "IL"  geoid: 1762367
    evidence: "Headline: Mother thankful boy still alive after falling in
               canal in Quincy"

The headline names no state. The model supplied Illinois — the Quincy most
often written about — for a Spokane station's story about a canal, which is
Quincy, Washington. `fips.place_geoid('Quincy', 'WA')` returns 5357115, the
correct place. It was never asked: the ladder passed the model's `IL`.

Weston fails the same way with an extra wrinkle. There is no Weston in
Washington, and `place_geoid('Weston', 'WA')` correctly returns None. The
nearest Weston to Walla Walla is in Umatilla County, Oregon, 25 miles away and
inside the Union-Bulletin's coverage — so the right answer existed and was
reachable. The model said Wisconsin.

## Why the existing scope does not catch it

`source_gazetteer_scope` already records which states a source may match
against: its own state, plus any neighbour that accounts for `BORDER_SHARE` of
the source's own POI build. Both sources above are scoped to WA alone, and the
Union-Bulletin is the kind of border publisher the border rule exists for.

That scope bounds ENTITY MATCHING. It does not bound point resolution, which
is a separate path: the model proposes a place and a state, `resolve_point`
chooses among the proposed cities, and `fips.place_geoid` geocodes the pair.
No step in that sequence reads the source's scope, so the one fact that would
have refused both points is already in the database and unconsulted.

## The shape of the fix

Resolution should treat the model's state as a proposal, not an answer:

1. Geocode the place against each state in the source's scope, own state first.
   A hit there is the point — which corrects Quincy without needing to know the
   model was wrong, because Quincy, WA exists.
2. Where the name resolves in no in-scope state, the model's state is the only
   candidate left and the point is out of scope. Refuse it rather than record
   it. A refused point is the designed outcome for a place that cannot be
   grounded; a point 1,800 miles away is not.
3. Record which state answered, so a later audit can separate "the model was
   right" from "the scope corrected it".

Step 2 costs the Weston point, which is the correct outcome: Oregon is a state
that source plausibly reaches, but it is not in its recorded scope, so the
honest answer is that this corpus cannot place that story. Widening the scope
is a separate decision about `BORDER_SHARE`, and one the Union-Bulletin is a
good argument for.

## Scale

1.2% of the points in this run, and the error is not small when it happens: a
Washington study with a central point in Illinois is worse than no point, which
is why this is a refusal rule and not a ranking preference. The same exposure
applies to every dataset — nothing here is specific to Washington.
