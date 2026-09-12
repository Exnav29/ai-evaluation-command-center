"""V2 Phase 1: work-area guidance + Home summaries.

Five operator-facing work areas group technical capability keys into
plain language ("Type of Work"). Mapping is deterministic, prefix-based,
and conservative: a capability maps to at most one work area, and unknown
or legacy keys map to None (rendered as "We don't know yet" territory via
unmapped counts, never as a winner).

Evidence rules preserved:
- Only completed evidence states count (see dashboard_queries.
  COMPLETED_EVIDENCE_STATES); queued/running work never counts.
- Demo rows (is_demo=True) are excluded from real summaries.
- UNKNOWN/unscored verdicts are never counted as passes.
- Missing values stay missing; no zero-fill, no composite ranking score.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from aecc.dashboard_queries import COMPLETED_EVIDENCE_STATES
from aecc.models import Attempt, Capability, Run, ScoreRevision

WORK_AREAS: list[dict] = [
    {
        "slug": "backend",
        "title": "Backend Development",
        "blurb": "APIs, services, data handling, and bug fixes behind the interface.",
        "prefixes": ("backend",),
    },
    {
        "slug": "frontend",
        "title": "Frontend Development",
        "blurb": "Interfaces, interactions, and client-side behavior users touch.",
        "prefixes": ("frontend",),
    },
    {
        "slug": "visual-design",
        "title": "Visual Design",
        "blurb": "Layout, styling, and visual quality of what gets built.",
        "prefixes": ("visual", "design"),
    },
    {
        "slug": "reasoning",
        "title": "Reasoning",
        "blurb": "Multi-step problem solving and working through complex tasks.",
        "prefixes": ("reasoning",),
    },
    {
        "slug": "instruction",
        "title": "Instruction Following",
        "blurb": "Doing what was asked, precisely and completely.",
        "prefixes": ("instruction", "instruction-following", "following"),
    },
]

PASS_VERDICTS = frozenset({"PASS", "PASS_WITH_FINDINGS"})


def map_capability_to_work_area(capability_key: str | None) -> str | None:
    """Map a technical capability key to a work-area slug, or None.

    Deterministic and conservative: match on the lowercased first
    dot-separated segment, or a full-key prefix with separator ('.', '_',
    '-'). Legacy keys such as 'bug-fixing' or 'refactoring' intentionally
    map to None so Home never claims they prove a work area.
    """
    if not capability_key:
        return None
    key = capability_key.strip().lower()
    if not key:
        return None
    first = key.split(".")[0]
    for area in WORK_AREAS:
        for prefix in area["prefixes"]:
            p = prefix.lower()
            if first == p or first.startswith(p + "_") or first.startswith(p + "-"):
                return area["slug"]
            if key == p or key.startswith(p + ".") or key.startswith(p + "_") or key.startswith(p + "-"):
                return area["slug"]
    return None


def fetch_home_work_area_summaries(session: Session) -> dict:
    """Summaries per work area for V2 Home. No winner, no composite score.

    Returns dict with 'areas' (one entry per WORK_AREAS in order) and
    'overall' (totals). Each area entry carries:
      slug, title, blurb, total_runs, evaluated_runs, pass_runs,
      models_tested, models_with_pass, status ('unknown' | 'has_evidence'),
      unmapped_note is on overall only.

    Counting rules:
    - completed evidence states only; demo excluded;
    - evaluated = runs with a latest non-UNKNOWN verdict;
    - pass = evaluated runs with PASS / PASS_WITH_FINDINGS;
    - missing verdicts stay UNKNOWN and never count as pass.
    """
    caps = list(session.scalars(select(Capability)).all())
    cap_key_by_id = {c.id: (c.capability_key or "") for c in caps}

    runs: list[Run] = list(session.scalars(select(Run)).all())
    real_completed = [
        r
        for r in runs
        if not r.is_demo
        and r.state is not None
        and r.state.value in COMPLETED_EVIDENCE_STATES
    ]

    # Latest score per run (append-only: highest id wins).
    run_ids = [r.id for r in real_completed]
    latest_by_run: dict[int, ScoreRevision] = {}
    if run_ids:
        for s in session.scalars(
            select(ScoreRevision)
            .where(ScoreRevision.run_id.in_(run_ids))
            .order_by(ScoreRevision.id.asc())
        ).all():
            latest_by_run[s.run_id] = s

    # Per-area aggregation (no cross-area blending of verdicts).
    by_area: dict[str, list[Run]] = {a["slug"]: [] for a in WORK_AREAS}
    unmapped = 0
    for r in real_completed:
        slug = map_capability_to_work_area(cap_key_by_id.get(r.capability_id, ""))
        if slug is None:
            unmapped += 1
        else:
            by_area[slug].append(r)

    areas = []
    for area in WORK_AREAS:
        grouped = by_area[area["slug"]]
        evaluated = 0
        passes = 0
        model_ids: set[int] = set()
        pass_model_ids: set[int] = set()
        for r in grouped:
            model_ids.add(r.model_id)
            latest = latest_by_run.get(r.id)
            verdict = latest.verdict.value if latest is not None and latest.verdict is not None else None
            if verdict is None or verdict == "UNKNOWN":
                continue
            evaluated += 1
            if verdict in PASS_VERDICTS:
                passes += 1
                pass_model_ids.add(r.model_id)
        status = "has_evidence" if passes > 0 else "unknown"
        areas.append(
            {
                "slug": area["slug"],
                "title": area["title"],
                "blurb": area["blurb"],
                "total_runs": len(grouped),
                "evaluated_runs": evaluated,
                "pass_runs": passes,
                "models_tested": len(model_ids),
                "models_with_pass": len(pass_model_ids),
                "status": status,
            }
        )

    # Overall real-evidence totals (completed, non-demo).
    evaluated_total = 0
    pass_total = 0
    for r in real_completed:
        latest = latest_by_run.get(r.id)
        verdict = latest.verdict.value if latest is not None and latest.verdict is not None else None
        if verdict is None or verdict == "UNKNOWN":
            continue
        evaluated_total += 1
        if verdict in PASS_VERDICTS:
            pass_total += 1

    return {
        "areas": areas,
        "overall": {
            "total_runs": len(real_completed),
            "evaluated_runs": evaluated_total,
            "pass_runs": pass_total,
            "models_tested": len({r.model_id for r in real_completed}),
            "unmapped_runs": unmapped,
        },
    }
