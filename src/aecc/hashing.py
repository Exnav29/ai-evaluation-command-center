"""Deterministic definition hashing for registered test versions.

The hash covers all evaluation-relevant inputs so that a correction or
silent edit is detectable and reproducible. It is a content-integrity
mechanism, not a secrecy mechanism.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


HASH_FIELDS = (
    "task_prompt",
    "acceptance_criteria",
    "rubric_id",
    "rubric_version",
    "source_fixture_ref",
    "source_commit",
    "permission_profile",
    "retry_policy",
    "timeout_seconds",
    "expected_artifacts",
    "capability_key",
)


def _normalize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _normalize(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [_normalize(v) for v in value]
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def build_definition_payload(
    *,
    task_prompt: str,
    acceptance_criteria: str,
    rubric_id: str,
    rubric_version: str,
    source_fixture_ref: str | None = None,
    source_commit: str | None = None,
    permission_profile: str | None = None,
    retry_policy: Any = None,
    timeout_seconds: int | None = None,
    expected_artifacts: Any = None,
    capability_key: str | None = None,
) -> dict:
    """Build the canonical payload dict covered by the definition hash."""
    raw = {
        "task_prompt": task_prompt,
        "acceptance_criteria": acceptance_criteria,
        "rubric_id": rubric_id,
        "rubric_version": rubric_version,
        "source_fixture_ref": source_fixture_ref,
        "source_commit": source_commit,
        "permission_profile": permission_profile,
        "retry_policy": retry_policy,
        "timeout_seconds": timeout_seconds,
        "expected_artifacts": expected_artifacts,
        "capability_key": capability_key,
    }
    return {k: _normalize(v) for k, v in raw.items()}


def canonical_definition_hash(payload: Mapping[str, Any]) -> str:
    """Compute a deterministic SHA-256 hex digest over the frozen definition."""
    normalized = _normalize(dict(payload))
    # Only hash the known evaluation-relevant fields; ignore extras explicitly
    # so unknown metadata cannot silently change the meaning of the hash.
    relevant = {k: normalized.get(k) for k in HASH_FIELDS}
    canonical = json.dumps(relevant, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
