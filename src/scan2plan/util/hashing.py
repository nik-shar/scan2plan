"""Content-addressed hashing for the deterministic cache (plan 01 section 7)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

_CHUNK = 1 << 20  # 1 MiB
_CHUNK = 1 << 20  # 1 MiB


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_file(path: str | Path) -> str:
    """SHA-256 of a file's bytes, streamed in chunks."""
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def hash_json(obj: Any) -> str:
    """SHA-256 of a canonical JSON encoding (sorted keys, compact)."""
    canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return hash_bytes(canonical.encode("utf-8"))


def cache_key(*, inputs: Iterable[str], config_digest: str, code_version: str) -> str:
    """Deterministic cache key from input hashes + config + code version."""
    payload = {
        "inputs": sorted(inputs),
        "config": config_digest,
        "code": code_version,
    }
    return hash_json(payload)
