"""Deterministic content hashing shared by every contract in the layer."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any


def canonical_value(value: Any) -> Any:
    """Return a JSON-serialisable value with a stable, type-faithful rendering."""

    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        # Floats are rendered through Decimal so 0.1 hashes the same everywhere.
        return format(Decimal(repr(value)), "f")
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return canonical_value(value.value)
    if isinstance(value, dict):
        return {str(key): canonical_value(item) for key, item in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [canonical_value(item) for item in value]
        if isinstance(value, (set, frozenset)):
            items = sorted(items, key=lambda item: json.dumps(item, sort_keys=True))
        return items
    if hasattr(value, "model_dump"):
        return canonical_value(value.model_dump(mode="python"))
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        canonical_value(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def sha256_prefixed(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def content_hash(value: Any) -> str:
    """``sha256:<hex>`` of the canonical JSON rendering of ``value``."""

    return sha256_prefixed(canonical_json_bytes(value))


def content_id(prefix: str, value: Any) -> str:
    """Short stable identifier: ``<prefix>:<first 32 hex chars>``."""

    return f"{prefix}:{content_hash(value)[7:39]}"
