# Institution name variants: measured, and not worth a rule

An institution appears in text under names the gazetteer does not hold.
Missouri articles say `Tolton`, `Tolton Catholic` and `Tolton Catholic
High School`; OSM records `Father Tolton Catholic High School` and the
index held only that, so a story about the school located nothing.

The obvious fix is to generate variants at index build — strip the
honorific, drop the honoured person's given names, expand the
abbreviation, complete `High` to `High School`. Measured over the
Missouri index, 20,651 unambiguous names against every ORG and FAC entity
in the corpus:

| rule | variants articles use | mentions unlocked |
|---|---|---|
| strip everything | 150 | 2,549 |
| require a type word and two words | 36 | 126 |

**The unconstrained rule manufactures the junk we spend our time
removing.** Its top results are `smith` (556 mentions), `campbell` (540),
`truman` (144), `green`, `paul`, `spot` — bare surnames from `Smith Co.`
and `Dr. X Campbell`. A name stripped to a surname stops being an
institution.

**Constrained, it is too small to matter, and still half wrong.** Of the
36 survivors, `mary catholic church`, `paul catholic church` and
`joseph catholic church` come from stripping `St.` — Missouri has dozens
of each — and `catholic high school`, `christian academy`, `fitness
center` and `nazarene church` are generic. What is left is about **60
mentions corpus-wide**: `plaster stadium`, `meyer library`, `crane
stadium`, `sever memorial library`, `keysor elementary school`.

For comparison, loading NCES schools moved accepted points from 32 to 49
on a 215-point sample.

## Why schools worked and the general case does not

NCES names have a known structure: a registry form that always carries a
type word (`HIGH SCHOOL`, `ELEM.`) and a distinctive token. Strip the
honoured person from `MURIEL W. BATTLE HIGH SCHOOL` and `Battle High
School` remains — still a school, still distinctive. OSM names carry no
such guarantee, so the same rules yield `smith`.

Variant generation belongs to the source that guarantees the structure,
which is where it lives: `src/pipeline/school_gazetteer.py`.

## `Father` is one name

Stripping the honorific looked worth doing on its own -- it is rarer than
`St.` and not shared across hundreds of institutions. Missouri holds
**three** `father `-prefixed names and **one** keeps a type word after
stripping: Tolton. A rule for a single instance is worse than the manual
entry that covers it.

## What handles the rest

`crawler gazetteer-place`. A curator can say that in Missouri, Tolton is
Columbia, and take responsibility for it -- which is a judgement, and a
judgement needs somebody's name on it. A rule cannot tell a school from a
person, which is how `Battle` becomes a PERSON and `Clark` a filling
station.
