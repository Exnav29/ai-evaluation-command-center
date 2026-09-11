"""Dashboard query layer: deterministic reads over the Phase 2 evidence model.

All functions take an explicit SQLAlchemy Session and return plain
structures/models. No hard-coded demo rows: every value comes from the
database. Ordering is deterministic so overview pages and tests agree.

Conventions preserved from the evidence foundation:
- latest score revision = highest id (append-only history);
- latest qualification decision per exact harness+model+capability triple
  = highest id for that triple;
- latest/relevant attempt for overview = highest attempt_number (tie: highest id);
- missing cost/tokens (None) stay unknown; numeric 0.0/0 stays zero.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from aecc.models import (
    Attempt,
    Capability,
    ExclusionEvent,
    Harness,
    InterventionEvent,
    LogicalTest,
    Model,
    QualificationDecision,
    QualificationEvidence,
    Run,
    ScoreRevision,
    TestVersion,
)


def _ordered_runs_stmt(limit: int = 100):
    return (
        select(Run)
        .order_by(Run.requested_at.desc(), Run.id.desc())
        .limit(limit)
    )


def latest_score(scores: list[ScoreRevision]) -> ScoreRevision | None:
    """Newest score revision by append-only id; None when unscored."""
    if not scores:
        return None
    return max(scores, key=lambda s: (s.id or 0))


def latest_attempt(attempts: list[Attempt]) -> Attempt | None:
    """Relevant attempt for overview: highest attempt_number, tie highest id."""
    if not attempts:
        return None
    return max(attempts, key=lambda a: (a.attempt_number or 0, a.id or 0))


def latest_qualification(
    decisions: list[QualificationDecision],
) -> QualificationDecision | None:
    if not decisions:
        return None
    return max(decisions, key=lambda d: (d.id or 0))


def _batch_map(session: Session, model_cls, ids: set[int]) -> dict:
    if not ids:
        return {}
    rows = session.scalars(select(model_cls).where(model_cls.id.in_(sorted(ids)))).all()
    return {r.id: r for r in rows}


def fetch_runs_overview(session: Session, limit: int = 100) -> list[dict]:
    """Newest-first run rows with joined identity + latest score/attempt/qual.

    Returns one dict per run with keys: run, harness, model, capability,
    test_version, logical_test, attempts, latest_attempt, scores,
    latest_score, qual_current, qual_history, interventions, exclusions,
    has_intervention, has_permission_denial.
    Batched queries avoid N+1 access patterns.
    """
    runs: list[Run] = list(session.scalars(_ordered_runs_stmt(limit)).all())
    if not runs:
        return []
    run_ids = [r.id for r in runs]
    triples = {(r.harness_id, r.model_id, r.capability_id) for r in runs}

    harness_map = _batch_map(session, Harness, {r.harness_id for r in runs})
    model_map = _batch_map(session, Model, {r.model_id for r in runs})
    cap_map = _batch_map(session, Capability, {r.capability_id for r in runs})
    tv_map = _batch_map(session, TestVersion, {r.test_version_id for r in runs})
    logical_map: dict[int, LogicalTest] = {}
    if tv_map:
        lt_ids = {tv.logical_test_id for tv in tv_map.values()}
        logical_map = _batch_map(session, LogicalTest, lt_ids)

    attempts_by_run: dict[int, list[Attempt]] = {rid: [] for rid in run_ids}
    for a in session.scalars(
        select(Attempt)
        .where(Attempt.run_id.in_(run_ids))
        .order_by(Attempt.attempt_number.asc(), Attempt.id.asc())
    ).all():
        attempts_by_run.setdefault(a.run_id, []).append(a)

    scores_by_run: dict[int, list[ScoreRevision]] = {rid: [] for rid in run_ids}
    for s in session.scalars(
        select(ScoreRevision).where(ScoreRevision.run_id.in_(run_ids)).order_by(ScoreRevision.id.asc())
    ).all():
        scores_by_run.setdefault(s.run_id, []).append(s)

    interventions_by_run: dict[int, list[InterventionEvent]] = {rid: [] for rid in run_ids}
    for ev in session.scalars(
        select(InterventionEvent).where(InterventionEvent.run_id.in_(run_ids)).order_by(InterventionEvent.id.asc())
    ).all():
        interventions_by_run.setdefault(ev.run_id, []).append(ev)

    exclusions_by_run: dict[int, list[ExclusionEvent]] = {rid: [] for rid in run_ids}
    for ev in session.scalars(
        select(ExclusionEvent).where(ExclusionEvent.run_id.in_(run_ids)).order_by(ExclusionEvent.id.asc())
    ).all():
        exclusions_by_run.setdefault(ev.run_id, []).append(ev)

    # Qualification history for every triple represented on this page.
    quals_by_triple: dict[tuple[int, int, int], list[QualificationDecision]] = {}
    if triples:
        h_ids = {t[0] for t in triples}
        m_ids = {t[1] for t in triples}
        c_ids = {t[2] for t in triples}
        for d in session.scalars(
            select(QualificationDecision)
            .where(
                QualificationDecision.harness_id.in_(sorted(h_ids)),
                QualificationDecision.model_id.in_(sorted(m_ids)),
                QualificationDecision.capability_id.in_(sorted(c_ids)),
            )
            .order_by(QualificationDecision.id.asc())
        ).all():
            key = (d.harness_id, d.model_id, d.capability_id)
            if key in triples:
                quals_by_triple.setdefault(key, []).append(d)

    rows: list[dict] = []
    for run in runs:
        attempts = attempts_by_run.get(run.id, [])
        scores = scores_by_run.get(run.id, [])
        interventions = interventions_by_run.get(run.id, [])
        exclusions = exclusions_by_run.get(run.id, [])
        qual_history = quals_by_triple.get((run.harness_id, run.model_id, run.capability_id), [])
        tv = tv_map.get(run.test_version_id)
        rows.append(
            {
                "run": run,
                "harness": harness_map.get(run.harness_id),
                "model": model_map.get(run.model_id),
                "capability": cap_map.get(run.capability_id),
                "test_version": tv,
                "logical_test": logical_map.get(tv.logical_test_id) if tv else None,
                "attempts": attempts,
                "latest_attempt": latest_attempt(attempts),
                "scores": scores,
                "latest_score": latest_score(scores),
                "qual_current": latest_qualification(qual_history),
                "qual_history": qual_history,
                "interventions": interventions,
                "exclusions": exclusions,
                "has_intervention": bool(interventions)
                or any(bool(a.human_intervention) for a in attempts),
                "has_permission_denial": any(bool(a.permission_denied) for a in attempts),
            }
        )
    return rows


def fetch_run_detail(session: Session, run_id: int) -> dict | None:
    """Full evidence bundle for one run, or None when the run does not exist."""
    run = session.get(Run, run_id)
    if run is None:
        return None
    harness = session.get(Harness, run.harness_id)
    model = session.get(Model, run.model_id)
    capability = session.get(Capability, run.capability_id)
    tv = session.get(TestVersion, run.test_version_id)
    logical = session.get(LogicalTest, tv.logical_test_id) if tv else None

    attempts = list(
        session.scalars(
            select(Attempt)
            .where(Attempt.run_id == run.id)
            .order_by(Attempt.attempt_number.asc(), Attempt.id.asc())
        ).all()
    )
    scores = list(
        session.scalars(
            select(ScoreRevision)
            .where(ScoreRevision.run_id == run.id)
            .order_by(ScoreRevision.id.asc())
        ).all()
    )
    interventions = list(
        session.scalars(
            select(InterventionEvent)
            .where(InterventionEvent.run_id == run.id)
            .order_by(InterventionEvent.id.asc())
        ).all()
    )
    exclusions = list(
        session.scalars(
            select(ExclusionEvent)
            .where(ExclusionEvent.run_id == run.id)
            .order_by(ExclusionEvent.id.asc())
        ).all()
    )
    qual_history = list(
        session.scalars(
            select(QualificationDecision)
            .where(
                QualificationDecision.harness_id == run.harness_id,
                QualificationDecision.model_id == run.model_id,
                QualificationDecision.capability_id == run.capability_id,
            )
            .order_by(QualificationDecision.id.asc())
        ).all()
    )
    qual_ids = [d.id for d in qual_history]
    evidence_links: list[QualificationEvidence] = []
    if qual_ids:
        evidence_links = list(
            session.scalars(
                select(QualificationEvidence)
                .where(QualificationEvidence.qualification_id.in_(qual_ids))
                .order_by(QualificationEvidence.id.asc())
            ).all()
        )
    evidence_by_qual: dict[int, list[QualificationEvidence]] = {}
    for link in evidence_links:
        evidence_by_qual.setdefault(link.qualification_id, []).append(link)

    return {
        "run": run,
        "harness": harness,
        "model": model,
        "capability": capability,
        "test_version": tv,
        "logical_test": logical,
        "attempts": attempts,
        "latest_attempt": latest_attempt(attempts),
        "scores": scores,
        "latest_score": latest_score(scores),
        "interventions": interventions,
        "exclusions": exclusions,
        "qual_history": qual_history,
        "qual_current": latest_qualification(qual_history),
        "evidence_by_qual": evidence_by_qual,
        "has_intervention": bool(interventions)
        or any(bool(a.human_intervention) for a in attempts),
        "has_permission_denial": any(bool(a.permission_denied) for a in attempts),
    }


def fetch_qualifications(session: Session, *, include_demo: bool = False) -> list[dict]:
    """One row per harness+model+capability triple with qualification history.

    Current state is the newest decision for the exact triple. History is
    preserved in chronological order with evidence links.
    By default demo decisions are excluded.
    """
    if include_demo:
        decisions = list(
            session.scalars(select(QualificationDecision).order_by(QualificationDecision.id.asc())).all()
        )
    else:
        decisions = list(
            session.scalars(select(QualificationDecision).where(QualificationDecision.is_demo == False).order_by(QualificationDecision.id.asc())).all()  # noqa: E712
        )
    if not decisions:
        return []
    by_triple: dict[tuple[int, int, int], list[QualificationDecision]] = {}
    for d in decisions:
        by_triple.setdefault((d.harness_id, d.model_id, d.capability_id), []).append(d)

    harness_map = _batch_map(session, Harness, {t[0] for t in by_triple})
    model_map = _batch_map(session, Model, {t[1] for t in by_triple})
    cap_map = _batch_map(session, Capability, {t[2] for t in by_triple})

    qual_ids = [d.id for d in decisions]
    evidence_by_qual: dict[int, list[QualificationEvidence]] = {}
    for link in session.scalars(
        select(QualificationEvidence)
        .where(QualificationEvidence.qualification_id.in_(qual_ids))
        .order_by(QualificationEvidence.id.asc())
    ).all():
        evidence_by_qual.setdefault(link.qualification_id, []).append(link)

    rows: list[dict] = []
    for triple in sorted(by_triple, key=lambda t: (t[0], t[1], t[2])):
        history = by_triple[triple]
        rows.append(
            {
                "harness": harness_map.get(triple[0]),
                "model": model_map.get(triple[1]),
                "capability": cap_map.get(triple[2]),
                "current": latest_qualification(history),
                "history": history,
                "evidence_by_qual": {
                    d.id: evidence_by_qual.get(d.id, []) for d in history
                },
            }
        )
    return rows


NON_PASS_REVIEW_VERDICTS = frozenset(
    {"FAIL", "NEEDS_REVIEW", "INFRASTRUCTURE_FAILURE", "EXCLUDED"}
)

# Run states that represent completed evaluation evidence (as opposed to
# queued/running/cancel-requested work). Comparison and computed
# qualification read only these states; queued or in-flight runs are never
# treated as evidence. In-flight states that must never count: QUEUED,
# CLAIMED, RUNNING, SCORING, CANCEL_REQUESTED, CANCELLED.
COMPLETED_EVIDENCE_STATES = frozenset(
    {
        "COMPLETED",
        "FINALIZED",
        "NEEDS_REVIEW",
        "INFRASTRUCTURE_FAILURE",
        "EXCLUDED",
    }
)


def fetch_summary(session: Session, *, include_demo: bool = False) -> dict:
    """Overview summary cards derived from persisted evidence (no hard-coding).

    By default demo rows (is_demo=True) are excluded from qualification counts
    and treated as labeled but not real evidence. Pass include_demo=True for
    debugging/demo-inclusive aggregates.
    """
    from sqlalchemy import func as _func

    if include_demo:
        total_runs = int(session.scalar(select(_func.count(Run.id))) or 0)
        run_ids: list[int] = list(session.scalars(select(Run.id)).all())
    else:
        total_runs = int(session.scalar(select(_func.count(Run.id)).where(Run.is_demo == False)) or 0)  # noqa: E712
        run_ids: list[int] = list(session.scalars(select(Run.id).where(Run.is_demo == False)).all())  # noqa: E712
    needs_review_or_failing = 0
    unknown_or_unscored = 0
    if run_ids:
        scores = list(
            session.scalars(
                select(ScoreRevision).where(ScoreRevision.run_id.in_(run_ids)).order_by(ScoreRevision.id.asc())
            ).all()
        )
        latest_by_run: dict[int, ScoreRevision] = {}
        for s in scores:
            latest_by_run[s.run_id] = s  # ascending order: last wins
        needs_review_states = list(
            session.scalars(select(Run.id).where(Run.state == "NEEDS_REVIEW")).all()
        )
        needs_review_run_ids = set(needs_review_states)
        for rid in run_ids:
            latest = latest_by_run.get(rid)
            if latest is None or (latest.verdict is not None and latest.verdict.value == "UNKNOWN"):
                unknown_or_unscored += 1
            if rid in needs_review_run_ids or (
                latest is not None
                and latest.verdict is not None
                and latest.verdict.value in NON_PASS_REVIEW_VERDICTS
            ):
                needs_review_or_failing += 1

    if include_demo:
        decisions = list(session.scalars(select(QualificationDecision)).all())
    else:
        decisions = list(session.scalars(select(QualificationDecision).where(QualificationDecision.is_demo == False)).all())  # noqa: E712
    latest_by_triple: dict[tuple[int, int, int], QualificationDecision] = {}
    for d in decisions:
        key = (d.harness_id, d.model_id, d.capability_id)
        prev = latest_by_triple.get(key)
        if prev is None or (d.id or 0) > (prev.id or 0):
            latest_by_triple[key] = d
    qualified_triples = sum(
        1 for d in latest_by_triple.values() if d.state is not None and d.state.value == "QUALIFIED"
    )

    return {
        "total_runs": total_runs,
        "needs_review_or_failing": needs_review_or_failing,
        "qualified_triples": qualified_triples,
        "unknown_or_unscored": unknown_or_unscored,
    }


def _run_evidences_for_runs(
    session: Session,
    runs: list[Run],
    *,
    latest_by_run: dict[int, ScoreRevision],
    attempts_by_run: dict[int, list[Attempt]],
    interventions_by_run: dict[int, list[InterventionEvent]],
    exclusions_by_run: dict[int, list[ExclusionEvent]],
) -> dict[int, "RunEvidence"]:
    """Build deterministic RunEvidence per run for computed qualification.

    Latest verdict comes from the append-only score history (highest id wins
    via latest_by_run); failure/intervention/permission signals come from the
    latest attempt plus any recorded events. Deferred import keeps this module
    importable without qualification at load time.
    """
    from aecc.qualification import RunEvidence

    out: dict[int, RunEvidence] = {}
    for run in runs:
        latest = latest_by_run.get(run.id)
        attempts = attempts_by_run.get(run.id, [])
        latest_a = latest_attempt(attempts)
        verdict = latest.verdict.value if latest is not None and latest.verdict is not None else None
        out[run.id] = RunEvidence(
            run_id=run.id,
            verdict=verdict,
            run_state=run.state.value if run.state is not None else None,
            failure_primary=(
                latest_a.failure_primary.value
                if latest_a is not None and latest_a.failure_primary is not None
                else None
            ),
            has_intervention=bool(interventions_by_run.get(run.id))
            or any(bool(a.human_intervention) for a in attempts),
            has_permission_denial=any(bool(a.permission_denied) for a in attempts),
            has_exclusion=bool(exclusions_by_run.get(run.id)),
            is_demo=bool(run.is_demo),
        )
    return out


def fetch_computed_qualifications(
    session: Session, *, include_demo: bool = False
) -> list[dict]:
    """Deterministic computed qualification per harness+model+capability+test group.

    Reads completed evaluation evidence only; queued/running runs never count.
    Demo runs are excluded from real qualification unless include_demo=True.
    Groups preserve the same capability/test context: runs sharing
    harness+model+capability but different test versions (different logical
    tests or materially different definitions) are never silently blended
    into one qualification; each exact test version gets its own assessment.
    Each row carries: harness, model, capability, test_version, logical_test,
    assessment (ComputedAssessment with state/label/reasons/counts/classified),
    run_rows (per-run evidence with latest verdict for drill-down, each
    carrying its own deterministic ``classification`` so the template never
    correlates separate collections by position). Rows sort
    by (harness_key, model_key, capability_key, version, logical_key,
    version_number) for determinism.
    """
    from aecc.qualification import assess_triple, classify_run

    runs: list[Run] = list(
        session.scalars(
            select(Run).order_by(Run.id.asc())
        ).all()
    )
    if not runs:
        return []
    run_ids = [r.id for r in runs]

    attempts_by_run: dict[int, list[Attempt]] = {rid: [] for rid in run_ids}
    for a in session.scalars(
        select(Attempt)
        .where(Attempt.run_id.in_(run_ids))
        .order_by(Attempt.attempt_number.asc(), Attempt.id.asc())
    ).all():
        attempts_by_run.setdefault(a.run_id, []).append(a)

    latest_by_run: dict[int, ScoreRevision] = {}
    for s in session.scalars(
        select(ScoreRevision).where(ScoreRevision.run_id.in_(run_ids)).order_by(ScoreRevision.id.asc())
    ).all():
        latest_by_run[s.run_id] = s  # ascending: last wins

    interventions_by_run: dict[int, list[InterventionEvent]] = {rid: [] for rid in run_ids}
    for ev in session.scalars(
        select(InterventionEvent).where(InterventionEvent.run_id.in_(run_ids)).order_by(InterventionEvent.id.asc())
    ).all():
        interventions_by_run.setdefault(ev.run_id, []).append(ev)

    exclusions_by_run: dict[int, list[ExclusionEvent]] = {rid: [] for rid in run_ids}
    for ev in session.scalars(
        select(ExclusionEvent).where(ExclusionEvent.run_id.in_(run_ids)).order_by(ExclusionEvent.id.asc())
    ).all():
        exclusions_by_run.setdefault(ev.run_id, []).append(ev)

    completed = [r for r in runs if (r.state is not None and r.state.value in COMPLETED_EVIDENCE_STATES)]
    if not completed:
        return []

    evidences = _run_evidences_for_runs(
        session,
        completed,
        latest_by_run=latest_by_run,
        attempts_by_run=attempts_by_run,
        interventions_by_run=interventions_by_run,
        exclusions_by_run=exclusions_by_run,
    )

    # Preserve same capability/test context: group by exact test version so
    # different logical tests or materially different definitions never blend.
    by_group: dict[tuple[int, int, int, int], list[Run]] = {}
    for r in completed:
        by_group.setdefault((r.harness_id, r.model_id, r.capability_id, r.test_version_id), []).append(r)

    harness_map = _batch_map(session, Harness, {t[0] for t in by_group})
    model_map = _batch_map(session, Model, {t[1] for t in by_group})
    cap_map = _batch_map(session, Capability, {t[2] for t in by_group})
    tv_map = _batch_map(session, TestVersion, {t[3] for t in by_group})
    logical_map: dict[int, LogicalTest] = {}
    if tv_map:
        logical_map = _batch_map(session, LogicalTest, {tv.logical_test_id for tv in tv_map.values()})

    rows: list[dict] = []
    for group, group_runs in by_group.items():
        group_runs_sorted = sorted(group_runs, key=lambda r: r.id)
        assessment = assess_triple(
            [evidences[r.id] for r in group_runs_sorted],
            include_demo=include_demo,
        )
        run_rows = [
            {
                "run": r,
                "latest_score": latest_by_run.get(r.id),
                "latest_attempt": latest_attempt(attempts_by_run.get(r.id, [])),
                "evidence": evidences[r.id],
                "classification": classify_run(evidences[r.id]),
            }
            for r in group_runs_sorted
        ]
        tv = tv_map.get(group[3])
        rows.append(
            {
                "triple": group[:3],
                "group": group,
                "harness": harness_map.get(group[0]),
                "model": model_map.get(group[1]),
                "capability": cap_map.get(group[2]),
                "test_version": tv,
                "logical_test": logical_map.get(tv.logical_test_id) if tv is not None else None,
                "assessment": assessment,
                "run_rows": run_rows,
            }
        )

    def _sort_key(row: dict) -> tuple:
        h = row["harness"]
        m = row["model"]
        c = row["capability"]
        tv = row.get("test_version")
        lt = row.get("logical_test")
        return (
            h.harness_key if h is not None else "",
            m.model_key if m is not None else "",
            c.capability_key if c is not None else "",
            c.version if c is not None and c.version else "",
            lt.key if lt is not None else "",
            tv.version_number if tv is not None else 0,
        )

    rows.sort(key=_sort_key)
    return rows


def fetch_compare_contexts(session: Session) -> dict:
    """Selector data for the comparison page: capabilities and test versions.

    Returns dict with 'capabilities' (ordered by key/version) and 'versions'
    (ordered by logical key/version number) plus lookup maps. Derived from
    persisted evidence only.
    """
    caps = list(
        session.scalars(
            select(Capability).order_by(Capability.capability_key, Capability.version)
        ).all()
    )
    versions = list(
        session.scalars(
            select(TestVersion).order_by(TestVersion.logical_test_id, TestVersion.version_number)
        ).all()
    )
    logical_map: dict[int, LogicalTest] = {}
    if versions:
        lt_ids = {v.logical_test_id for v in versions}
        logical_map = _batch_map(session, LogicalTest, lt_ids)
    return {"capabilities": caps, "versions": versions, "logical_map": logical_map}


def fetch_compare_rows(
    session: Session,
    *,
    capability_id: int | None = None,
    test_version_id: int | None = None,
    limit: int = 200,
) -> list[dict]:
    """Completed-evaluation rows for side-by-side model+harness comparison.

    Filters to a single capability/test context (both optional; when neither
    is given the newest completed runs are returned). Only completed evidence
    states are included; queued/running work never appears. Newest-first
    deterministic order. Row shape matches fetch_runs_overview rows so the
    same evidence semantics (latest score/attempt, UNKNOWN handling) apply.
    """
    stmt = select(Run).where(Run.state.in_(sorted(COMPLETED_EVIDENCE_STATES)))
    if capability_id is not None:
        stmt = stmt.where(Run.capability_id == capability_id)
    if test_version_id is not None:
        stmt = stmt.where(Run.test_version_id == test_version_id)
    stmt = stmt.order_by(Run.requested_at.desc(), Run.id.desc()).limit(limit)
    runs: list[Run] = list(session.scalars(stmt).all())
    if not runs:
        return []
    run_ids = [r.id for r in runs]
    triples = {(r.harness_id, r.model_id, r.capability_id) for r in runs}

    harness_map = _batch_map(session, Harness, {r.harness_id for r in runs})
    model_map = _batch_map(session, Model, {r.model_id for r in runs})
    cap_map = _batch_map(session, Capability, {r.capability_id for r in runs})
    tv_map = _batch_map(session, TestVersion, {r.test_version_id for r in runs})
    logical_map: dict[int, LogicalTest] = {}
    if tv_map:
        lt_ids = {tv.logical_test_id for tv in tv_map.values()}
        logical_map = _batch_map(session, LogicalTest, lt_ids)

    attempts_by_run: dict[int, list[Attempt]] = {rid: [] for rid in run_ids}
    for a in session.scalars(
        select(Attempt)
        .where(Attempt.run_id.in_(run_ids))
        .order_by(Attempt.attempt_number.asc(), Attempt.id.asc())
    ).all():
        attempts_by_run.setdefault(a.run_id, []).append(a)

    scores_by_run: dict[int, list[ScoreRevision]] = {rid: [] for rid in run_ids}
    for s in session.scalars(
        select(ScoreRevision).where(ScoreRevision.run_id.in_(run_ids)).order_by(ScoreRevision.id.asc())
    ).all():
        scores_by_run.setdefault(s.run_id, []).append(s)

    interventions_by_run: dict[int, list[InterventionEvent]] = {rid: [] for rid in run_ids}
    for ev in session.scalars(
        select(InterventionEvent).where(InterventionEvent.run_id.in_(run_ids)).order_by(InterventionEvent.id.asc())
    ).all():
        interventions_by_run.setdefault(ev.run_id, []).append(ev)

    exclusions_by_run: dict[int, list[ExclusionEvent]] = {rid: [] for rid in run_ids}
    for ev in session.scalars(
        select(ExclusionEvent).where(ExclusionEvent.run_id.in_(run_ids)).order_by(ExclusionEvent.id.asc())
    ).all():
        exclusions_by_run.setdefault(ev.run_id, []).append(ev)

    quals_by_triple: dict[tuple[int, int, int], list[QualificationDecision]] = {}
    if triples:
        h_ids = {t[0] for t in triples}
        m_ids = {t[1] for t in triples}
        c_ids = {t[2] for t in triples}
        for d in session.scalars(
            select(QualificationDecision)
            .where(
                QualificationDecision.harness_id.in_(sorted(h_ids)),
                QualificationDecision.model_id.in_(sorted(m_ids)),
                QualificationDecision.capability_id.in_(sorted(c_ids)),
            )
            .order_by(QualificationDecision.id.asc())
        ).all():
            key = (d.harness_id, d.model_id, d.capability_id)
            if key in triples:
                quals_by_triple.setdefault(key, []).append(d)

    latest_by_run: dict[int, ScoreRevision] = {}
    for rid, scores in scores_by_run.items():
        latest = latest_score(scores)
        if latest is not None:
            latest_by_run[rid] = latest
    evidences = _run_evidences_for_runs(
        session,
        runs,
        latest_by_run=latest_by_run,
        attempts_by_run=attempts_by_run,
        interventions_by_run=interventions_by_run,
        exclusions_by_run=exclusions_by_run,
    )

    from aecc.qualification import classify_run

    rows: list[dict] = []
    for run in runs:
        attempts = attempts_by_run.get(run.id, [])
        scores = scores_by_run.get(run.id, [])
        interventions = interventions_by_run.get(run.id, [])
        exclusions = exclusions_by_run.get(run.id, [])
        qual_history = quals_by_triple.get((run.harness_id, run.model_id, run.capability_id), [])
        tv = tv_map.get(run.test_version_id)
        rows.append(
            {
                "run": run,
                "harness": harness_map.get(run.harness_id),
                "model": model_map.get(run.model_id),
                "capability": cap_map.get(run.capability_id),
                "test_version": tv,
                "logical_test": logical_map.get(tv.logical_test_id) if tv else None,
                "attempts": attempts,
                "latest_attempt": latest_attempt(attempts),
                "scores": scores,
                "latest_score": latest_score(scores),
                "qual_current": latest_qualification(qual_history),
                "qual_history": qual_history,
                "interventions": interventions,
                "exclusions": exclusions,
                "has_intervention": bool(interventions)
                or any(bool(a.human_intervention) for a in attempts),
                "has_permission_denial": any(bool(a.permission_denied) for a in attempts),
                "evidence_category": classify_run(evidences[run.id]).category,
                "evidence": evidences[run.id],
            }
        )
    return rows
