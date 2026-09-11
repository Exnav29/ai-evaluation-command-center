"""Deterministic computed qualification for the Comparison / Qualification milestone.

This module derives one of six qualification states for an exact
harness + model + capability triple from preserved run evidence. It is a
pure function over evidence: no LLM, no network, no randomness, no wall-clock
reads. The same evidence always yields the same state and the same reasons.

Computed states (display labels use em dashes):

- Qualified — Autonomous
- Qualified — Review Required
- Qualified — Escalate on Conditions
- Provisionally Qualified
- Insufficient Evidence
- Not Qualified

Relationship to stored qualification decisions (``QualificationDecision``):
stored decisions are append-only operator judgments and remain the auditable
history shown on ``/operator/qualifications``. This module does not write to
that table and never mutates evidence. It reads completed run evidence
(latest evaluator verdict per run, failure classification, intervention and
exclusion signals) and explains its result through an explicit reasons list
so the operator can see why a state was assigned and drill into the runs.

Evidence-integrity rules preserved here:

- UNKNOWN (missing score or UNKNOWN verdict) is never counted as PASS.
- Infrastructure failure (run state, INFRASTRUCTURE_FAILURE verdict, or an
  INFRASTRUCTURE_FAILURE primary failure classification) is distinguished
  from model/task failure and never causes Not Qualified on its own. Infra
  runs are excluded from the model/task assessment denominator and reported
  separately.
- Excluded runs (exclusion event or EXCLUDED verdict) remain inspectable but
  are excluded from the assessment denominator and reported separately.
- Demo rows (is_demo=True) are excluded from real qualification unless the
  caller explicitly opts in with include_demo=True, and any such exclusion
  is disclosed in the reasons.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class ComputedQualificationState(str, enum.Enum):
    """Deterministic qualification states for the comparison milestone."""

    QUALIFIED_AUTONOMOUS = "QUALIFIED_AUTONOMOUS"
    QUALIFIED_REVIEW_REQUIRED = "QUALIFIED_REVIEW_REQUIRED"
    QUALIFIED_ESCALATE_ON_CONDITIONS = "QUALIFIED_ESCALATE_ON_CONDITIONS"
    PROVISIONALLY_QUALIFIED = "PROVISIONALLY_QUALIFIED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    NOT_QUALIFIED = "NOT_QUALIFIED"

    @property
    def label(self) -> str:
        return {
            "QUALIFIED_AUTONOMOUS": "Qualified \u2014 Autonomous",
            "QUALIFIED_REVIEW_REQUIRED": "Qualified \u2014 Review Required",
            "QUALIFIED_ESCALATE_ON_CONDITIONS": "Qualified \u2014 Escalate on Conditions",
            "PROVISIONALLY_QUALIFIED": "Provisionally Qualified",
            "INSUFFICIENT_EVIDENCE": "Insufficient Evidence",
            "NOT_QUALIFIED": "Not Qualified",
        }[self.value]


# Run-level evidence categories. Priority order in classify_run is:
# excluded > infrastructure > unknown > pass/findings/review/fail.
RUN_CATEGORY_EXCLUDED = "excluded"
RUN_CATEGORY_INFRASTRUCTURE = "infrastructure"
RUN_CATEGORY_UNKNOWN = "unknown"
RUN_CATEGORY_PASS = "pass"
RUN_CATEGORY_PASS_WITH_FINDINGS = "pass_with_findings"
RUN_CATEGORY_NEEDS_REVIEW = "needs_review"
RUN_CATEGORY_FAIL = "fail"


@dataclass(frozen=True)
class RunEvidence:
    """Minimal per-run facts the assessment needs. All fields are plain data.

    verdict: latest EvaluatorVerdict value (e.g. "PASS") or None when unscored.
    run_state: RunState value (e.g. "FINALIZED") or None.
    failure_primary: latest-attempt FailureClassification value or None.
    """

    run_id: int
    verdict: str | None
    run_state: str | None = None
    failure_primary: str | None = None
    has_intervention: bool = False
    has_permission_denial: bool = False
    has_exclusion: bool = False
    is_demo: bool = False


@dataclass(frozen=True)
class ClassifiedRun:
    run_id: int
    category: str
    detail: str


@dataclass(frozen=True)
class ComputedAssessment:
    state: ComputedQualificationState
    reasons: tuple[str, ...] = field(default_factory=tuple)
    counts: dict[str, int] = field(default_factory=dict)
    classified: tuple[ClassifiedRun, ...] = field(default_factory=tuple)

    @property
    def label(self) -> str:
        return self.state.label


def _norm(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return value.value  # type: ignore[union-attr] (accepts enum members too)
    except AttributeError:
        text = str(value).strip()
        return text.upper() if text else None


def classify_run(evidence: RunEvidence) -> ClassifiedRun:
    """Classify one run deterministically. Pure function of the evidence."""
    verdict = _norm(evidence.verdict)
    run_state = _norm(evidence.run_state)
    failure_primary = _norm(evidence.failure_primary)

    if evidence.has_exclusion or verdict == "EXCLUDED":
        return ClassifiedRun(
            run_id=evidence.run_id,
            category=RUN_CATEGORY_EXCLUDED,
            detail=(
                f"run #{evidence.run_id} excluded from model/task assessment "
                f"(verdict={verdict or 'none'}, exclusion event recorded); "
                f"evidence remains inspectable"
            ),
        )
    if (
        run_state == "INFRASTRUCTURE_FAILURE"
        or verdict == "INFRASTRUCTURE_FAILURE"
        or failure_primary == "INFRASTRUCTURE_FAILURE"
    ):
        return ClassifiedRun(
            run_id=evidence.run_id,
            category=RUN_CATEGORY_INFRASTRUCTURE,
            detail=(
                f"run #{evidence.run_id} is an infrastructure failure "
                f"(run_state={run_state or 'none'}, verdict={verdict or 'none'}, "
                f"failure_primary={failure_primary or 'none'}); "
                f"not a model/task failure and excluded from the assessment denominator"
            ),
        )
    if verdict is None or verdict == "UNKNOWN":
        return ClassifiedRun(
            run_id=evidence.run_id,
            category=RUN_CATEGORY_UNKNOWN,
            detail=(
                f"run #{evidence.run_id} is UNKNOWN/unscored "
                f"(verdict={verdict or 'none'}); UNKNOWN is never counted as pass"
            ),
        )
    if verdict == "PASS":
        return ClassifiedRun(
            run_id=evidence.run_id,
            category=RUN_CATEGORY_PASS,
            detail=f"run #{evidence.run_id} verdict PASS",
        )
    if verdict == "PASS_WITH_FINDINGS":
        return ClassifiedRun(
            run_id=evidence.run_id,
            category=RUN_CATEGORY_PASS_WITH_FINDINGS,
            detail=f"run #{evidence.run_id} verdict PASS_WITH_FINDINGS (passes with noted findings)",
        )
    if verdict == "NEEDS_REVIEW":
        return ClassifiedRun(
            run_id=evidence.run_id,
            category=RUN_CATEGORY_NEEDS_REVIEW,
            detail=f"run #{evidence.run_id} verdict NEEDS_REVIEW (unresolved review item)",
        )
    if verdict == "FAIL":
        return ClassifiedRun(
            run_id=evidence.run_id,
            category=RUN_CATEGORY_FAIL,
            detail=(
                f"run #{evidence.run_id} verdict FAIL "
                f"(failure_primary={failure_primary or 'none'}); model/task failure evidence"
            ),
        )
    # Any future/unknown verdict value is treated as unknown, never as pass.
    return ClassifiedRun(
        run_id=evidence.run_id,
        category=RUN_CATEGORY_UNKNOWN,
        detail=(
            f"run #{evidence.run_id} carries an unrecognized verdict "
            f"({verdict}); treated as UNKNOWN, never as pass"
        ),
    )


def assess_triple(
    evidences: list[RunEvidence],
    *,
    include_demo: bool = False,
) -> ComputedAssessment:
    """Assess one harness + model + capability triple deterministically.

    Decision tree (evaluated in order; evaluated runs are pass, findings,
    needs-review, and fail after infra/excluded/unknown/demo are set aside):

    1. zero evaluated runs -> Insufficient Evidence
    2. any FAIL -> Not Qualified
    3. passes absent (only NEEDS_REVIEW) -> Not Qualified (no passing evidence)
    4. any NEEDS_REVIEW alongside passes -> Qualified — Escalate on Conditions
    5. >=2 evaluated, no flags -> Qualified — Autonomous
    6. >=2 evaluated, with flags -> Qualified — Review Required
    7. exactly 1 evaluated pass -> Provisionally Qualified

    Flags are PASS_WITH_FINDINGS verdicts, human intervention, or permission
    denial within the evaluated runs. Reasons always list the full breakdown
    so the operator can verify the assignment.
    """
    ordered = sorted(evidences, key=lambda e: e.run_id)
    demo_set_aside: list[int] = []
    if not include_demo:
        demo_set_aside = [e.run_id for e in ordered if e.is_demo]
        ordered = [e for e in ordered if not e.is_demo]

    classified = tuple(classify_run(e) for e in ordered)

    by_category: dict[str, list[int]] = {
        RUN_CATEGORY_EXCLUDED: [],
        RUN_CATEGORY_INFRASTRUCTURE: [],
        RUN_CATEGORY_UNKNOWN: [],
        RUN_CATEGORY_PASS: [],
        RUN_CATEGORY_PASS_WITH_FINDINGS: [],
        RUN_CATEGORY_NEEDS_REVIEW: [],
        RUN_CATEGORY_FAIL: [],
    }
    for c in classified:
        by_category[c.category].append(c.run_id)

    n_pass = len(by_category[RUN_CATEGORY_PASS])
    n_findings = len(by_category[RUN_CATEGORY_PASS_WITH_FINDINGS])
    n_review = len(by_category[RUN_CATEGORY_NEEDS_REVIEW])
    n_fail = len(by_category[RUN_CATEGORY_FAIL])
    n_evaluated = n_pass + n_findings + n_review + n_fail

    # Flags are computed over evaluated runs only: infra/unknown/excluded runs
    # never impose review conditions on model/task evidence.
    evaluated_ids = set(
        by_category[RUN_CATEGORY_PASS]
        + by_category[RUN_CATEGORY_PASS_WITH_FINDINGS]
        + by_category[RUN_CATEGORY_NEEDS_REVIEW]
        + by_category[RUN_CATEGORY_FAIL]
    )
    by_id = {e.run_id: e for e in ordered}
    intervention_ids = sorted(
        rid for rid in evaluated_ids if by_id[rid].has_intervention
    )
    permission_ids = sorted(
        rid for rid in evaluated_ids if by_id[rid].has_permission_denial
    )
    has_flags = bool(n_findings or intervention_ids or permission_ids)

    counts = {
        "evaluated": n_evaluated,
        "pass": n_pass,
        "pass_with_findings": n_findings,
        "needs_review": n_review,
        "fail": n_fail,
        "unknown": len(by_category[RUN_CATEGORY_UNKNOWN]),
        "infrastructure": len(by_category[RUN_CATEGORY_INFRASTRUCTURE]),
        "excluded": len(by_category[RUN_CATEGORY_EXCLUDED]),
        "demo_set_aside": len(demo_set_aside),
        "total": len(evidences),
    }

    summary = (
        f"{n_evaluated} evaluated run(s): {n_pass} pass, "
        f"{n_findings} pass with findings, {n_fail} fail, "
        f"{n_review} needs-review."
    )
    set_aside = (
        f"Set aside (not model/task evidence): "
        f"{counts['infrastructure']} infrastructure failure(s)"
        + (
            f" ({', '.join(f'run #{i}' for i in sorted(by_category[RUN_CATEGORY_INFRASTRUCTURE]))})"
            if by_category[RUN_CATEGORY_INFRASTRUCTURE]
            else ""
        )
        + f", {counts['unknown']} unknown/unscored"
        + (
            f" ({', '.join(f'run #{i}' for i in sorted(by_category[RUN_CATEGORY_UNKNOWN]))})"
            if by_category[RUN_CATEGORY_UNKNOWN]
            else ""
        )
        + f", {counts['excluded']} excluded"
        + (
            f" ({', '.join(f'run #{i}' for i in sorted(by_category[RUN_CATEGORY_EXCLUDED]))})"
            if by_category[RUN_CATEGORY_EXCLUDED]
            else ""
        )
        + "."
    )
    unknown_rule = "UNKNOWN verdicts are never counted as pass."
    infra_rule = (
        "Infrastructure failures are distinguished from model/task failures "
        "and never cause Not Qualified on their own."
    )

    reasons: list[str] = [summary, set_aside]
    if demo_set_aside and not include_demo:
        reasons.append(
            f"{len(demo_set_aside)} demo run(s) labeled and excluded from real "
            f"qualification ({', '.join(f'run #{i}' for i in sorted(demo_set_aside))})."
        )

    if n_evaluated == 0:
        reasons.append(
            "No scored model/task evidence for this triple; "
            "qualification cannot be earned from infrastructure, unknown, "
            "excluded, or demo runs alone."
        )
        reasons.extend([unknown_rule, infra_rule])
        return ComputedAssessment(
            state=ComputedQualificationState.INSUFFICIENT_EVIDENCE,
            reasons=tuple(reasons),
            counts=counts,
            classified=classified,
        )

    if n_fail:
        reasons.append(
            f"Blocking: model/task failure evidence in "
            f"{', '.join(f'run #{i} (FAIL)' for i in sorted(by_category[RUN_CATEGORY_FAIL]))}."
        )
        reasons.extend([unknown_rule, infra_rule])
        return ComputedAssessment(
            state=ComputedQualificationState.NOT_QUALIFIED,
            reasons=tuple(reasons),
            counts=counts,
            classified=classified,
        )

    if n_pass + n_findings == 0:
        reasons.append(
            f"No passing evidence; only unresolved review items in "
            f"{', '.join(f'run #{i}' for i in sorted(by_category[RUN_CATEGORY_NEEDS_REVIEW]))}."
        )
        reasons.extend([unknown_rule, infra_rule])
        return ComputedAssessment(
            state=ComputedQualificationState.NOT_QUALIFIED,
            reasons=tuple(reasons),
            counts=counts,
            classified=classified,
        )

    if n_review:
        reasons.append(
            f"Passing evidence exists, but review is unresolved in "
            f"{', '.join(f'run #{i}' for i in sorted(by_category[RUN_CATEGORY_NEEDS_REVIEW]))}; "
            f"escalate on those conditions before autonomous use."
        )
        reasons.extend([unknown_rule, infra_rule])
        return ComputedAssessment(
            state=ComputedQualificationState.QUALIFIED_ESCALATE_ON_CONDITIONS,
            reasons=tuple(reasons),
            counts=counts,
            classified=classified,
        )

    if n_evaluated == 1:
        sole = sorted(evaluated_ids)[0]
        reasons.append(
            f"Single passing run (run #{sole}); evidence is promising but too "
            f"thin for full qualification."
        )
        if has_flags:
            flag_parts: list[str] = []
            if n_findings:
                flag_parts.append(
                    f"findings in run #{sole}" if sole in by_category[RUN_CATEGORY_PASS_WITH_FINDINGS] else "pass-with-findings verdicts present"
                )
            if intervention_ids:
                flag_parts.append(
                    f"human intervention in {', '.join(f'run #{i}' for i in intervention_ids)}"
                )
            if permission_ids:
                flag_parts.append(
                    f"permission denial in {', '.join(f'run #{i}' for i in permission_ids)}"
                )
            reasons.append(f"Noted conditions ({'; '.join(flag_parts)}); re-evaluate after a second clean pass.")
        reasons.extend([unknown_rule, infra_rule])
        return ComputedAssessment(
            state=ComputedQualificationState.PROVISIONALLY_QUALIFIED,
            reasons=tuple(reasons),
            counts=counts,
            classified=classified,
        )

    # n_evaluated >= 2, no fail, no unresolved review.
    if not has_flags:
        reasons.append(
            f"{n_evaluated} evaluated runs, all clean passes with no "
            f"intervention, permission denial, or findings."
        )
        reasons.extend([unknown_rule, infra_rule])
        return ComputedAssessment(
            state=ComputedQualificationState.QUALIFIED_AUTONOMOUS,
            reasons=tuple(reasons),
            counts=counts,
            classified=classified,
        )

    flag_parts = []
    if n_findings:
        flag_parts.append(
            f"pass-with-findings in {', '.join(f'run #{i}' for i in sorted(by_category[RUN_CATEGORY_PASS_WITH_FINDINGS]))}"
        )
    if intervention_ids:
        flag_parts.append(
            f"human intervention in {', '.join(f'run #{i}' for i in intervention_ids)}"
        )
    if permission_ids:
        flag_parts.append(
            f"permission denial in {', '.join(f'run #{i}' for i in permission_ids)}"
        )
    reasons.append(
        f"Passing evidence exists but requires operator review: {'; '.join(flag_parts)}."
    )
    reasons.extend([unknown_rule, infra_rule])
    return ComputedAssessment(
        state=ComputedQualificationState.QUALIFIED_REVIEW_REQUIRED,
        reasons=tuple(reasons),
        counts=counts,
        classified=classified,
    )
