"""The canonical assertion and relationship contract.

Every new or materially changed fact in the enrichment layer is an
:class:`Assertion`: a typed value about a subject of an explicit scope, with its
source reference, source/effective/retrieval dates, transformation version,
evidence status, conflicts, verification and permitted visibility/use.

Relationships are first-class records with their own evidence and validity
period. A control relationship can never be inferred from a shared officer, and
a consolidated figure can never be reconciled against an entity figure: the
accounting scope is part of the reconciliation key.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..hashing import content_id
from .identity import ExternalIdentifier

SubjectScope = Literal[
    "legal_entity",
    "operating_business",
    "corporate_group",
    "financial_statement",
    "transaction",
    "person_role",
    "security",
]
EvidenceStatus = Literal["reported", "estimated", "derived", "verified", "withdrawn", "contradicted"]
Visibility = Literal["public", "licensed_internal", "tenant_private", "permissioned", "restricted"]
VerificationLevel = Literal[
    "unverified", "source_verified", "owner_attested", "advisor_verified", "independently_verified"
]
AccountingScope = Literal["entity", "consolidated", "combined"]
ValueKind = Literal["money", "number", "ratio", "percent", "text", "code", "date", "boolean", "range_money"]
RelationshipKind = Literal[
    "controls",
    "parent_of",
    "subsidiary_of",
    "owns_shares_in",
    "member_of_operating_business",
    "officer_of",
    "shareholder_of",
    "acquired",
    "merged_into",
    "successor_of",
    "same_as",
    "candidate_same_as",
]

PERMITTED_USES = frozenset(
    {"internal_analysis", "display", "derive", "redistribute", "retain_after_termination", "model_training"}
)
CONTROL_BASES = frozenset(
    {"shareholding_majority", "psc_register", "consolidation_scope", "declared_parent", "provider_true_company"}
)
FORBIDDEN_CONTROL_BASES = frozenset({"shared_officer", "shared_address", "name_similarity"})

_PREDICATE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,159}$")


def _decimal(value: Any, field: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field}: boolean is not a number")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field}: {value!r} is not a decimal number") from exc
    if not result.is_finite():
        raise ValueError(f"{field}: {value!r} is not finite")
    return result


class SourceRef(BaseModel):
    """Where a fact came from, when it was true and when we fetched it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_system: str = Field(min_length=1, max_length=120)
    source_record_id: str | None = Field(default=None, max_length=200)
    source_url: str | None = None
    licence_id: str | None = Field(default=None, max_length=160)
    source_date: date | None = None
    effective_date: date | None = None
    retrieved_at: datetime
    document_sha256: str | None = None

    @model_validator(mode="after")
    def _rules(self) -> "SourceRef":
        if self.retrieved_at.tzinfo is None:
            raise ValueError("retrieved_at must be timezone-aware")
        if self.source_url is not None and not self.source_url.startswith("https://"):
            raise ValueError("source_url must be https")
        if self.document_sha256 is not None and not _SHA256.match(self.document_sha256):
            raise ValueError("document_sha256 must look like sha256:<64 hex>")
        return self


class TypedValue(BaseModel):
    """A value that always carries its kind, unit, currency, period and basis."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    kind: ValueKind
    value: Any
    currency: str | None = None
    unit: str | None = Field(default=None, max_length=40)
    period_start: date | None = None
    period_end: date | None = None
    accounting_scope: AccountingScope | None = None
    basis: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def _rules(self) -> "TypedValue":
        kind, value = self.kind, self.value
        if kind in {"money", "range_money"}:
            if not self.currency or not _CURRENCY.match(self.currency):
                raise ValueError(f"{kind} values require an ISO-4217 currency")
        elif self.currency is not None:
            raise ValueError(f"{kind} values must not carry a currency")
        if kind == "money":
            object.__setattr__(self, "value", _decimal(value, "money"))
        elif kind in {"number", "ratio", "percent"}:
            object.__setattr__(self, "value", _decimal(value, kind))
        elif kind == "range_money":
            if not isinstance(value, Mapping) or set(value) - {"low", "mid", "high"} or "low" not in value or "high" not in value:
                raise ValueError("range_money value must be a mapping with low, high and optional mid")
            low, high = _decimal(value["low"], "low"), _decimal(value["high"], "high")
            if low > high:
                raise ValueError("range_money low exceeds high")
            rendered = {"low": low, "high": high}
            if value.get("mid") is not None:
                mid = _decimal(value["mid"], "mid")
                if not (low <= mid <= high):
                    raise ValueError("range_money mid must sit inside the range")
                rendered["mid"] = mid
            object.__setattr__(self, "value", rendered)
        elif kind == "date":
            if isinstance(value, str):
                object.__setattr__(self, "value", date.fromisoformat(value))
            elif not isinstance(value, date):
                raise ValueError("date value must be a date")
        elif kind == "boolean":
            if not isinstance(value, bool):
                raise ValueError("boolean value must be a bool")
        elif kind in {"text", "code"}:
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{kind} value must be a non-empty string")
        if self.period_start and self.period_end and self.period_start > self.period_end:
            raise ValueError("period_start is after period_end")
        return self


class Verification(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    level: VerificationLevel = "unverified"
    verified_by_principal: str | None = None
    verified_at: datetime | None = None
    receipt_id: str | None = None

    @model_validator(mode="after")
    def _rules(self) -> "Verification":
        if self.level != "unverified" and self.verified_at is None:
            raise ValueError("a verified fact needs verified_at")
        return self


class Subject(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: SubjectScope
    subject_id: str = Field(min_length=3, max_length=200)
    identifiers: tuple[ExternalIdentifier, ...] = ()

    @model_validator(mode="after")
    def _rules(self) -> "Subject":
        if not self.subject_id.startswith(f"{self.scope}:"):
            raise ValueError(f"subject_id must start with '{self.scope}:'")
        return self


class Assertion(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    assertion_id: str = ""
    subject: Subject
    predicate: str
    value: TypedValue
    source: SourceRef
    transformation_version: str
    evidence_status: EvidenceStatus = "reported"
    visibility: Visibility
    permitted_uses: tuple[str, ...] = ("internal_analysis",)
    verification: Verification = Verification()
    conflicts_with: tuple[str, ...] = ()
    supersedes: str | None = None
    raw_source_assertion: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _rules(self) -> "Assertion":
        if not _PREDICATE.match(self.predicate):
            raise ValueError("predicate must be snake_case")
        if not _VERSION.match(self.transformation_version):
            raise ValueError("transformation_version has an invalid shape")
        unknown = set(self.permitted_uses) - PERMITTED_USES
        if unknown:
            raise ValueError(f"unknown permitted uses: {sorted(unknown)}")
        if self.visibility == "public" and "display" not in self.permitted_uses:
            raise ValueError("a public assertion must permit display")
        if self.evidence_status == "verified" and self.verification.level == "unverified":
            raise ValueError("evidence_status 'verified' requires a verification level")
        if self.value.kind in {"money", "range_money", "number", "ratio", "percent"} and self.subject.scope == "financial_statement" and self.value.accounting_scope is None:
            raise ValueError("financial-statement values must state their accounting scope")
        computed = content_id(
            "asrt",
            {
                "subject": self.subject.subject_id,
                "predicate": self.predicate,
                "value": self.value.model_dump(mode="python"),
                "source": {
                    "system": self.source.source_system,
                    "record": self.source.source_record_id,
                    "effective": self.source.effective_date,
                    "source_date": self.source.source_date,
                },
                "transformation_version": self.transformation_version,
                "evidence_status": self.evidence_status,
            },
        )
        if self.assertion_id and self.assertion_id != computed:
            raise ValueError("assertion_id does not match the assertion content")
        object.__setattr__(self, "assertion_id", computed)
        return self

    def reconciliation_key(self) -> tuple[str, str, date | None, AccountingScope | None, str | None]:
        return (
            self.subject.subject_id,
            self.predicate,
            self.value.period_end,
            self.value.accounting_scope,
            self.value.basis,
        )


class Relationship(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    relationship_id: str = ""
    kind: RelationshipKind
    from_subject: Subject
    to_subject: Subject
    attributes: dict[str, Any] = Field(default_factory=dict)
    valid_from: date | None = None
    valid_until: date | None = None
    source: SourceRef
    transformation_version: str
    evidence_status: EvidenceStatus = "reported"
    visibility: Visibility
    permitted_uses: tuple[str, ...] = ("internal_analysis",)
    derived_from: tuple[str, ...] = ()
    derivation_rule: str | None = None

    @model_validator(mode="after")
    def _rules(self) -> "Relationship":
        if self.from_subject.subject_id == self.to_subject.subject_id and self.kind not in {"same_as", "candidate_same_as"}:
            raise ValueError("a relationship needs two different subjects")
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValueError("valid_until is before valid_from")
        if self.kind in {"controls", "parent_of", "subsidiary_of"}:
            basis = self.attributes.get("control_basis")
            if basis in FORBIDDEN_CONTROL_BASES:
                raise ValueError(f"control cannot be inferred from {basis}")
            if basis not in CONTROL_BASES:
                raise ValueError("control relationships need a control_basis from the allowed set")
        if self.kind in {"owns_shares_in", "shareholder_of"} and "percentage" in self.attributes:
            pct = _decimal(self.attributes["percentage"], "percentage")
            if not (0 <= pct <= 100):
                raise ValueError("percentage must be within 0..100")
        if self.evidence_status == "derived" and not self.derived_from:
            raise ValueError("a derived relationship must reference what it was derived from")
        if self.kind == "same_as" and self.evidence_status not in {"verified", "reported"}:
            raise ValueError("same_as requires reported or verified evidence; use candidate_same_as otherwise")
        computed = content_id(
            "rel",
            {
                "kind": self.kind,
                "from": self.from_subject.subject_id,
                "to": self.to_subject.subject_id,
                "attributes": self.attributes,
                "valid_from": self.valid_from,
                "valid_until": self.valid_until,
                "source": (self.source.source_system, self.source.source_record_id),
                "transformation_version": self.transformation_version,
            },
        )
        if self.relationship_id and self.relationship_id != computed:
            raise ValueError("relationship_id does not match the relationship content")
        object.__setattr__(self, "relationship_id", computed)
        return self


_STATUS_RANK = {"verified": 4, "reported": 3, "derived": 2, "estimated": 1, "withdrawn": 0, "contradicted": 0}


class Reconciliation(BaseModel):
    """The selected interpretation of one fact, with the raw candidates kept."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: tuple[str, str, date | None, str | None, str | None]
    selected: Assertion | None
    candidates: tuple[Assertion, ...]
    conflict: bool
    review_required: bool
    reason: str


def _numeric(assertion: Assertion) -> Decimal | None:
    if assertion.value.kind in {"money", "number", "ratio", "percent"}:
        return assertion.value.value
    return None


def reconcile(assertions: Iterable[Assertion], *, tolerance: Decimal = Decimal("0.005")) -> list[Reconciliation]:
    """Group assertions by (subject, predicate, period, scope, basis) and pick one.

    Precedence: verified > reported > derived > estimated. Two live candidates
    of the same rank that disagree by more than ``tolerance`` (relative) are a
    material conflict: nothing is selected and the group is routed to review.
    An estimate is never promoted over a reported figure, and never relabelled.
    An amended filing that names the assertion it ``supersedes`` replaces it
    silently: the superseded candidate is kept in the group but not selected.
    """

    groups: dict[tuple, list[Assertion]] = {}
    for assertion in assertions:
        groups.setdefault(assertion.reconciliation_key(), []).append(assertion)
    results: list[Reconciliation] = []
    for key, members in groups.items():
        superseded = {m.supersedes for m in members if m.supersedes}
        live = [m for m in members if m.evidence_status not in {"withdrawn", "contradicted"} and m.assertion_id not in superseded]
        if not live:
            results.append(Reconciliation(key=key, selected=None, candidates=tuple(members), conflict=False, review_required=False, reason="all candidates withdrawn"))
            continue
        top_rank = max(_STATUS_RANK[m.evidence_status] for m in live)
        top = [m for m in live if _STATUS_RANK[m.evidence_status] == top_rank]
        # Automatron extraction: unlike units/currencies are not comparable values.
        dimensions = {(m.value.kind, m.value.currency, m.value.unit, m.value.period_start) for m in top}
        if len(dimensions) > 1:
            results.append(Reconciliation(key=key, selected=None, candidates=tuple(members), conflict=True, review_required=True, reason="incompatible value dimensions require review"))
            continue
        values = [v for v in (_numeric(m) for m in top) if v is not None]
        if len(top) > 1 and values and len(values) == len(top):
            lo, hi = min(values), max(values)
            scale = max(abs(lo), abs(hi))
            if scale and (hi - lo) / scale > tolerance:
                results.append(Reconciliation(key=key, selected=None, candidates=tuple(members), conflict=True, review_required=True, reason=f"{len(top)} {top[0].evidence_status} values disagree: {lo} vs {hi}"))
                continue
        if len(top) > 1 and not values:
            distinct = {str(m.value.value) for m in top}
            if len(distinct) > 1:
                results.append(Reconciliation(key=key, selected=None, candidates=tuple(members), conflict=True, review_required=True, reason=f"{len(top)} {top[0].evidence_status} values disagree"))
                continue
        selected = sorted(top, key=lambda m: (m.source.retrieved_at, m.assertion_id))[-1]
        results.append(Reconciliation(key=key, selected=selected, candidates=tuple(members), conflict=False, review_required=False, reason=f"selected {selected.evidence_status} value from {selected.source.source_system}"))
    return results
