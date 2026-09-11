"""Comparison / Qualification milestone tests: deterministic computed states.

Exercises real HTTP routes against an isolated migrated SQLite database:
base evidence from ``seed_dashboard_data`` plus extra triples covering every
computed state. Also unit-tests the pure assessment function for
determinism, UNKNOWN semantics, and infra/model-failure separation.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

BASE = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)


def _alembic_config(db_file: Path) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_file}")
    return cfg


def _add_run(
    session,
    *,
    harness,
    model,
    capability,
    logical_test,
    version_number: int,
    verdict,
    day_offset: float,
    is_demo: bool = False,
    run_state=None,
    failure_primary=None,
    human_intervention: bool = False,
    permission_denied: bool = False,
    with_exclusion: bool = False,
    score_none: bool = False,
    task_prompt: str = "do the thing",
):
    """Insert one run + sealed attempt (+ score unless score_none)."""
    from aecc.hashing import build_definition_payload, canonical_definition_hash
    from aecc.models import (
        Attempt,
        DeliverableOutcome,
        ExclusionEvent,
        ProcessOutcome,
        RepoModificationOutcome,
        Run,
        RunState,
        ScoreRevision,
        TaskOutcome,
        TestVersion,
    )

    payload = build_definition_payload(
        task_prompt=task_prompt,
        acceptance_criteria="ac",
        rubric_id="rubric-cmp",
        rubric_version="1.0",
        source_fixture_ref="fixture-cmp",
        source_commit="abc123def",
        permission_profile="READ_ONLY_NO_SHELL",
        retry_policy={"max_attempts": 1},
        timeout_seconds=60,
        expected_artifacts=["out.txt"],
        capability_key=capability.capability_key,
    )
    # Reuse the same frozen test version when the caller repeats the same
    # logical test + version number so repeated trials of one exact test
    # context share one TestVersion row (mirrors production: many runs per
    # registered version). Different version numbers still create distinct
    # frozen contexts.
    tv = session.scalar(
        sa.select(TestVersion).where(
            TestVersion.logical_test_id == logical_test.id,
            TestVersion.version_number == version_number,
        )
    )
    if tv is None:
        tv = TestVersion(
            logical_test_id=logical_test.id,
            version_number=version_number,
            task_prompt=task_prompt,
            capability_key=capability.capability_key,
            capability_version=capability.version,
            acceptance_criteria="ac",
            rubric_id="rubric-cmp",
            rubric_version="1.0",
            permission_profile="READ_ONLY_NO_SHELL",
            source_fixture_ref="fixture-cmp",
            source_commit="abc123def",
            created_at=BASE,
            registered_at=BASE,
            definition_hash=canonical_definition_hash(payload),
            is_demo=is_demo,
        )
        session.add(tv)
        session.flush()
    run = Run(
        test_version_id=tv.id,
        harness_id=harness.id,
        model_id=model.id,
        capability_id=capability.id,
        state=run_state or RunState.FINALIZED,
        requested_at=BASE + timedelta(days=day_offset),
        started_at=BASE + timedelta(days=day_offset, minutes=1),
        finished_at=BASE + timedelta(days=day_offset, minutes=6),
        is_demo=is_demo,
    )
    session.add(run)
    session.flush()
    attempt = Attempt(
        run_id=run.id,
        attempt_number=1,
        exit_code=0,
        started_at=BASE + timedelta(days=day_offset),
        finished_at=BASE + timedelta(days=day_offset, minutes=5),
        elapsed_seconds=60.0,
        process_outcome=ProcessOutcome.SUCCESS,
        deliverable_outcome=DeliverableOutcome.PRESENT,
        task_outcome=TaskOutcome.SUCCEEDED,
        repo_modification_outcome=RepoModificationOutcome.MODIFIED,
        permission_denied=permission_denied,
        timed_out=False,
        cancelled=False,
        tokens_input=100,
        tokens_output=50,
        cost=0.001,
        cost_source="pricing-snapshot-v3",
        human_intervention=human_intervention,
        frontier_escalation=False,
        failure_primary=failure_primary,
        raw_evidence_location=f"runs/cmp/{run.id}",
        sealed_at=BASE + timedelta(days=day_offset, minutes=6),
        is_demo=is_demo,
    )
    session.add(attempt)
    session.flush()
    if not score_none:
        session.add(
            ScoreRevision(
                run_id=run.id,
                attempt_id=attempt.id,
                rubric_version="rubric-cmp/1.0",
                total_score=0.9,
                verdict=verdict,
                evaluator_identity="evaluator-1",
                created_at=BASE + timedelta(days=day_offset, hours=1),
                is_demo=is_demo,
            )
        )
        session.flush()
    if with_exclusion:
        session.add(
            ExclusionEvent(
                run_id=run.id,
                attempt_id=attempt.id,
                reason="operator exclusion for comparison test",
                author="operator-1",
                created_at=BASE + timedelta(days=day_offset, hours=2),
                methodology_version="method-1.0",
                scope="aggregate-pass-rate",
                is_demo=is_demo,
            )
        )
        session.flush()
    return run


@pytest.fixture()
def client(tmp_path):
    command.upgrade(_alembic_config(tmp_path / "compare.sqlite"), "head")
    engine = sa.create_engine(
        f"sqlite:///{tmp_path / 'compare.sqlite'}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    from aecc.db import apply_sqlite_pragmas, create_session_factory

    apply_sqlite_pragmas(engine)
    from aecc.seed_dashboard import seed_dashboard_data

    factory = create_session_factory(engine)
    with factory() as session:
        ids = seed_dashboard_data(session)
        from aecc.models import Capability, EvaluatorVerdict, Harness, LogicalTest, Model

        h_auto = Harness(harness_key="cmp-harness", version="9.9.9", is_demo=False)
        m_auto = Model(
            model_key="cmp-auto",
            provider="cmp-provider",
            exact_identifier="cmp-provider/cmp-auto-exact-identifier",
            is_active=True,
            is_demo=False,
        )
        m_rev = Model(
            model_key="cmp-review",
            provider="cmp-provider",
            exact_identifier="cmp-provider/cmp-review-exact-identifier",
            is_active=True,
            is_demo=False,
        )
        m_esc = Model(
            model_key="cmp-escalate",
            provider="cmp-provider",
            exact_identifier="cmp-provider/cmp-escalate-exact-identifier",
            is_active=True,
            is_demo=False,
        )
        cap_auto = Capability(
            capability_key="comparison.autonomous", version="v1", is_demo=False
        )
        lt = LogicalTest(key="cmp-logical", name="Cmp logical", is_demo=False)
        session.add_all([h_auto, m_auto, m_rev, m_esc, cap_auto, lt])
        session.flush()
        # Autonomous: two clean passes of the same exact test version.
        # Review Required / Escalate triples likewise repeat one frozen
        # version twice: qualification groups preserve exact test context, so
        # repeated trials must reference the same TestVersion to combine.
        _add_run(session, harness=h_auto, model=m_auto, capability=cap_auto,
                 logical_test=lt, version_number=1, verdict=EvaluatorVerdict.PASS, day_offset=10)
        _add_run(session, harness=h_auto, model=m_auto, capability=cap_auto,
                 logical_test=lt, version_number=1, verdict=EvaluatorVerdict.PASS, day_offset=11)
        # Review Required: two passes, one with human intervention.
        _add_run(session, harness=h_auto, model=m_rev, capability=cap_auto,
                 logical_test=lt, version_number=3, verdict=EvaluatorVerdict.PASS, day_offset=12)
        _add_run(session, harness=h_auto, model=m_rev, capability=cap_auto,
                 logical_test=lt, version_number=3, verdict=EvaluatorVerdict.PASS_WITH_FINDINGS,
                 day_offset=13, human_intervention=True)
        # Escalate on Conditions: one pass plus one unresolved review.
        _add_run(session, harness=h_auto, model=m_esc, capability=cap_auto,
                 logical_test=lt, version_number=5, verdict=EvaluatorVerdict.PASS, day_offset=14)
        _add_run(session, harness=h_auto, model=m_esc, capability=cap_auto,
                 logical_test=lt, version_number=5, verdict=EvaluatorVerdict.NEEDS_REVIEW, day_offset=15)
        session.commit()
        ids["cmp"] = {
            "harness_id": h_auto.id,
            "capability_id": cap_auto.id,
            "models": {"auto": m_auto.id, "rev": m_rev.id, "esc": m_esc.id},
        }

    from aecc.web import create_app
    from fastapi.testclient import TestClient

    app = create_app(engine=engine)
    test_client = TestClient(app)
    test_client.ids = ids  # type: ignore[attr-defined]
    test_client.engine = engine  # type: ignore[attr-defined]
    try:
        yield test_client
    finally:
        engine.dispose()


def _ids(client):
    return client.ids


# ---------------------------------------------------------------------------
# Pure-function determinism and semantics
# ---------------------------------------------------------------------------


def test_assess_deterministic_same_evidence_same_result():
    from aecc.qualification import RunEvidence, assess_triple

    evidences = [
        RunEvidence(run_id=2, verdict="PASS"),
        RunEvidence(run_id=1, verdict="PASS"),
    ]
    first = assess_triple(evidences)
    second = assess_triple(list(reversed(evidences)))
    assert first.state == second.state
    assert first.reasons == second.reasons
    assert first.counts == second.counts
    assert first.label == "Qualified \u2014 Autonomous"


def test_all_six_states_reachable():
    from aecc.qualification import ComputedQualificationState, RunEvidence, assess_triple

    cases = {
        ComputedQualificationState.QUALIFIED_AUTONOMOUS: [
            RunEvidence(run_id=1, verdict="PASS"),
            RunEvidence(run_id=2, verdict="PASS"),
        ],
        ComputedQualificationState.QUALIFIED_REVIEW_REQUIRED: [
            RunEvidence(run_id=1, verdict="PASS"),
            RunEvidence(run_id=2, verdict="PASS_WITH_FINDINGS"),
        ],
        ComputedQualificationState.QUALIFIED_ESCALATE_ON_CONDITIONS: [
            RunEvidence(run_id=1, verdict="PASS"),
            RunEvidence(run_id=2, verdict="NEEDS_REVIEW"),
        ],
        ComputedQualificationState.PROVISIONALLY_QUALIFIED: [
            RunEvidence(run_id=1, verdict="PASS"),
        ],
        ComputedQualificationState.INSUFFICIENT_EVIDENCE: [
            RunEvidence(run_id=1, verdict="UNKNOWN"),
            RunEvidence(run_id=2, verdict=None),
        ],
        ComputedQualificationState.NOT_QUALIFIED: [
            RunEvidence(run_id=1, verdict="PASS"),
            RunEvidence(run_id=2, verdict="FAIL"),
        ],
    }
    for expected, evidences in cases.items():
        assert assess_triple(evidences).state == expected, expected


def test_unknown_never_counts_as_pass():
    from aecc.qualification import ComputedQualificationState, RunEvidence, assess_triple

    assessment = assess_triple(
        [RunEvidence(run_id=1, verdict=None), RunEvidence(run_id=2, verdict="UNKNOWN")]
    )
    assert assessment.state == ComputedQualificationState.INSUFFICIENT_EVIDENCE
    assert assessment.counts["pass"] == 0
    assert any("never counted as pass" in r for r in assessment.reasons)


def test_infrastructure_failure_does_not_cause_not_qualified():
    from aecc.qualification import ComputedQualificationState, RunEvidence, assess_triple

    assessment = assess_triple(
        [
            RunEvidence(run_id=1, verdict="INFRASTRUCTURE_FAILURE",
                        failure_primary="INFRASTRUCTURE_FAILURE", run_state="INFRASTRUCTURE_FAILURE"),
            RunEvidence(run_id=2, verdict="PASS"),
            RunEvidence(run_id=3, verdict="PASS"),
        ]
    )
    assert assessment.state == ComputedQualificationState.QUALIFIED_AUTONOMOUS
    assert assessment.counts["infrastructure"] == 1
    assert assessment.counts["evaluated"] == 2


def test_infra_only_triple_is_insufficient_not_not_qualified():
    from aecc.qualification import ComputedQualificationState, RunEvidence, assess_triple

    assessment = assess_triple(
        [RunEvidence(run_id=1, verdict="INFRASTRUCTURE_FAILURE",
                     failure_primary="INFRASTRUCTURE_FAILURE")]
    )
    assert assessment.state == ComputedQualificationState.INSUFFICIENT_EVIDENCE


def test_demo_runs_set_aside_and_disclosed():
    from aecc.qualification import ComputedQualificationState, RunEvidence, assess_triple

    assessment = assess_triple(
        [
            RunEvidence(run_id=1, verdict="PASS"),
            RunEvidence(run_id=2, verdict="PASS"),
            RunEvidence(run_id=3, verdict="FAIL", is_demo=True),
        ]
    )
    assert assessment.state == ComputedQualificationState.QUALIFIED_AUTONOMOUS
    assert assessment.counts["demo_set_aside"] == 1
    assert any("demo" in r.lower() for r in assessment.reasons)


# ---------------------------------------------------------------------------
# HTTP: comparison page
# ---------------------------------------------------------------------------


def test_compare_returns_200_with_navigation(client):
    html = client.get("/operator/compare").text
    assert client.get("/operator/compare").status_code == 200
    assert "<h1>" in html
    assert 'href="/operator/compare"' in html
    assert 'href="/operator/qualification"' in html
    assert "Model + Harness Comparison" in html


def test_compare_shows_exact_identity_and_drilldown(client):
    html = client.get("/operator/compare").text
    assert "cmp-provider/cmp-auto-exact-identifier" in html
    assert "comparison.autonomous" in html
    run_id = _ids(client)["runs"]["r1"]
    assert f'href="/operator/runs/{run_id}"' in html


def test_compare_context_filter_and_errors(client):
    cap_id = _ids(client)["cmp"]["capability_id"]
    seed_r1 = _ids(client)["runs"]["r1"]
    html = client.get(f"/operator/compare?capability_id={cap_id}").text
    assert "comparison.autonomous" in html
    assert f'data-run-id="{seed_r1}"' not in html  # other contexts filtered out
    assert client.get("/operator/compare?capability_id=abc").status_code == 400
    assert client.get("/operator/compare?capability_id=999999").status_code == 404
    assert client.get("/operator/compare?test_version_id=999999").status_code == 404


def test_compare_excludes_queued_runs(client):
    from aecc.db import create_session_factory
    from aecc.models import Run, RunState

    factory = create_session_factory(client.engine)
    with factory() as session:
        existing = session.scalars(__import__("sqlalchemy").select(Run).limit(1)).one()
        queued = Run(
            test_version_id=existing.test_version_id,
            harness_id=existing.harness_id,
            model_id=existing.model_id,
            capability_id=existing.capability_id,
            state=RunState.QUEUED,
            requested_at=BASE + timedelta(days=99),
            is_demo=False,
        )
        session.add(queued)
        session.commit()
        queued_id = queued.id
    html = client.get("/operator/compare").text
    assert f'data-run-id="{queued_id}"' not in html


def test_compare_evidence_class_distinguishes_infra_from_task_failure(client):
    html = client.get("/operator/compare").text
    assert "infrastructure" in html or "excluded" in html or "unknown" in html
    r2 = _ids(client)["runs"]["r2"]
    row = html.split(f'data-run-id="{r2}"')[1].split("</tr>")[0]
    assert "FAIL" in row
    assert "fail" in row  # evidence class badge for the task failure


# ---------------------------------------------------------------------------
# HTTP: computed qualification page
# ---------------------------------------------------------------------------


def test_computed_qualification_returns_200_with_all_states(client):
    response = client.get("/operator/qualification")
    assert response.status_code == 200
    html = response.text
    for label in (
        "Qualified \u2014 Autonomous",
        "Qualified \u2014 Review Required",
        "Qualified \u2014 Escalate on Conditions",
        "Provisionally Qualified",
        "Insufficient Evidence",
        "Not Qualified",
    ):
        assert label in html, label


def test_computed_qualification_shows_why_and_drilldown(client):
    html = client.get("/operator/qualification").text
    assert "Why this state was assigned" in html
    assert "never counted as pass" in html
    assert "Infrastructure failures are distinguished" in html
    run_id = _ids(client)["runs"]["r1"]
    assert f'href="/operator/runs/{run_id}"' in html
    assert "data-testid=" in html


def test_computed_unknown_not_styled_as_success(client):
    html = client.get("/operator/qualification").text
    assert "badge-unknown" in html
    assert "badge-pass\">Insufficient Evidence" not in html
    assert "badge-pass\">UNKNOWN" not in html


def test_computed_qualification_deterministic_across_requests(client):
    first = client.get("/operator/qualification").text
    second = client.get("/operator/qualification").text
    assert first == second


def test_run_detail_shows_evidence_class_and_compare_links(client):
    run_id = _ids(client)["runs"]["r1"]
    detail = client.get(f"/operator/runs/{run_id}").text
    assert "Evidence class" in detail
    assert 'href="/operator/compare"' in detail
    assert 'href="/operator/qualification"' in detail


def test_stored_qualification_board_still_triple_keyed(client):
    html = client.get("/operator/qualifications").text
    assert "QUALIFIED" in html
    assert "promotion after passing evidence" in html
    overview = client.get("/operator").text
    assert 'href="/operator/compare"' in overview
    assert 'href="/operator/qualification"' in overview


# ---------------------------------------------------------------------------
# Regression: in-flight work must never count as qualification evidence
# ---------------------------------------------------------------------------


def test_inflight_states_never_count_as_evidence(client):
    from aecc.dashboard_queries import (
        COMPLETED_EVIDENCE_STATES,
        fetch_compare_rows,
        fetch_computed_qualifications,
    )
    from aecc.db import create_session_factory
    from aecc.models import Capability, EvaluatorVerdict, Harness, LogicalTest, Model, RunState

    # SCORING is in-flight (QUEUED -> CLAIMED -> RUNNING -> COMPLETED ->
    # SCORING -> FINALIZED) and must not be treated as completed evidence.
    assert "SCORING" not in COMPLETED_EVIDENCE_STATES
    for in_flight in ("QUEUED", "CLAIMED", "RUNNING", "SCORING", "CANCEL_REQUESTED", "CANCELLED"):
        assert in_flight not in COMPLETED_EVIDENCE_STATES

    factory = create_session_factory(client.engine)
    with factory() as session:
        h = Harness(harness_key="inflight-harness", version="1.0", is_demo=False)
        m = Model(
            model_key="inflight-model",
            provider="cmp-provider",
            exact_identifier="cmp-provider/inflight-exact-identifier",
            is_active=True,
            is_demo=False,
        )
        cap = Capability(capability_key="inflight.cap", version="v1", is_demo=False)
        lt = LogicalTest(key="inflight-logical", name="Inflight logical", is_demo=False)
        session.add_all([h, m, cap, lt])
        session.flush()
        # Triple with ONLY in-flight runs (each scored PASS to prove even
        # scored in-flight work cannot qualify).
        for idx, state in enumerate((RunState.QUEUED, RunState.RUNNING, RunState.SCORING)):
            _add_run(
                session,
                harness=h,
                model=m,
                capability=cap,
                logical_test=lt,
                version_number=50 + idx,
                verdict=EvaluatorVerdict.PASS,
                day_offset=60 + idx,
                run_state=state,
            )
        session.commit()
        inflight_triple = (h.id, m.id, cap.id)

    with factory() as session:
        rows = fetch_computed_qualifications(session)
        assert all(r["triple"] != inflight_triple for r in rows)
        compare = fetch_compare_rows(session, limit=1000)
        compare_ids = {r["run"].id for r in compare}
        with factory() as s2:
            from sqlalchemy import select as _select

            from aecc.models import Run as _Run

            inflight_ids = set(
                s2.scalars(
                    _select(_Run.id).where(
                        _Run.harness_id == inflight_triple[0],
                        _Run.model_id == inflight_triple[1],
                        _Run.capability_id == inflight_triple[2],
                    )
                ).all()
            )
        assert inflight_ids, "expected in-flight runs to exist"
        assert not (inflight_ids & compare_ids)

    # In-flight PASS on an existing qualified context must not inflate it.
    with factory() as session:
        before = {
            (r["harness"].id, r["model"].id, r["capability"].id, r["test_version"].id): r["assessment"].counts["evaluated"]
            for r in fetch_computed_qualifications(session)
        }
        cmp_ids = _ids(client)["cmp"]
        h_id = cmp_ids["harness_id"]
        cap_id = cmp_ids["capability_id"]
        auto_id = cmp_ids["models"]["auto"]
        from sqlalchemy import select as _select

        from aecc.models import Run as _Run

        auto_runs = session.scalars(
            _select(_Run).where(
                _Run.harness_id == h_id,
                _Run.model_id == auto_id,
                _Run.capability_id == cap_id,
            )
        ).all()
        assert auto_runs
        target_tv = auto_runs[0].test_version_id
        from aecc.models import EvaluatorVerdict as _V, Run as _R

        extra = _R(
            test_version_id=target_tv,
            harness_id=h_id,
            model_id=auto_id,
            capability_id=cap_id,
            state=RunState.SCORING,
            requested_at=BASE + timedelta(days=99),
            is_demo=False,
        )
        session.add(extra)
        session.flush()
        from aecc.models import Attempt as _A
        from aecc.models import (
            DeliverableOutcome,
            ProcessOutcome,
            RepoModificationOutcome,
            ScoreRevision,
            TaskOutcome,
        )

        att = _A(
            run_id=extra.id,
            attempt_number=1,
            exit_code=0,
            started_at=BASE + timedelta(days=99),
            finished_at=BASE + timedelta(days=99, minutes=5),
            elapsed_seconds=60.0,
            process_outcome=ProcessOutcome.SUCCESS,
            deliverable_outcome=DeliverableOutcome.PRESENT,
            task_outcome=TaskOutcome.SUCCEEDED,
            repo_modification_outcome=RepoModificationOutcome.MODIFIED,
            sealed_at=BASE + timedelta(days=99, minutes=6),
            is_demo=False,
        )
        session.add(att)
        session.flush()
        session.add(
            ScoreRevision(
                run_id=extra.id,
                attempt_id=att.id,
                rubric_version="rubric-cmp/1.0",
                total_score=0.99,
                verdict=_V.PASS,
                evaluator_identity="evaluator-1",
                created_at=BASE + timedelta(days=99, hours=1),
                is_demo=False,
            )
        )
        session.commit()
        extra_id = extra.id

    with factory() as session:
        after = {
            (r["harness"].id, r["model"].id, r["capability"].id, r["test_version"].id): r["assessment"]
            for r in fetch_computed_qualifications(session)
        }
        key = (h_id, auto_id, cap_id, target_tv)
        assert key in after
        assert after[key].counts["evaluated"] == before[key]
        assert after[key].state.value == "QUALIFIED_AUTONOMOUS"
        compare = fetch_compare_rows(session, limit=1000)
        assert extra_id not in {r["run"].id for r in compare}
    html = client.get("/operator/compare").text
    assert f'data-run-id="{extra_id}"' not in html


# ---------------------------------------------------------------------------
# Regression: qualification must not blend different test contexts
# ---------------------------------------------------------------------------


def test_qualification_does_not_blend_different_test_versions(client):
    from aecc.dashboard_queries import fetch_computed_qualifications
    from aecc.db import create_session_factory
    from aecc.models import Capability, EvaluatorVerdict, Harness, LogicalTest, Model

    factory = create_session_factory(client.engine)
    with factory() as session:
        h = Harness(harness_key="split-harness", version="1.0", is_demo=False)
        m = Model(
            model_key="split-model",
            provider="cmp-provider",
            exact_identifier="cmp-provider/split-exact-identifier",
            is_active=True,
            is_demo=False,
        )
        cap = Capability(capability_key="split.cap", version="v1", is_demo=False)
        lt_a = LogicalTest(key="split-logical-a", name="Split A", is_demo=False)
        lt_b = LogicalTest(key="split-logical-b", name="Split B", is_demo=False)
        session.add_all([h, m, cap, lt_a, lt_b])
        session.flush()
        # Same harness+model+capability, two materially different test
        # contexts (different logical tests / frozen versions), one PASS each.
        # Blended this would look like 2 evaluated -> Autonomous; split it is
        # 2 groups of 1 evaluated -> Provisionally Qualified each.
        run_a = _add_run(
            session,
            harness=h,
            model=m,
            capability=cap,
            logical_test=lt_a,
            version_number=1,
            verdict=EvaluatorVerdict.PASS,
            day_offset=70,
            task_prompt="split task A",
        )
        run_b = _add_run(
            session,
            harness=h,
            model=m,
            capability=cap,
            logical_test=lt_b,
            version_number=1,
            verdict=EvaluatorVerdict.PASS,
            day_offset=71,
            task_prompt="split task B",
        )
        session.commit()
        tv_a, tv_b = run_a.test_version_id, run_b.test_version_id
        assert tv_a != tv_b

    with factory() as session:
        rows = [
            r
            for r in fetch_computed_qualifications(session)
            if (r["harness"].id, r["model"].id, r["capability"].id) == (h.id, m.id, cap.id)
        ]
        assert len(rows) == 2, f"expected 2 exact-context groups, got {len(rows)}"
        by_tv = {r["test_version"].id: r for r in rows}
        assert set(by_tv) == {tv_a, tv_b}
        for r in rows:
            assert r["assessment"].state.value == "PROVISIONALLY_QUALIFIED"
            assert r["assessment"].counts["evaluated"] == 1
            assert len(r["run_rows"]) == 1
        # Same logical test but materially different version content must
        # also stay separate (different frozen version ids).
    with factory() as session:
        run_c = _add_run(
            session,
            harness=h,
            model=m,
            capability=cap,
            logical_test=lt_a,
            version_number=2,
            verdict=EvaluatorVerdict.PASS,
            day_offset=72,
            task_prompt="split task A v2 materially different",
        )
        session.commit()
        tv_c = run_c.test_version_id
        assert tv_c not in (tv_a, tv_b)

    with factory() as session:
        rows = [
            r
            for r in fetch_computed_qualifications(session)
            if (r["harness"].id, r["model"].id, r["capability"].id) == (h.id, m.id, cap.id)
        ]
        assert len(rows) == 3
        assert {r["test_version"].id for r in rows} == {tv_a, tv_b, tv_c}


# ---------------------------------------------------------------------------
# Regression: populated Qualification page must not crash on demo/set-aside
# evidence (positional correlation of separate collections).
# ---------------------------------------------------------------------------


def test_qualification_demo_seed_renders_all_run_evidence(tmp_path):
    """Seed built-in demo data; GET /operator/qualification is 200 and safe.

    Demo runs are set aside from real qualification, so assessment.classified
    can be shorter than the displayed run_rows. Each run row carries its own
    deterministic classification, so every applicable run still renders.
    """
    from aecc.db import apply_sqlite_pragmas, create_session_factory

    command.upgrade(_alembic_config(tmp_path / "demo-qual.sqlite"), "head")
    engine = sa.create_engine(
        f"sqlite:///{tmp_path / 'demo-qual.sqlite'}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    apply_sqlite_pragmas(engine)
    try:
        from aecc.seed_dashboard import seed_dashboard_data

        factory = create_session_factory(engine)
        with factory() as session:
            seed_dashboard_data(session, is_demo=True)

        from aecc.dashboard_queries import fetch_computed_qualifications

        with factory() as session:
            rows = fetch_computed_qualifications(session)
            assert rows, "expected computed rows from demo seed"
            for row in rows:
                assert row["run_rows"], "each triple must show its run evidence"
                for rr in row["run_rows"]:
                    # Structural guarantee: row carries its own classification.
                    assert hasattr(rr["classification"], "category")
                    assert rr["classification"].run_id == rr["run"].id

        from aecc.web import create_app
        from fastapi.testclient import TestClient

        app = create_app(engine=engine)
        demo_client = TestClient(app)
        response = demo_client.get("/operator/qualification")
        assert response.status_code == 200, response.text[:2000]
        html = response.text
        with factory() as session:
            rows = fetch_computed_qualifications(session)
            for row in rows:
                for rr in row["run_rows"]:
                    assert f'data-run-id="{rr["run"].id}"' in html
                    assert rr["classification"].category in html
    finally:
        engine.dispose()
