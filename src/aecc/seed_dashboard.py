"""Deterministic dashboard seed/demo fixture.

Populates the existing Phase 2 evidence model with rows exercising every
edge case the Operator dashboard must render (see
docs/OPERATOR_DASHBOARD_V1_SPEC.md section 6):

1. successful/pass-scored run with known zero-dollar cost;
2. run with process SUCCESS but task FAILED and a failing verdict;
3. run/attempt with permission denial and human intervention evidence;
4. run with UNKNOWN/not-recorded score and cost fields;
5. two score revisions for one run (history/latest);
6. two qualification decisions for one triple (current/history);
7. one qualification evidence link to a run;
8. one exclusion and one intervention event retained for drill-down.

Route logic never depends on these rows; tests build isolated databases
through ``seed_dashboard_data(session)`` and assert rendered behavior.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from aecc.hashing import build_definition_payload, canonical_definition_hash
from aecc.models import (
    Attempt,
    Capability,
    DeliverableOutcome,
    EvaluatorVerdict,
    ExclusionEvent,
    FailureClassification,
    Harness,
    InterventionEvent,
    LogicalTest,
    Model,
    ProcessOutcome,
    QualificationDecision,
    QualificationEvidence,
    QualificationState,
    RepoModificationOutcome,
    Run,
    RunState,
    ScoreRevision,
    TaskOutcome,
    TestVersion,
)

BASE = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)


def _payload(prompt: str, cap_key: str, commit: str = "abc123def") -> dict:
    return build_definition_payload(
        task_prompt=prompt,
        acceptance_criteria="acceptance criteria",
        rubric_id="rubric-dashboard",
        rubric_version="1.0",
        source_fixture_ref="fixture-dashboard",
        source_commit=commit,
        permission_profile="WORKSPACE_WRITE_AND_SHELL_CONTAINED",
        retry_policy={"max_attempts": 2},
        timeout_seconds=300,
        expected_artifacts=["out.txt"],
        capability_key=cap_key,
    )


def _test_version(
    session: Session,
    logical: LogicalTest,
    number: int,
    prompt: str,
    cap_key: str,
    supersedes: int | None = None,
) -> TestVersion:
    payload = _payload(prompt, cap_key)
    tv = TestVersion(
        logical_test_id=logical.id,
        version_number=number,
        task_prompt=prompt,
        capability_key=cap_key,
        acceptance_criteria="acceptance criteria",
        rubric_id="rubric-dashboard",
        rubric_version="1.0",
        retry_policy='{"max_attempts": 2}',
        timeout_seconds=300,
        expected_artifacts='["out.txt"]',
        permission_profile="WORKSPACE_WRITE_AND_SHELL_CONTAINED",
        source_fixture_ref="fixture-dashboard",
        source_commit="abc123def",
        created_at=BASE,
        registered_at=BASE,
        definition_hash=canonical_definition_hash(payload),
        supersedes_version_id=supersedes,
    )
    session.add(tv)
    session.flush()
    return tv


def seed_dashboard_data(session: Session) -> dict:
    """Insert deterministic demo evidence. Returns ids for tests/demo."""
    h1 = Harness(harness_key="opencode", display_name="opencode", version="1.4.2", build="build-2026.09.01", config_snapshot='{"mode":"contained"}', config_hash="cfg-opencode-142")
    h2 = Harness(harness_key="opencode-strict", display_name="opencode-strict", version="2.0.0", build="build-2026.09.02", config_snapshot='{"mode":"restricted"}', config_hash="cfg-strict-200")
    m1 = Model(model_key="cheap-free", provider="test-provider", exact_identifier="test-provider/opencode-cheap-1.0-extended-identifier-for-readability", pricing_class="free", pricing_tier="free", price_input=0.0, price_output=0.0, is_active=True, config_params='{"effort":"low"}')
    m2 = Model(model_key="frontier-x", provider="other-provider", exact_identifier="other-provider/frontier-x-2026.01-preview-long-exact-identifier", pricing_class="paid", pricing_tier="paid", price_input=0.15, price_output=0.60, is_active=True, config_params='{"effort":"high"}')
    cap_bug = Capability(capability_key="bug-fixing", version="v1", definition="fix defects", description="Bug fixing capability")
    cap_ref = Capability(capability_key="refactoring", version="v2", definition="restructure code", description="Refactoring capability")
    lt1 = LogicalTest(key="dashboard-login-fix", name="Login fix", description="fix login bug")
    lt2 = LogicalTest(key="dashboard-refactor", name="Refactor billing", description="refactor billing")
    session.add_all([h1, h2, m1, m2, cap_bug, cap_ref, lt1, lt2]); session.flush()
    tv1 = _test_version(session, lt1, 1, "fix the login redirect bug", "bug-fixing")
    tv2 = _test_version(session, lt2, 1, "refactor the billing module", "refactoring")
    def _run(tv, h, m, cap, day_offset, state):
        r = Run(test_version_id=tv.id, harness_id=h.id, model_id=m.id, capability_id=cap.id, methodology_version="method-1.0", permission_profile="WORKSPACE_WRITE_AND_SHELL_CONTAINED", source_commit="abc123def", source_fixture="fixture-dashboard", state=state, requested_at=BASE + timedelta(days=day_offset), started_at=BASE + timedelta(days=day_offset, minutes=1), finished_at=BASE + timedelta(days=day_offset, minutes=6)); session.add(r); session.flush(); return r
    r1 = _run(tv1, h1, m1, cap_bug, 0, RunState.FINALIZED)
    r2 = _run(tv1, h1, m2, cap_bug, 1, RunState.FINALIZED)
    r3 = _run(tv1, h2, m1, cap_bug, 2, RunState.NEEDS_REVIEW)
    r4 = _run(tv2, h2, m2, cap_ref, 3, RunState.COMPLETED)
    a1 = Attempt(run_id=r1.id, attempt_number=1, exit_code=0, started_at=BASE, finished_at=BASE + timedelta(seconds=92), elapsed_seconds=92.0, time_to_first_output_seconds=4.5, process_outcome=ProcessOutcome.SUCCESS, deliverable_outcome=DeliverableOutcome.PRESENT, task_outcome=TaskOutcome.SUCCEEDED, repo_modification_outcome=RepoModificationOutcome.MODIFIED, permission_denied=False, timed_out=False, cancelled=False, tokens_input=1200, tokens_output=800, cost=0.0, cost_source="pricing-snapshot-v3 (free tier, billed zero)", provider_response_meta='{"route":"free-tier"}', human_intervention=False, frontier_escalation=False, failure_primary=None, failure_secondary=None, raw_evidence_location="runs/r1/a1", artifact_refs='["out.txt"]', invocation_meta='{"harness":"opencode 1.4.2"}', sealed_at=BASE + timedelta(minutes=6))
    a2 = Attempt(run_id=r2.id, attempt_number=1, exit_code=0, started_at=BASE + timedelta(days=1), finished_at=BASE + timedelta(days=1, seconds=61), elapsed_seconds=61.0, time_to_first_output_seconds=3.0, process_outcome=ProcessOutcome.SUCCESS, deliverable_outcome=DeliverableOutcome.MISSING, task_outcome=TaskOutcome.FAILED, repo_modification_outcome=RepoModificationOutcome.UNMODIFIED, permission_denied=False, timed_out=False, cancelled=False, tokens_input=0, tokens_output=0, cost=0.0045, cost_source="pricing-snapshot-v3", human_intervention=False, frontier_escalation=False, failure_primary=FailureClassification.TASK_FAILURE, failure_secondary=FailureClassification.UNKNOWN, raw_evidence_location="runs/r2/a1", sealed_at=BASE + timedelta(days=1, minutes=6))
    a3 = Attempt(run_id=r3.id, attempt_number=1, exit_code=1, started_at=BASE + timedelta(days=2), finished_at=BASE + timedelta(days=2, seconds=45), elapsed_seconds=45.0, time_to_first_output_seconds=2.0, process_outcome=ProcessOutcome.FAILURE, deliverable_outcome=DeliverableOutcome.MISSING, task_outcome=TaskOutcome.NEEDS_REVIEW, repo_modification_outcome=RepoModificationOutcome.NOT_CHECKED, permission_denied=True, permission_denial_evidence="denied: shell tool 'exec' not in profile WORKSPACE_WRITE_RESTRICTED", timed_out=False, cancelled=False, tokens_input=640, tokens_output=210, cost=0.0012, cost_source="pricing-snapshot-v3", human_intervention=True, frontier_escalation=False, failure_primary=FailureClassification.PERMISSION_POLICY_FAILURE, failure_secondary=FailureClassification.TASK_FAILURE, raw_evidence_location="runs/r3/a1", sealed_at=BASE + timedelta(days=2, minutes=6))
    a4 = Attempt(run_id=r4.id, attempt_number=1, exit_code=None, started_at=BASE + timedelta(days=3), finished_at=None, elapsed_seconds=None, time_to_first_output_seconds=None, process_outcome=ProcessOutcome.UNKNOWN, deliverable_outcome=DeliverableOutcome.UNKNOWN, task_outcome=TaskOutcome.UNKNOWN, repo_modification_outcome=RepoModificationOutcome.UNKNOWN, permission_denied=False, timed_out=False, cancelled=False, tokens_input=None, tokens_output=None, cost=None, cost_source=None, human_intervention=False, frontier_escalation=False, failure_primary=FailureClassification.UNKNOWN, failure_secondary=None, raw_evidence_location="runs/r4/a1", sealed_at=BASE + timedelta(days=3, minutes=6))
    session.add_all([a1, a2, a3, a4]); session.flush()
    s1a = ScoreRevision(run_id=r1.id, attempt_id=a1.id, rubric_version="rubric-dashboard/1.0", dimension_scores='{"correctness": 0.85}', total_score=0.85, verdict=EvaluatorVerdict.PASS, notes="initial scoring", evaluator_identity="evaluator-1", created_at=BASE + timedelta(hours=1)); session.add(s1a); session.flush()
    s1b = ScoreRevision(run_id=r1.id, attempt_id=a1.id, rubric_version="rubric-dashboard/1.0", dimension_scores='{"correctness": 0.95}', total_score=0.95, verdict=EvaluatorVerdict.PASS, notes="correction after artifact recheck", evaluator_identity="evaluator-1", created_at=BASE + timedelta(hours=2), supersedes_revision_id=s1a.id)
    s2 = ScoreRevision(run_id=r2.id, attempt_id=a2.id, rubric_version="rubric-dashboard/1.0", dimension_scores='{"correctness": 0.1}', total_score=0.1, verdict=EvaluatorVerdict.FAIL, notes="exit 0 but no deliverable produced", evaluator_identity="evaluator-1", created_at=BASE + timedelta(days=1, hours=1))
    s3 = ScoreRevision(run_id=r3.id, attempt_id=a3.id, rubric_version="rubric-dashboard/1.0", dimension_scores='{"correctness": 0.4}', total_score=0.4, verdict=EvaluatorVerdict.NEEDS_REVIEW, notes="permission denial; operator clarified scope", evaluator_identity="evaluator-1", created_at=BASE + timedelta(days=2, hours=1))
    session.add_all([s1b, s2, s3]); session.flush()
    interv = InterventionEvent(run_id=r3.id, attempt_id=a3.id, kind="prompt_clarification", actor="operator-1", reason="operator clarified file scope after permission denial", created_at=BASE + timedelta(days=2, minutes=10))
    excl = ExclusionEvent(run_id=r3.id, attempt_id=a3.id, reason="attempt 1 excluded from pass-rate aggregate: broken fixture path", author="operator-1", created_at=BASE + timedelta(days=2, minutes=20), methodology_version="method-1.0", scope="aggregate-pass-rate")
    session.add_all([interv, excl]); session.flush()
    q1a = QualificationDecision(harness_id=h1.id, model_id=m1.id, capability_id=cap_bug.id, state=QualificationState.SHADOW, methodology_version="qual-policy-1", decided_at=BASE + timedelta(hours=3), author="operator-1", evidence_summary="initial shadow qualification"); session.add(q1a); session.flush()
    q1b = QualificationDecision(harness_id=h1.id, model_id=m1.id, capability_id=cap_bug.id, state=QualificationState.QUALIFIED, methodology_version="qual-policy-1", decided_at=BASE + timedelta(hours=4), author="operator-1", restrictions="contained workspace only", evidence_summary="promotion after passing evidence", supersedes_decision_id=q1a.id); session.add(q1b); session.flush(); session.add(QualificationEvidence(qualification_id=q1b.id, run_id=r1.id, attempt_id=a1.id))
    q2 = QualificationDecision(harness_id=h1.id, model_id=m2.id, capability_id=cap_bug.id, state=QualificationState.RESTRICTED, methodology_version="qual-policy-1", decided_at=BASE + timedelta(days=1, hours=3), author="operator-1", restrictions="requires human review: deliverable missing despite exit 0", evidence_summary="task failure despite process success"); session.add(q2); session.flush(); session.add(QualificationEvidence(qualification_id=q2.id, run_id=r2.id, attempt_id=None))
    q4 = QualificationDecision(harness_id=h2.id, model_id=m2.id, capability_id=cap_ref.id, state=QualificationState.UNQUALIFIED, methodology_version="qual-policy-1", decided_at=BASE + timedelta(days=3, hours=3), author="operator-1", evidence_summary="insufficient evidence (unscored run)"); session.add(q4); session.flush()
    session.commit()
    return {"runs": {"r1": r1.id, "r2": r2.id, "r3": r3.id, "r4": r4.id}, "attempts": {"a1": a1.id, "a2": a2.id, "a3": a3.id, "a4": a4.id}, "scores": {"s1a": s1a.id, "s1b": s1b.id, "s2": s2.id, "s3": s3.id}, "quals": {"q1a": q1a.id, "q1b": q1b.id, "q2": q2.id, "q4": q4.id}, "harness": {"h1": h1.id, "h2": h2.id}, "models": {"m1": m1.id, "m2": m2.id}, "capabilities": {"bug": cap_bug.id, "ref": cap_ref.id}}
