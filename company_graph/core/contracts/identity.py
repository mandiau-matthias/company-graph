"""Identity: identifier schemes, normalisation and the crosswalk contract.

The rule that matters most: an ambiguous match never merges. Only an exact
national-registry identifier (or a verified alias) yields ``exact``; name and
postcode agreement yields ``candidate`` and stays out of every join.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..hashing import content_id

MatchStatus = Literal["exact", "candidate", "unresolved", "conflict"]
EntityScope = Literal["legal_entity", "operating_business", "corporate_group"]

_ALNUM = re.compile(r"[^A-Z0-9]")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.I)

# scheme -> {country, pattern (on the normalised value), national}
IDENTIFIER_SCHEMES: dict[str, dict[str, Any]] = {
    "BE_KBO": {"country": "BE", "pattern": r"^[01][0-9]{9}$", "national": True},
    "FR_SIREN": {"country": "FR", "pattern": r"^[0-9]{9}$", "national": True},
    "FR_SIRET": {"country": "FR", "pattern": r"^[0-9]{14}$", "national": False},
    "SK_ICO": {"country": "SK", "pattern": r"^[0-9]{8}$", "national": True},
    "EE_REGISTRIKOOD": {"country": "EE", "pattern": r"^[0-9]{8}$", "national": True},
    "LT_CODE": {"country": "LT", "pattern": r"^[0-9]{7,9}$", "national": True},
    "LV_REGNUM": {"country": "LV", "pattern": r"^[0-9]{11}$", "national": True},
    "NO_ORGNR": {"country": "NO", "pattern": r"^[0-9]{9}$", "national": True},
    "FI_YTUNNUS": {"country": "FI", "pattern": r"^[0-9]{8}$", "national": True},
    "IE_CRO": {"country": "IE", "pattern": r"^[0-9]{1,7}$", "national": True},
    "GB_COMPANIES_HOUSE": {"country": "GB", "pattern": r"^[A-Z0-9]{8}$", "national": True},
    "DE_HANDELSREGISTER": {"country": "DE", "pattern": r"^[A-Z0-9]{5,40}$", "national": True},
    "LEI": {"country": None, "pattern": r"^[A-Z0-9]{20}$", "national": False},
    "EUID": {"country": None, "pattern": r"^[A-Z]{2}[A-Z0-9]{3,60}$", "national": False},
    "BEAUHURST_COMPANY_ID": {"country": None, "pattern": r"^[A-Z0-9]{1,64}$", "national": False},
    "BEAUHURST_TRUE_COMPANY_ID": {"country": None, "pattern": r"^[A-Z0-9]{1,64}$", "national": False},
    "UPSWITCH_PAGE_SLUG": {"country": None, "pattern": r"^[A-Z0-9]{1,64}$", "national": False},
    "UPSWITCH_COMPANY_NODE_ID": {"country": None, "pattern": r"^[A-F0-9]{32}$", "national": False},
}

NATIONAL_SCHEME_BY_COUNTRY: dict[str, str] = {
    spec["country"]: scheme for scheme, spec in IDENTIFIER_SCHEMES.items() if spec["national"] and spec["country"]
}


def normalize_identifier(scheme: str, value: str) -> str:
    """Upper-case, strip everything that is not A-Z0-9, and validate the shape."""

    if scheme not in IDENTIFIER_SCHEMES:
        raise ValueError(f"unknown identifier scheme {scheme!r}")
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{scheme}: identifier value is empty")
    raw = value.strip()
    if scheme == "UPSWITCH_COMPANY_NODE_ID" and not _UUID.match(raw):
        raise ValueError("UPSWITCH_COMPANY_NODE_ID must be a UUID")
    normalized = _ALNUM.sub("", raw.upper())
    if scheme == "BE_KBO" and len(normalized) == 9:
        normalized = "0" + normalized  # KBO numbers are printed without the leading zero
    if scheme == "GB_COMPANIES_HOUSE" and normalized.isdigit() and len(normalized) < 8:
        normalized = normalized.zfill(8)
    if not re.match(IDENTIFIER_SCHEMES[scheme]["pattern"], normalized):
        raise ValueError(f"{scheme}: {value!r} does not match the scheme shape")
    return normalized


class ExternalIdentifier(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    scheme: str
    value: str
    normalized: str = ""

    @model_validator(mode="after")
    def _normalize(self) -> "ExternalIdentifier":
        normalized = normalize_identifier(self.scheme, self.value)
        if self.normalized and self.normalized != normalized:
            raise ValueError(f"{self.scheme}: normalized value {self.normalized!r} does not match {normalized!r}")
        object.__setattr__(self, "normalized", normalized)
        return self

    @property
    def is_national(self) -> bool:
        return bool(IDENTIFIER_SCHEMES[self.scheme]["national"])

    @property
    def country(self) -> str | None:
        return IDENTIFIER_SCHEMES[self.scheme]["country"]


class UpswitchCompanyKey(BaseModel):
    """The canonical Upswitch key: ``(country_code, registry_number)``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    country_code: str = Field(pattern=r"^[A-Z]{2}$")
    registry_number: str = Field(pattern=r"^[A-Z0-9]{1,32}$")
    page_slug: str | None = None

    @field_validator("page_slug")
    @classmethod
    def _slug(cls, value: str | None) -> str | None:
        if value is not None and not re.match(r"^[a-z]{2}/[a-z0-9][a-z0-9-]{0,251}$", value):
            raise ValueError("page_slug must look like 'be/name-0400268520'")
        return value

    @property
    def subject_id(self) -> str:
        return f"legal_entity:{self.country_code}:{self.registry_number}"


class CrosswalkEntry(BaseModel):
    """One resolved (or deliberately unresolved) link between an external record and Upswitch."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    crosswalk_id: str = ""
    source_system: str = Field(min_length=1)
    source_record_id: str = Field(min_length=1)
    entity_scope: EntityScope = "legal_entity"
    identifiers: tuple[ExternalIdentifier, ...] = ()
    upswitch: UpswitchCompanyKey | None = None
    match_status: MatchStatus
    match_basis: tuple[str, ...] = ()
    confidence: float = Field(ge=0.0, le=1.0)
    candidates: tuple[UpswitchCompanyKey, ...] = ()
    review_required: bool = False
    review_note: str | None = None
    resolved_at: datetime

    @model_validator(mode="after")
    def _rules(self) -> "CrosswalkEntry":
        if self.match_status == "exact" and self.upswitch is None:
            raise ValueError("an exact match must name the Upswitch key")
        if self.match_status != "exact" and self.upswitch is not None:
            raise ValueError("only an exact match may carry an Upswitch key; candidates stay in `candidates`")
        if self.match_status == "exact" and "national_registry_id" not in self.match_basis and "verified_alias" not in self.match_basis:
            raise ValueError("exact matches require a national registry identifier or a verified alias")
        if self.match_status in {"candidate", "conflict"} and not self.review_required:
            raise ValueError(f"a {self.match_status} match must be routed to review")
        if self.resolved_at.tzinfo is None:
            raise ValueError("resolved_at must be timezone-aware")
        if not self.crosswalk_id:
            object.__setattr__(
                self,
                "crosswalk_id",
                content_id(
                    "xwalk",
                    {
                        "source_system": self.source_system,
                        "source_record_id": self.source_record_id,
                        "identifiers": [(i.scheme, i.normalized) for i in self.identifiers],
                        "status": self.match_status,
                        "upswitch": self.upswitch.model_dump() if self.upswitch else None,
                    },
                ),
            )
        return self


LookupFn = Callable[[str, str], Sequence[UpswitchCompanyKey]]


def resolve_crosswalk(
    *,
    source_system: str,
    source_record_id: str,
    identifiers: Iterable[ExternalIdentifier],
    lookup: LookupFn,
    name_postcode_hits: Sequence[UpswitchCompanyKey] = (),
    entity_scope: EntityScope = "legal_entity",
    now: datetime | None = None,
) -> CrosswalkEntry:
    """Deterministic identity resolution that cannot silently merge.

    * one distinct Upswitch key reached through national identifiers -> ``exact``;
    * several distinct keys reached through national identifiers -> ``conflict``;
    * no national identifier but exactly one name+postcode hit -> ``candidate``;
    * otherwise ``unresolved``.
    """

    resolved_at = now or datetime.now(timezone.utc)
    ids = tuple(identifiers)
    keys: dict[tuple[str, str], UpswitchCompanyKey] = {}
    basis: list[str] = []
    for identifier in ids:
        if not identifier.is_national:
            continue
        for key in lookup(identifier.scheme, identifier.normalized):
            keys[(key.country_code, key.registry_number)] = key
        if keys:
            basis.append("national_registry_id")
    common = dict(
        source_system=source_system,
        source_record_id=source_record_id,
        entity_scope=entity_scope,
        identifiers=ids,
        resolved_at=resolved_at,
    )
    if len(keys) == 1:
        (key,) = keys.values()
        return CrosswalkEntry(upswitch=key, match_status="exact", match_basis=("national_registry_id",), confidence=1.0, **common)
    if len(keys) > 1:
        return CrosswalkEntry(
            match_status="conflict",
            match_basis=("national_registry_id",),
            confidence=0.0,
            candidates=tuple(keys.values()),
            review_required=True,
            review_note="national identifiers point at different Upswitch companies",
            **common,
        )
    hits = tuple(name_postcode_hits)
    if len(hits) == 1:
        return CrosswalkEntry(
            match_status="candidate",
            match_basis=("name_postcode",),
            confidence=0.6,
            candidates=hits,
            review_required=True,
            review_note="name and postcode agree; no registry identifier confirms the match",
            **common,
        )
    return CrosswalkEntry(match_status="unresolved", confidence=0.0, candidates=hits, **common)


def registry_alias_rows(
    entry: CrosswalkEntry,
    *,
    source: str,
    run_id: str,
    dataset_version: str | None = None,
    source_license: str | None = None,
    parser_version: str | None = None,
) -> list[dict[str, Any]]:
    """Rows for ``company_registry_aliases`` (migration 109), exact matches only.

    Foreign identifiers are stored as observed aliases of the canonical Upswitch
    key so the provider id survives every later join; the table's uniqueness
    constraint guarantees one provider id never moves between companies silently.
    """

    if entry.match_status != "exact" or entry.upswitch is None:
        return []
    rows: list[dict[str, Any]] = []
    for identifier in entry.identifiers:
        if identifier.scheme == NATIONAL_SCHEME_BY_COUNTRY.get(entry.upswitch.country_code):
            continue  # the national id IS the canonical key, not an alias
        rows.append(
            {
                "country_code": entry.upswitch.country_code,
                "scheme": identifier.scheme[:32],
                "normalized_value": identifier.normalized[:64],
                "display_value": identifier.value,
                "canonical_registry_number": entry.upswitch.registry_number,
                "source": source,
                "parser_version": parser_version,
                "dataset_version": dataset_version,
                "run_id": run_id,
                "source_license": source_license,
                "provenance": {
                    "crosswalk_id": entry.crosswalk_id,
                    "source_system": entry.source_system,
                    "source_record_id": entry.source_record_id,
                    "match_basis": list(entry.match_basis),
                    "entity_scope": entry.entity_scope,
                },
                "verification_status": "observed",
                "is_authoritative": False,
            }
        )
    return rows
