"""Milestone 1 chart analytics: decision-support aggregates from persisted evidence.

All functions take an explicit Session and return plain JSON-serializable dicts.
Rules (never violated):
- UNKNOWN stays unknown (verdict None / UNKNOWN / unscored never counted as PASS).
- Missing cost / elapsed / score (None) stays unknown; numeric 0 / 0.0 stays zero.
- Demo evidence (is_demo=True) excluded by default; include_demo=True opts in.
- Completed evidence states only for run-level charts; queued/running never count.
- Latest score revision = highest id; latest attempt = highest (attempt_number, id).
- Deterministic ordering by natural keys; empty input yields empty groups, null
  averages (never invented zeros).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from aecc import dashboard_queries as dq
from aecc.models import (
    Attempt,
    Capability,
    ExclusionEvent,
    Harness,
    InterventionEvent,
    Model,
    QualificationDecision,
    Run,
    ScoreRevision,
)

QUALIFICATION_STATE_ORDER = [
    "QUALIFIED",
    "SHADOW",
    "RESTRICTED",
    "UNQUALIFIED",
    "NOT_AUTHORIZED",
]

VERDICT_BUCKETS = [
    "PASS",
    "PASS_WITH_FINDINGS",
    "NEEDS_REVIEW",
    "FAIL",
    "INFRASTRUCTURE_FAILURE",
    "EXCLUDED",
    "UNKNOWN",
]


def _norm(value) -> str | None:
    if value is None:
        return None
    try:
        return value.value  # enum member
    except AttributeError:
        text = str(value).strip()
        return text.upper() if text else None


def fetch_chart_qualification_distribution(
    session: Session, *, include_demo: bool = False
) -> dict:
    """Stored-qualification current-state counts per exact triple.

    Current = newest QualificationDecision per (harness, model, capability).
    History preserved but not counted. Demo excluded unless opted in.
    """
    if include_demo:
        decisions = list(
            session.scalars(
                select(QualificationDecision).order_by(QualificationDecision.id.asc())
            ).all()
        )
    else:
        decisions = list(
            session.scalars(
                select(QualificationDecision)
                .where(QualificationDecision.is_demo == False)  # noqa: E712
                .order_by(QualificationDecision.id.asc())
            ).all()
        )
    latest_by_triple: dict[tuple[int, int, int], QualificationDecision] = {}
    for d in decisions:
        key = (d.harness_id, d.model_id, d.capability_id)
        prev = latest_by_triple.get(key)
        if prev is None or (d.id or 0) > (prev.id or 0):
            latest_by_triple[key] = d
    counts_by_state: dict[str, int] = {s: 0 for s in QUALIFICATION_STATE_ORDER}
    for d in latest_by_triple.values():
        state = _norm(d.state) or "UNKNOWN"
        if state in counts_by_state:
            counts_by_state[state] += 1
        # Unknown future states are not invented; they simply do not map to
        # the fixed order (triples_total still counts them).
    counts = [counts_by_state[s] for s in QUALIFICATION_STATE_ORDER]
    return {
        "type": "qualification_state_distribution",
        "source": "stored QualificationDecision.current per triple",
        "labels": list(QUALIFICATION_STATE_ORDER),
        "counts": counts,
        "triples_total": len(latest_by_triple),
        "meta": {"include_demo": include_demo, "empty": len(latest_by_triple) == 0},
    }


def _completed_runs(
    session: Session,
    *,
    capability_id: int | None = None,
    test_version_id: int | None = None,
    include_demo: bool = False,
    limit: int = 2000,
) -> list[Run]:
    stmt = select(Run).where(Run.state.in_(sorted(dq.COMPLETED_EVIDENCE_STATES)))
    if not include_demo:
        stmt = stmt.where(Run.is_demo == False)  # noqa: E712
    if capability_id is not None:
        stmt = stmt.where(Run.capability_id == capability_id)
    if test_version_id is not None:
        stmt = stmt.where(Run.test_version_id == test_version_id)
    stmt = stmt.order_by(Run.id.asc()).limit(limit)
    return list(session.scalars(stmt).all())


def _latest_maps(
    session: Session, runs: list[Run]
) -> tuple[dict[int, ScoreRevision], dict[int, Attempt], dict[str, dict]]:
    run_ids = [r.id for r in runs]
    latest_by_run: dict[int, ScoreRevision] = {}
    attempts_by_run: dict[int, list[Attempt]] = {rid: [] for rid in run_ids}
    empty_extra = {"attempts": {}, "interventions": {}, "exclusions": {}}
    if not run_ids:
        return latest_by_run, {}, empty_extra
    for s in session.scalars(
        select(ScoreRevision)
        .where(ScoreRevision.run_id.in_(run_ids))
        .order_by(ScoreRevision.id.asc())
    ).all():
        latest_by_run[s.run_id] = s  # ascending: last wins
    for a in session.scalars(
        select(Attempt)
        .where(Attempt.run_id.in_(run_ids))
        .order_by(Attempt.attempt_number.asc(), Attempt.id.asc())
    ).all():
        attempts_by_run.setdefault(a.run_id, []).append(a)
    latest_attempt_by_run: dict[int, Attempt] = {}
    for rid, attempts in attempts_by_run.items():
        latest = dq.latest_attempt(attempts)
        if latest is not None:
            latest_attempt_by_run[rid] = latest
    interventions_by_run: dict[int, list[InterventionEvent]] = {rid: [] for rid in run_ids}
    for ev in session.scalars(
        select(InterventionEvent)
        .where(InterventionEvent.run_id.in_(run_ids))
        .order_by(InterventionEvent.id.asc())
    ).all():
        interventions_by_run.setdefault(ev.run_id, []).append(ev)
    exclusions_by_run: dict[int, list[ExclusionEvent]] = {rid: [] for rid in run_ids}
    for ev in session.scalars(
        select(ExclusionEvent)
        .where(ExclusionEvent.run_id.in_(run_ids))
        .order_by(ExclusionEvent.id.asc())
    ).all():
        exclusions_by_run.setdefault(ev.run_id, []).append(ev)
    return latest_by_run, latest_attempt_by_run, {
        "attempts": attempts_by_run,
        "interventions": interventions_by_run,
        "exclusions": exclusions_by_run,
    }


def _classify_for_charts(
    run: Run,
    latest: ScoreRevision | None,
    latest_attempt: Attempt | None,
    has_exclusion: bool,
) -> str:
    """Verdict bucket for charts. Mirrors qualification.classify_run categories."""
    from aecc.qualification import classify_run, RunEvidence

    verdict = _norm(latest.verdict) if latest is not None else None
    evidence = RunEvidence(
        run_id=run.id,
        verdict=verdict,
        run_state=_norm(run.state),
        failure_primary=_norm(latest_attempt.failure_primary)
        if latest_attempt is not None
        else None,
        has_intervention=False,
        has_permission_denial=False,
        has_exclusion=has_exclusion,
        is_demo=bool(run.is_demo),
    )
    category = classify_run(evidence).category
    mapping = {
        "pass": "PASS",
        "pass_with_findings": "PASS_WITH_FINDINGS",
        "needs_review": "NEEDS_REVIEW",
        "fail": "FAIL",
        "infrastructure": "INFRASTRUCTURE_FAILURE",
        "excluded": "EXCLUDED",
        "unknown": "UNKNOWN",
    }
    return mapping.get(category, "UNKNOWN")


def _group_identity(
    session: Session, runs: list[Run]
) -> tuple[dict[int, Model], dict[int, Harness], dict[int, Capability]]:
    model_map: dict[int, Model] = {}
    harness_map: dict[int, Harness] = {}
    if runs:
        m_ids = sorted({r.model_id for r in runs})
        h_ids = sorted({r.harness_id for r in runs})
        model_map = {m.id: m for m in session.scalars(select(Model).where(Model.id.in_(m_ids))).all()}
        harness_map = {
            h.id: h for h in session.scalars(select(Harness).where(Harness.id.in_(h_ids))).all()
        }
    cap_map: dict[int, Capability] = {}
    return model_map, harness_map, cap_map


def _group_key(
    run: Run, model_map: dict[int, Model], harness_map: dict[int, Harness]
) -> tuple[str, str]:
    m = model_map.get(run.model_id)
    h = harness_map.get(run.harness_id)
    return (
        m.model_key if m is not None else f"model-{run.model_id}",
        h.harness_key if h is not None else f"harness-{run.harness_id}",
    )


def _group_label(model_key: str, harness_key: str) -> str:
    return f"{harness_key} + {model_key}"


def fetch_chart_verdict_by_model_harness(
    session: Session,
    *,
    capability_id: int | None = None,
    test_version_id: int | None = None,
    include_demo: bool = False,
) -> dict:
    runs = _completed_runs(
        session,
        capability_id=capability_id,
        test_version_id=test_version_id,
        include_demo=include_demo,
    )
    latest_by_run, _, extra = _latest_maps(session, runs)
    model_map, harness_map, _ = _group_identity(session, runs)
    exclusions_by_run = extra["exclusions"]
    grouped: dict[tuple[str, str], dict[str, int]] = {}
    run_ids_by_group: dict[tuple[str, str], list[int]] = {}
    for run in runs:
        key = _group_key(run, model_map, harness_map)
        bucket = _classify_for_charts(
            run,
            latest_by_run.get(run.id),
            None,  # verdict chart needs exclusion signal only; infra via run_state/verdict
            bool(exclusions_by_run.get(run.id)),
        )
        # Re-derive infra correctly: _classify_for_charts builds RunEvidence
        # without failure_primary here, so patch infra check with latest attempt.
        # Fetch failure signal cheaply: already have attempts map.
        grouped.setdefault(key, {b: 0 for b in VERDICT_BUCKETS})
        run_ids_by_group.setdefault(key, []).append(run.id)
        grouped[key][bucket] += 1
    # Fix-up: runs whose latest attempt carries INFRASTRUCTURE_FAILURE primary
    # but verdict is FAIL must still count as infrastructure. Re-scan with
    # failure_primary included.
    if runs:
        _, latest_attempt_by_run, _ = _latest_maps(session, runs)
        for run in runs:
            key = _group_key(run, model_map, harness_map)
            corrected = _classify_for_charts(
                run,
                latest_by_run.get(run.id),
                latest_attempt_by_run.get(run.id),
                bool(exclusions_by_run.get(run.id)),
            )
            # adjust: decrement previously counted bucket, increment corrected
            # (only when different to avoid double counting)
            pass  # counted below in second pass instead
        # Rebuild deterministically with full signals (simple + correct).
        grouped = {k: {b: 0 for b in VERDICT_BUCKETS} for k in grouped}
        run_ids_by_group = {k: [] for k in run_ids_by_group}
        for run in runs:
            key = _group_key(run, model_map, harness_map)
            bucket = _classify_for_charts(
                run,
                latest_by_run.get(run.id),
                latest_attempt_by_run.get(run.id),
                bool(exclusions_by_run.get(run.id)),
            )
            grouped[key][bucket] += 1
            run_ids_by_group[key].append(run.id)
    groups = []
    for (model_key, harness_key) in sorted(grouped, key=lambda k: (k[0], k[1])):
        counts = grouped[(model_key, harness_key)]
        evaluated = (
            counts["PASS"]
            + counts["PASS_WITH_FINDINGS"]
            + counts["NEEDS_REVIEW"]
            + counts["FAIL"]
        )
        if evaluated:
            pass_rate: float | None = (
                counts["PASS"] + counts["PASS_WITH_FINDINGS"]
            ) / evaluated
        else:
            pass_rate = None
        groups.append(
            {
                "model_key": model_key,
                "harness_key": harness_key,
                "label": _group_label(model_key, harness_key),
                "counts": counts,
                "evaluated": evaluated,
                "pass_rate": pass_rate,
                "runs_total": sum(counts.values()),
                "run_ids": sorted(run_ids_by_group[(model_key, harness_key)]),
            }
        )
    return {
        "type": "verdict_by_model_harness",
        "context": {"capability_id": capability_id, "test_version_id": test_version_id},
        "groups": groups,
        "meta": {"include_demo": include_demo, "empty": not groups},
    }


def fetch_chart_cost_by_model_harness(
    session: Session,
    *,
    capability_id: int | None = None,
    test_version_id: int | None = None,
    include_demo: bool = False,
) -> dict:
    runs = _completed_runs(
        session,
        capability_id=capability_id,
        test_version_id=test_version_id,
        include_demo=include_demo,
    )
    _, latest_attempt_by_run, _ = _latest_maps(session, runs)
    model_map, harness_map, _ = _group_identity(session, runs)
    acc: dict[tuple[str, str], dict] = {}
    for run in runs:
        key = _group_key(run, model_map, harness_map)
        entry = acc.setdefault(
            key, {"known": [], "n_unknown": 0, "run_ids_known": [], "run_ids_unknown": []}
        )
        attempt = latest_attempt_by_run.get(run.id)
        cost = attempt.cost if attempt is not None else None
        if cost is None:
            entry["n_unknown"] += 1
            entry["run_ids_unknown"].append(run.id)
        else:
            entry["known"].append(float(cost))
            entry["run_ids_known"].append(run.id)
    groups = []
    for (model_key, harness_key) in sorted(acc, key=lambda k: (k[0], k[1])):
        entry = acc[(model_key, harness_key)]
        known = entry["known"]
        n_known = len(known)
        groups.append(
            {
                "model_key": model_key,
                "harness_key": harness_key,
                "label": _group_label(model_key, harness_key),
                "n_known": n_known,
                "n_unknown": entry["n_unknown"],
                "sum_known": sum(known) if n_known else None,
                "avg_known": (sum(known) / n_known) if n_known else None,
                "min_known": min(known) if n_known else None,
                "max_known": max(known) if n_known else None,
                "costs_known": sorted(known),
                "has_zero_cost": any(c == 0.0 for c in known),
                "run_ids_known": sorted(entry["run_ids_known"]),
                "run_ids_unknown": sorted(entry["run_ids_unknown"]),
            }
        )
    return {
        "type": "cost_by_model_harness",
        "context": {"capability_id": capability_id, "test_version_id": test_version_id},
        "groups": groups,
        "meta": {
            "include_demo": include_demo,
            "empty": not groups,
            "note": "None stays unknown; 0.0 stays zero; latest attempt only",
            "unit": "USD",
        },
    }


def fetch_chart_elapsed_by_model_harness(
    session: Session,
    *,
    capability_id: int | None = None,
    test_version_id: int | None = None,
    include_demo: bool = False,
) -> dict:
    runs = _completed_runs(
        session,
        capability_id=capability_id,
        test_version_id=test_version_id,
        include_demo=include_demo,
    )
    _, latest_attempt_by_run, _ = _latest_maps(session, runs)
    model_map, harness_map, _ = _group_identity(session, runs)
    acc: dict[tuple[str, str], dict] = {}
    for run in runs:
        key = _group_key(run, model_map, harness_map)
        entry = acc.setdefault(
            key, {"known": [], "n_unknown": 0, "run_ids_known": [], "run_ids_unknown": []}
        )
        attempt = latest_attempt_by_run.get(run.id)
        elapsed = attempt.elapsed_seconds if attempt is not None else None
        if elapsed is None:
            entry["n_unknown"] += 1
            entry["run_ids_unknown"].append(run.id)
        else:
            entry["known"].append(float(elapsed))
            entry["run_ids_known"].append(run.id)
    groups = []
    for (model_key, harness_key) in sorted(acc, key=lambda k: (k[0], k[1])):
        entry = acc[(model_key, harness_key)]
        known = sorted(entry["known"])
        n_known = len(known)
        groups.append(
            {
                "model_key": model_key,
                "harness_key": harness_key,
                "label": _group_label(model_key, harness_key),
                "n_known": n_known,
                "n_unknown": entry["n_unknown"],
                "avg_known": (sum(known) / n_known) if n_known else None,
                "min_known": known[0] if n_known else None,
                "max_known": known[-1] if n_known else None,
                "values_known": known,
                "run_ids_known": sorted(entry["run_ids_known"]),
                "run_ids_unknown": sorted(entry["run_ids_unknown"]),
            }
        )
    return {
        "type": "elapsed_by_model_harness",
        "context": {"capability_id": capability_id, "test_version_id": test_version_id},
        "groups": groups,
        "meta": {"include_demo": include_demo, "empty": not groups, "unit": "seconds"},
    }


def fetch_chart_scores_by_model_harness(
    session: Session,
    *,
    capability_id: int | None = None,
    test_version_id: int | None = None,
    include_demo: bool = False,
) -> dict:
    runs = _completed_runs(
        session,
        capability_id=capability_id,
        test_version_id=test_version_id,
        include_demo=include_demo,
    )
    latest_by_run, _, _ = _latest_maps(session, runs)
    model_map, harness_map, _ = _group_identity(session, runs)
    acc: dict[tuple[str, str], dict] = {}
    for run in runs:
        key = _group_key(run, model_map, harness_map)
        entry = acc.setdefault(
            key,
            {"scored": [], "n_unscored": 0, "run_ids_scored": [], "run_ids_unscored": []},
        )
        latest = latest_by_run.get(run.id)
        verdict = _norm(latest.verdict) if latest is not None else None
        total = latest.total_score if latest is not None else None
        if latest is None or verdict == "UNKNOWN" or total is None:
            entry["n_unscored"] += 1
            entry["run_ids_unscored"].append(run.id)
        else:
            entry["scored"].append(float(total))
            entry["run_ids_scored"].append(run.id)
    groups = []
    for (model_key, harness_key) in sorted(acc, key=lambda k: (k[0], k[1])):
        entry = acc[(model_key, harness_key)]
        scored = sorted(entry["scored"])
        n_scored = len(scored)
        groups.append(
            {
                "model_key": model_key,
                "harness_key": harness_key,
                "label": _group_label(model_key, harness_key),
                "n_scored": n_scored,
                "n_unscored_unknown": entry["n_unscored"],
                "avg_scored": (sum(scored) / n_scored) if n_scored else None,
                "min_scored": scored[0] if n_scored else None,
                "max_scored": scored[-1] if n_scored else None,
                "values_scored": scored,
                "run_ids_scored": sorted(entry["run_ids_scored"]),
                "run_ids_unscored": sorted(entry["run_ids_unscored"]),
            }
        )
    return {
        "type": "scores_by_model_harness",
        "context": {"capability_id": capability_id, "test_version_id": test_version_id},
        "groups": groups,
        "meta": {"include_demo": include_demo, "empty": not groups},
    }


def fetch_overview_charts(session: Session, *, include_demo: bool = False) -> dict:
    """Combined payload for /operator overview (no context filter)."""
    return {
        "qualification": fetch_chart_qualification_distribution(
            session, include_demo=include_demo
        ),
        "verdict": fetch_chart_verdict_by_model_harness(
            session, include_demo=include_demo
        ),
        "cost": fetch_chart_cost_by_model_harness(session, include_demo=include_demo),
        "elapsed": fetch_chart_elapsed_by_model_harness(
            session, include_demo=include_demo
        ),
        "scores": fetch_chart_scores_by_model_harness(
            session, include_demo=include_demo
        ),
        "meta": {"include_demo": include_demo},
    }


def fetch_context_charts(
    session: Session,
    *,
    capability_id: int | None = None,
    test_version_id: int | None = None,
    include_demo: bool = False,
) -> dict:
    """Filtered payload for compare/qualification context views."""
    return {
        "qualification": fetch_chart_qualification_distribution(
            session, include_demo=include_demo
        ),
        "verdict": fetch_chart_verdict_by_model_harness(
            session,
            capability_id=capability_id,
            test_version_id=test_version_id,
            include_demo=include_demo,
        ),
        "cost": fetch_chart_cost_by_model_harness(
            session,
            capability_id=capability_id,
            test_version_id=test_version_id,
            include_demo=include_demo,
        ),
        "elapsed": fetch_chart_elapsed_by_model_harness(
            session,
            capability_id=capability_id,
            test_version_id=test_version_id,
            include_demo=include_demo,
        ),
        "scores": fetch_chart_scores_by_model_harness(
            session,
            capability_id=capability_id,
            test_version_id=test_version_id,
            include_demo=include_demo,
        ),
        "meta": {
            "include_demo": include_demo,
            "capability_id": capability_id,
            "test_version_id": test_version_id,
        },
    }
