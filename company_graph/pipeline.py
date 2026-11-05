"""Offline assembly around the original Upswitch identity and assertion contracts."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

from .core.contracts.identity import ExternalIdentifier, UpswitchCompanyKey, resolve_crosswalk
from .core.contracts.assertion import Assertion, Relationship, SourceRef, Subject, TypedValue, reconcile


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Entity(StrictModel):
    country: str
    registry_number: str
    name: str = Field(min_length=1)
    identifiers: list[ExternalIdentifier]


class Fact(StrictModel):
    predicate: str
    value: TypedValue
    evidence_status: str = "reported"
    visibility: str = "public"
    permitted_uses: list[str] = Field(default_factory=lambda: ["display", "redistribute"])


class Record(StrictModel):
    source: SourceRef
    identifiers: list[ExternalIdentifier] = Field(default_factory=list)
    candidate_ids: list[str] = Field(default_factory=list)
    facts: list[Fact] = Field(default_factory=list)


class InputGraph(StrictModel):
    schema_version: int = Field(ge=1, le=1)
    as_of: datetime
    entities: list[Entity]
    records: list[Record]
    relationships: list[Relationship] = Field(default_factory=list)


def publishable(item: Assertion | Relationship, as_of: datetime) -> bool:
    return (item.visibility == "public" and {"display", "redistribute"} <= set(item.permitted_uses)
            and item.evidence_status in {"reported", "verified", "derived"}
            and item.source.retrieved_at <= as_of
            and (item.source.source_date is None or item.source.source_date <= as_of.date())
            and (item.source.effective_date is None or item.source.effective_date <= as_of.date()))


def build_graph(raw: dict[str, Any], base_url: str = "https://example.test/companies") -> dict[str, Any]:
    """Return public-safe graph, review reasons and schema.org markup. Performs no I/O.

    The caller supplies a trusted identity catalogue and normalized source records.
    Identifiers establish matches inside that catalogue, not independent verification.
    """
    data = InputGraph.model_validate(raw)
    if data.as_of.tzinfo is None:
        raise ValueError("as_of must have a timezone")
    parsed = urlsplit(base_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment or parsed.username:
        raise ValueError("base_url must be an HTTPS URL without credentials, query or fragment")
    base_url = base_url.rstrip("/")
    keys: dict[str, UpswitchCompanyKey] = {}
    entities: dict[str, Entity] = {}
    lookup: dict[tuple[str, str], list[UpswitchCompanyKey]] = defaultdict(list)
    for entity in data.entities:
        key = UpswitchCompanyKey(country_code=entity.country, registry_number=entity.registry_number)
        if key.subject_id in keys:
            raise ValueError("duplicate catalogue identity")
        if not any(i.is_national and i.country == entity.country and i.normalized == entity.registry_number for i in entity.identifiers):
            raise ValueError("catalogue identity needs its matching normalized national identifier")
        keys[key.subject_id], entities[key.subject_id] = key, entity
        for identifier in entity.identifiers:
            lookup[(identifier.scheme, identifier.normalized)].append(key)

    assertions: dict[str, Assertion] = {}
    matches, review = [], []
    record_keys: set[tuple[str, str | None]] = set()
    for record in data.records:
        record_key = (record.source.source_system, record.source.source_record_id)
        if record_key in record_keys:
            raise ValueError("duplicate source record; supply each observation once")
        record_keys.add(record_key)
        if record.source.retrieved_at > data.as_of:
            raise ValueError("source observation is later than as_of")
        if any(c not in keys for c in record.candidate_ids):
            raise ValueError("unknown candidate identity")
        crosswalk = resolve_crosswalk(source_system=record.source.source_system,
            source_record_id=record.source.source_record_id or "unspecified",
            identifiers=record.identifiers, lookup=lambda scheme, number: lookup.get((scheme, number), []),
            name_postcode_hits=[keys[c] for c in record.candidate_ids], now=data.as_of)
        matches.append({"source": record.source.source_system, "record": record.source.source_record_id,
                        "status": crosswalk.match_status,
                        "subject": crosswalk.upswitch.subject_id if crosswalk.upswitch else None})
        if not crosswalk.upswitch:
            review.append({"kind": "identity", "record": record.source.source_record_id,
                           "reason": crosswalk.match_status + ": no automatic merge"})
            continue
        subject = Subject(scope="legal_entity", subject_id=crosswalk.upswitch.subject_id)
        for fact in record.facts:
            assertion = Assertion(subject=subject, source=record.source,
                transformation_version="company-graph/0.1", **fact.model_dump())
            previous = assertions.get(assertion.assertion_id)
            if previous is not None and previous != assertion:
                raise ValueError("same assertion has conflicting metadata")
            assertions[assertion.assertion_id] = assertion

    groups = reconcile(assertions.values())
    nodes = []
    for subject_id, entity in entities.items():
        node_groups = [g for g in groups if g.key[0] == subject_id]
        facts, conflicts = [], []
        for group in node_groups:
            if group.selected and publishable(group.selected, data.as_of):
                item = group.selected.model_dump(mode="json", exclude={"raw_source_assertion"})
                facts.append(item)
            if group.review_required:
                # Private candidate values and source metadata never enter the public viewer.
                candidates = [a.model_dump(mode="json", exclude={"raw_source_assertion"})
                              for a in group.candidates if publishable(a, data.as_of)]
                conflicts.append({"predicate": group.key[1], "reason": "Conflicting observations require review", "candidates": candidates})
        key = keys[subject_id]
        url = f"{base_url}/{key.country_code.lower()}-{key.registry_number}.html"
        node = {"id": subject_id, "name": entity.name, "country": key.country_code,
                "registry_number": key.registry_number, "url": url, "facts": facts, "conflicts": conflicts}
        nodes.append(node)
    edges = []
    for relation in data.relationships:
        if relation.from_subject.subject_id not in keys or relation.to_subject.subject_id not in keys:
            raise ValueError("relationship endpoint is not in the catalogue")
        if (publishable(relation, data.as_of)
                and (relation.valid_from is None or relation.valid_from <= data.as_of.date())
                and (relation.valid_until is None or relation.valid_until >= data.as_of.date())):
            if relation.evidence_status == "derived" and any(a not in assertions or not publishable(assertions[a], data.as_of) for a in relation.derived_from):
                continue
            edges.append(relation.model_dump(mode="json"))
    for node in nodes:
        markup: dict[str, Any] = {"@type": "Organization", "@id": node["url"] + "#organization",
            "url": node["url"], "name": node["name"],
            "identifier": {"@type": "PropertyValue", "propertyID": node["country"] + " registry", "value": node["registry_number"]}}
        for fact in node["facts"]:
            if fact["predicate"] == "description" and fact["value"]["kind"] == "text":
                markup["description"] = fact["value"]["value"]
        related = [edge for edge in edges if edge["from_subject"]["subject_id"] == node["id"] and edge["kind"] == "parent_of"]
        if related:
            markup["subOrganization"] = [{"@id": next(n["url"] for n in nodes if n["id"] == e["to_subject"]["subject_id"]) + "#organization"} for e in related]
        node["jsonld"] = markup
    return {"schema_version": 1, "as_of": data.as_of.isoformat(), "nodes": nodes, "edges": edges,
            "matches": matches, "review": review}
