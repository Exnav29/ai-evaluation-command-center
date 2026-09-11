"""Presentation helpers: formatting + badge classes with evidence semantics.

Rules enforced here and in templates:
- UNKNOWN/unscored is never styled or labeled as success;
- missing cost/tokens (None) render as unknown/not recorded, never zero;
- process outcome, deliverable outcome, task outcome, and evaluator verdict
  keep separate labels and badge treatments;
- exit code is a raw fact and is never translated into a task verdict.
"""

from __future__ import annotations

from datetime import datetime

PASS_VERDICTS = frozenset({"PASS", "PASS_WITH_FINDINGS"})


def format_cost(cost: float | None) -> str:
    """None -> unknown; numeric (including 0.0) -> dollar amount."""
    if cost is None:
        return "Not recorded"
    return f"${cost:.2f}"


def format_cost_title(cost: float | None, source: str | None) -> str:
    if cost is None:
        return "Cost unknown / not recorded (not zero)"
    base = f"${cost:.4f}"
    if source:
        base += f" · source: {source}"
    return base


def format_tokens(value: int | None) -> str:
    if value is None:
        return "Not recorded"
    return str(value)


def format_elapsed(seconds: float | None) -> str:
    if seconds is None:
        return "Not recorded"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = seconds / 60
    return f"{minutes:.1f} min"


def format_dt(value: datetime | None) -> str:
    if value is None:
        return "—"
    try:
        return value.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return str(value)


def verdict_label(verdict) -> str:
    if verdict is None:
        return "UNKNOWN"
    try:
        return verdict.value
    except AttributeError:
        return str(verdict)


def is_pass_verdict(verdict) -> bool:
    return verdict_label(verdict) in PASS_VERDICTS


def badge_class(kind: str, value: str | None) -> str:
    """CSS badge class. UNKNOWN always maps to badge-unknown (never success)."""
    v = (value or "UNKNOWN").upper()
    if kind == "verdict":
        return {
            "PASS": "badge-pass",
            "PASS_WITH_FINDINGS": "badge-pass-findings",
            "FAIL": "badge-fail",
            "NEEDS_REVIEW": "badge-review",
            "INFRASTRUCTURE_FAILURE": "badge-infra",
            "EXCLUDED": "badge-excluded",
            "UNKNOWN": "badge-unknown",
        }.get(v, "badge-unknown")
    if kind == "process":
        return {
            "SUCCESS": "badge-neutral",
            "FAILURE": "badge-fail",
            "TIMEOUT": "badge-review",
            "CANCELLED": "badge-excluded",
            "UNKNOWN": "badge-unknown",
        }.get(v, "badge-unknown")
    if kind == "task":
        return {
            "SUCCEEDED": "badge-pass",
            "FAILED": "badge-fail",
            "NEEDS_REVIEW": "badge-review",
            "NOT_EVALUATED": "badge-unknown",
            "UNKNOWN": "badge-unknown",
        }.get(v, "badge-unknown")
    if kind == "deliverable":
        return {
            "PRESENT": "badge-pass",
            "MISSING": "badge-fail",
            "NOT_CHECKED": "badge-unknown",
            "UNKNOWN": "badge-unknown",
        }.get(v, "badge-unknown")
    if kind == "qual":
        return {
            "QUALIFIED": "badge-pass",
            "SHADOW": "badge-review",
            "RESTRICTED": "badge-review",
            "UNQUALIFIED": "badge-unknown",
            "NOT_AUTHORIZED": "badge-excluded",
        }.get(v, "badge-unknown")
    if kind == "runstate":
        if v in ("COMPLETED", "FINALIZED"):
            return "badge-neutral"
        if v in ("NEEDS_REVIEW",):
            return "badge-review"
        if v in ("INFRASTRUCTURE_FAILURE", "CANCELLED", "EXCLUDED"):
            return "badge-fail"
        if v in ("QUEUED", "CLAIMED", "RUNNING", "SCORING"):
            return "badge-progress"
        return "badge-unknown"
    if kind == "computed":
        # Deterministic computed qualification states. UNKNOWN-adjacent
        # (INSUFFICIENT_EVIDENCE) is never styled as success.
        return {
            "QUALIFIED_AUTONOMOUS": "badge-pass",
            "QUALIFIED — AUTONOMOUS": "badge-pass",
            "QUALIFIED_REVIEW_REQUIRED": "badge-review",
            "QUALIFIED — REVIEW REQUIRED": "badge-review",
            "QUALIFIED_ESCALATE_ON_CONDITIONS": "badge-review",
            "QUALIFIED — ESCALATE ON CONDITIONS": "badge-review",
            "PROVISIONALLY_QUALIFIED": "badge-neutral",
            "PROVISIONALLY QUALIFIED": "badge-neutral",
            "INSUFFICIENT_EVIDENCE": "badge-unknown",
            "INSUFFICIENT EVIDENCE": "badge-unknown",
            "NOT_QUALIFIED": "badge-fail",
            "NOT QUALIFIED": "badge-fail",
        }.get(v, "badge-unknown")
    if kind == "evidence":
        return {
            "PASS": "badge-pass",
            "PASS_WITH_FINDINGS": "badge-pass-findings",
            "NEEDS_REVIEW": "badge-review",
            "FAIL": "badge-fail",
            "UNKNOWN": "badge-unknown",
            "INFRASTRUCTURE": "badge-infra",
            "EXCLUDED": "badge-excluded",
        }.get(v, "badge-unknown")
    return "badge-unknown"
