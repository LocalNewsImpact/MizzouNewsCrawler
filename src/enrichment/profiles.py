"""Dataset enrichment profiles (docs/BACKFIELD_IMPLEMENTATION.md §3).

The profile lives at datasets.metadata -> 'enrichment_profile'. Absent means
the default: content gate on, everything else off — a new dataset costs nothing
and still refuses to export cookie text.

Validation failures raise ConfigurationError, which per §5.3 fails the run at
startup before any article is touched. A profile typo must never burn
enrichment_attempts across a dataset.
"""

from __future__ import annotations

from dataclasses import dataclass

# The five per-article metadata presets. geographic_scope is not among them:
# it is controlled by the `scope` flag, because place extraction and point
# resolution depend on it. information_needs is excluded from production by
# decision (proposal §12).
PRODUCTION_PRESETS = ("subject", "topic", "format", "temporal_orientation", "user_need")

# Scope categories a dataset may exclude from export. The two point scopes are
# not excludable: local coverage is the product. elsewhere_to_local is
# excludable but note it means "external events with direct local impact" —
# excluding it drops localized national stories, which is rarely intended.
EXCLUDABLE_SCOPES = (
    "international",
    "national",
    "statewide",
    "regional",
    "other",
    "elsewhere_to_local",
    "local_to_elsewhere",
)

_KNOWN_KEYS = {
    "version",
    "export_exclude_scopes",
    "steady_state_since",
    "content_gate",
    "scope",
    "places",
    "geocode",
    "people",
    "organizations",
    "metadata_presets",
}

_BOOL_KEYS = ("content_gate", "scope", "places", "geocode", "people", "organizations")


class ConfigurationError(ValueError):
    """Invalid enrichment configuration. Fails the run; touches no article."""


@dataclass(frozen=True)
class Profile:
    version: int
    content_gate: bool = True
    scope: bool = False
    places: bool = False
    geocode: bool = False
    people: bool = False
    organizations: bool = False
    metadata_presets: tuple[str, ...] = ()
    # Scope categories whose articles take status 'out_of_scope' and do not
    # export. Dataset-specific; default empty = exclude nothing.
    export_exclude_scopes: tuple[str, ...] = ()
    # Steady-state floor: the scheduled run selects only articles created on or
    # after this ISO date. Without it, enabling a dataset would enrich its
    # entire historical backlog — history is the backfill list's job.
    steady_state_since: str | None = None


DEFAULT_PROFILE = Profile(version=1)


def parse_profile(raw: dict | None) -> Profile:
    if raw is None:
        return DEFAULT_PROFILE
    if not isinstance(raw, dict):
        raise ConfigurationError(
            f"enrichment_profile must be an object, got {type(raw).__name__}"
        )

    unknown = set(raw) - _KNOWN_KEYS
    if unknown:
        raise ConfigurationError(f"unknown profile keys: {sorted(unknown)}")

    version = raw.get("version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise ConfigurationError(f"profile version must be an integer, got {version!r}")

    for key in _BOOL_KEYS:
        if key in raw and not isinstance(raw[key], bool):
            raise ConfigurationError(f"profile key {key!r} must be a boolean")

    presets = raw.get("metadata_presets", [])
    if not isinstance(presets, (list, tuple)) or not all(
        isinstance(p, str) for p in presets
    ):
        raise ConfigurationError("metadata_presets must be a list of strings")
    if "information_needs" in presets:
        raise ConfigurationError(
            "information_needs is excluded from the production path (proposal §12); "
            "our CIN classifier remains authoritative"
        )
    if "geographic_scope" in presets:
        raise ConfigurationError(
            "geographic_scope is controlled by the 'scope' flag, not metadata_presets"
        )
    bad = [p for p in presets if p not in PRODUCTION_PRESETS]
    if bad:
        raise ConfigurationError(
            f"unknown metadata presets {bad}; allowed: {list(PRODUCTION_PRESETS)}"
        )
    if len(set(presets)) != len(presets):
        raise ConfigurationError("metadata_presets contains duplicates")

    since = raw.get("steady_state_since")
    if since is not None:
        import datetime

        try:
            datetime.date.fromisoformat(str(since))
        except ValueError:
            raise ConfigurationError(
                f"steady_state_since must be an ISO date (YYYY-MM-DD), got {since!r}"
            ) from None

    exclude = raw.get("export_exclude_scopes", [])
    if not isinstance(exclude, (list, tuple)) or not all(
        isinstance(x, str) for x in exclude
    ):
        raise ConfigurationError("export_exclude_scopes must be a list of strings")
    bad_scopes = [x for x in exclude if x not in EXCLUDABLE_SCOPES]
    if bad_scopes:
        raise ConfigurationError(
            f"not excludable: {bad_scopes}; allowed: {list(EXCLUDABLE_SCOPES)} "
            "(point scopes are the product and cannot be excluded)"
        )
    if len(set(exclude)) != len(exclude):
        raise ConfigurationError("export_exclude_scopes contains duplicates")

    profile = Profile(
        version=version,
        content_gate=raw.get("content_gate", True),
        scope=raw.get("scope", False),
        places=raw.get("places", False),
        geocode=raw.get("geocode", False),
        people=raw.get("people", False),
        organizations=raw.get("organizations", False),
        metadata_presets=tuple(presets),
        export_exclude_scopes=tuple(exclude),
        steady_state_since=str(since) if since is not None else None,
    )

    if profile.export_exclude_scopes and not profile.scope:
        raise ConfigurationError(
            "export_exclude_scopes requires scope: exclusion is decided by the "
            "scope classification"
        )
    if profile.geocode and not profile.places:
        raise ConfigurationError(
            "geocode requires places: geocoding needs extracted places"
        )
    if profile.places and not profile.scope:
        raise ConfigurationError(
            "places requires scope: the scope gate on 54% of articles is the cost model (§5.2)"
        )
    if profile.geocode:
        raise ConfigurationError(
            "geocode is not implemented in this phase: it requires a geocoder "
            "credential and the geocode_agent adapter (proposal §3 step 4)"
        )
    return profile


def configured_steps(profile: Profile) -> list[str]:
    """The steps this profile asks for, in execution order."""
    steps: list[str] = []
    if profile.content_gate:
        steps.append("content_gate")
    if profile.scope:
        steps.append("scope")
    if profile.places:
        steps.append("places")
    steps.extend(profile.metadata_presets)
    if profile.people:
        steps.append("people")
    if profile.organizations:
        steps.append("organizations")
    return steps


def missing_steps(profile: Profile, steps_applied: list[str]) -> list[str]:
    """The delta a reprocessing run pays for (§8): configured steps that have
    not been applied, in execution order."""
    applied = set(steps_applied or [])
    return [s for s in configured_steps(profile) if s not in applied]
