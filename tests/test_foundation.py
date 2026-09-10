"""Foundation invariant tests: behavioral proof against a migrated SQLite database."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def make_alembic_config(db_file: Path) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_file}")
    return cfg


@pytest.fixture()
def db_file(tmp_path):
    path = tmp_path / "evaluations.sqlite"
    command.upgrade(make_alembic_config(path), "head")
    return path


@pytest.fixture()
def engine(db_file):
    import sys

    sys.path.insert(0, str(ROOT / "src"))
    from aecc.db import create_engine_for_path

    eng = create_engine_for_path(db_file)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture()
def session(engine):
    import sys

    sys.path.insert(0, str(ROOT / "src"))
    from aecc.db import create_session_factory

    factory = create_session_factory(engine)
    with factory() as sess:
        yield sess


def _seed_identities(sess: Session, tag: str = "t"):
    """Insert one harness, model, capability, logical test + registered version, run."""
    from aecc.models import Capability, Harness, LogicalTest, Model, Run, TestVersion
    from aecc.hashing import build_definition_payload, canonical_definition_hash

    harness = Harness(
        harness_key=f"harness-{tag}",
        display_name=f"Harness {tag}",
        version="1.0.0",
        build="b1",
        config_snapshot='{"mode":"contained"}',
        config_hash="cfghash",
    )
    model = Model(
        model_key=f"model-{tag}",
        provider="test-provider",
        exact_identifier="test-provider/model-1.0",
        pricing_class="free",
        config_params='{"effort":"low"}',
    )
    capability = Capability(
        capability_key=f"cap-{tag}", version="v1", definition="def", description="desc"
    )
    logical = LogicalTest(key=f"logical-{tag}", name=f"Logical {tag}", description="d")
    sess.add_all([harness, model, capability, logical])
    sess.flush()

    payload = build_definition_payload(
        task_prompt="do the thing",
        acceptance_criteria="accept",
        rubric_id="rubric-a",
        rubric_version="1.0",
        source_fixture_ref="fixture-1",
        source_commit="abc123",
        permission_profile="WORKSPACE_WRITE_AND_SHELL_CONTAINED",
        retry_policy={"max_attempts": 2},
        timeout_seconds=300,
        expected_artifacts=["out.txt"],
        capability_key=f"cap-{tag}",
    )
    version = TestVersion(
        logical_test_id=logical.id,
        version_number=1,
        task_prompt="do the thing",
        capability_key=f"cap-{tag}",
        acceptance_criteria="accept",
        rubric_id="rubric-a",
        rubric_version="1.0",
        retry_policy='{"max_attempts": 2}',
        timeout_seconds=300,
        expected_artifacts='["out.txt"]',
        permission_profile="WORKSPACE_WRITE_AND_SHELL_CONTAINED",
        source_fixture_ref="fixture-1",
        source_commit="abc123",
        created_at=_utcnow(),
        registered_at=_utcnow(),
        definition_hash=canonical_definition_hash(payload),
    )
    sess.add(version)
    sess.flush()
    run = Run(
        test_version_id=version.id,
        harness_id=harness.id,
        model_id=model.id,
        capability_id=capability.id,
        methodology_version="m1",
        state="QUEUED",
        requested_at=_utcnow(),
    )
    # state may be passed as enum; string coerces via SAEnum? pass enum explicitly
    from aecc.models import RunState

    run.state = RunState.QUEUED
    sess.add(run)
    sess.flush()
    sess.commit()
    return {
        "harness": harness,
        "model": model,
        "capability": capability,
        "logical": logical,
        "version": version,
        "run": run,
    }


# ---------------------------------------------------------------------------
# 1. Alembic creates schema from empty database
# ---------------------------------------------------------------------------


def test_alembic_creates_schema_from_empty_database(tmp_path):
    db_file = tmp_path / "fresh.sqlite"
    assert not db_file.exists()
    command.upgrade(make_alembic_config(db_file), "head")
    assert db_file.exists()

    import sys

    sys.path.insert(0, str(ROOT / "src"))
    from aecc.db import create_engine_for_path

    eng = create_engine_for_path(db_file)
    try:
        with eng.connect() as conn:
            tables = {
                r[0]
                for r in conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table'")
                ).fetchall()
            }
            triggers = {
                r[0]
                for r in conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='trigger'")
                ).fetchall()
            }
        for expected in [
            "logical_tests",
            "test_versions",
            "harnesses",
            "models",
            "capabilities",
            "runs",
            "attempts",
            "score_revisions",
            "intervention_events",
            "exclusion_events",
            "qualification_decisions",
            "qualification_evidence",
            "audit_events",
            "alembic_version",
        ]:
            assert expected in tables, f"missing table {expected}"
        for trigger in [
            "trg_test_versions_no_update",
            "trg_test_versions_no_delete",
            "trg_attempts_no_update_sealed",
            "trg_attempts_no_delete_sealed",
            "trg_score_revisions_no_update",
            "trg_score_revisions_no_delete",
            "trg_qualification_decisions_no_update",
            "trg_qualification_decisions_no_delete",
            "trg_audit_events_no_update",
            "trg_audit_events_no_delete",
        ]:
            assert trigger in triggers, f"missing trigger {trigger}"
    finally:
        eng.dispose()


# ---------------------------------------------------------------------------
# 2. Foreign keys enforced
# ---------------------------------------------------------------------------


def test_sqlite_foreign_keys_enforced(engine, session):
    with engine.connect() as conn:
        value = conn.execute(text("PRAGMA foreign_keys")).scalar()
    assert int(value) == 1

    from aecc.models import Run

    bad = Run(
        test_version_id=999999,
        harness_id=999999,
        model_id=999999,
        capability_id=999999,
        requested_at=_utcnow(),
    )
    from aecc.models import RunState

    bad.state = RunState.QUEUED
    session.add(bad)
    with pytest.raises(sa.exc.DBAPIError):
        session.commit()
    session.rollback()


# ---------------------------------------------------------------------------
# 3. WAL enabled for file-backed database
# ---------------------------------------------------------------------------


def test_sqlite_wal_enabled_for_file_database(engine, db_file):
    assert db_file.exists()
    with engine.connect() as conn:
        mode = conn.execute(text("PRAGMA journal_mode")).scalar()
    assert str(mode).lower() == "wal"


# ---------------------------------------------------------------------------
# 4/5. Registered test version update/delete rejected at DB level
# ---------------------------------------------------------------------------


def test_registered_test_version_update_rejected(session):
    seed = _seed_identities(session, tag="upd")
    version_id = seed["version"].id
    with pytest.raises(sa.exc.DBAPIError, match="immutable"):
        with session.bind.connect() as conn:
            with conn.begin():
                conn.execute(
                    text("UPDATE test_versions SET task_prompt='mutated' WHERE id=:i"),
                    {"i": version_id},
                )
    session.rollback()
    got = session.execute(
        text("SELECT task_prompt FROM test_versions WHERE id=:i"), {"i": version_id}
    ).scalar()
    assert got == "do the thing"


def test_registered_test_version_update_rejected_via_orm(session):
    from aecc.models import TestVersion

    seed = _seed_identities(session, tag="updorm")
    version = session.get(TestVersion, seed["version"].id)
    assert version is not None
    version.task_prompt = "mutated via ORM"
    with pytest.raises(sa.exc.DBAPIError):
        session.commit()
    session.rollback()


def test_registered_test_version_delete_rejected(session):
    seed = _seed_identities(session, tag="dele")
    version_id = seed["version"].id
    # run references the version; even without the trigger the FK would block,
    # so delete the dependent run first via raw SQL is impossible due to attempts...
    # Instead verify trigger directly on an unreferenced version.
    from aecc.models import LogicalTest, TestVersion

    logical = LogicalTest(key="logical-orphan", name="Orphan")
    session.add(logical)
    session.flush()
    orphan = TestVersion(
        logical_test_id=logical.id,
        version_number=1,
        task_prompt="p",
        capability_key="cap-dele",
        acceptance_criteria="a",
        rubric_id="r",
        rubric_version="1",
        permission_profile="READ_ONLY_NO_SHELL",
        created_at=_utcnow(),
        registered_at=_utcnow(),
        definition_hash="h" * 64,
    )
    session.add(orphan)
    session.commit()
    orphan_id = orphan.id
    session.close()
    with pytest.raises(sa.exc.DBAPIError, match="immutable"):
        with session.bind.connect() as conn:
            with conn.begin():
                conn.execute(text("DELETE FROM test_versions WHERE id=:i"), {"i": orphan_id})
    # original still present
    remaining = session.execute(
        text("SELECT COUNT(*) FROM test_versions WHERE id=:i"), {"i": orphan_id}
    ).scalar()
    assert int(remaining) == 1
    # the referenced version is also protected
    with pytest.raises(sa.exc.DBAPIError):
        with session.bind.connect() as conn:
            with conn.begin():
                conn.execute(text("DELETE FROM test_versions WHERE id=:i"), {"i": version_id})


# ---------------------------------------------------------------------------
# 6. Correction creates a new version, preserves the original
# ---------------------------------------------------------------------------


def test_correction_creates_new_version(session):
    from aecc.models import TestVersion
    from aecc.hashing import build_definition_payload, canonical_definition_hash

    seed = _seed_identities(session, tag="corr")
    v1 = session.get(TestVersion, seed["version"].id)
    assert v1 is not None
    original_hash = v1.definition_hash

    payload2 = build_definition_payload(
        task_prompt="do the thing (clarified)",
        acceptance_criteria="accept",
        rubric_id="rubric-a",
        rubric_version="1.0",
        source_fixture_ref="fixture-1",
        source_commit="abc123",
        permission_profile="WORKSPACE_WRITE_AND_SHELL_CONTAINED",
        retry_policy={"max_attempts": 2},
        timeout_seconds=300,
        expected_artifacts=["out.txt"],
        capability_key=v1.capability_key,
    )
    v2 = TestVersion(
        logical_test_id=v1.logical_test_id,
        version_number=2,
        task_prompt="do the thing (clarified)",
        capability_key=v1.capability_key,
        acceptance_criteria="accept",
        rubric_id="rubric-a",
        rubric_version="1.0",
        retry_policy='{"max_attempts": 2}',
        timeout_seconds=300,
        expected_artifacts='["out.txt"]',
        permission_profile="WORKSPACE_WRITE_AND_SHELL_CONTAINED",
        source_fixture_ref="fixture-1",
        source_commit="abc123",
        created_at=_utcnow(),
        registered_at=_utcnow(),
        definition_hash=canonical_definition_hash(payload2),
        supersedes_version_id=v1.id,
    )
    session.add(v2)
    session.commit()

    v1_again = session.get(TestVersion, v1.id)
    assert v1_again is not None
    assert v1_again.task_prompt == "do the thing"
    assert v1_again.definition_hash == original_hash
    assert v2.supersedes_version_id == v1.id
    assert v2.definition_hash != v1.definition_hash
    count = session.execute(
        text("SELECT COUNT(*) FROM test_versions WHERE logical_test_id=:l"),
        {"l": v1.logical_test_id},
    ).scalar()
    assert int(count) == 2


# ---------------------------------------------------------------------------
# 7. Retries create separate attempts; duplicate attempt numbers rejected
# ---------------------------------------------------------------------------


def test_retry_attempts_preserved(session):
    from aecc.models import Attempt

    seed = _seed_identities(session, tag="retry")
    run_id = seed["run"].id
    a1 = Attempt(run_id=run_id, attempt_number=1, exit_code=1)
    from aecc.models import ProcessOutcome, DeliverableOutcome, TaskOutcome

    a1.process_outcome = ProcessOutcome.FAILURE
    a1.deliverable_outcome = DeliverableOutcome.MISSING
    a1.task_outcome = TaskOutcome.FAILED
    session.add(a1)
    session.commit()
    a2 = Attempt(run_id=run_id, attempt_number=2, exit_code=0)
    a2.process_outcome = ProcessOutcome.SUCCESS
    a2.deliverable_outcome = DeliverableOutcome.PRESENT
    a2.task_outcome = TaskOutcome.SUCCEEDED
    session.add(a2)
    session.commit()

    rows = session.execute(
        text("SELECT attempt_number, exit_code FROM attempts WHERE run_id=:r ORDER BY attempt_number"),
        {"r": run_id},
    ).fetchall()
    assert [(r[0], r[1]) for r in rows] == [(1, 1), (2, 0)]
    # prior attempt untouched by retry
    assert session.get(Attempt, a1.id).exit_code == 1


def test_duplicate_attempt_number_rejected(session):
    from aecc.models import Attempt

    seed = _seed_identities(session, tag="dup")
    run_id = seed["run"].id
    session.add(Attempt(run_id=run_id, attempt_number=1))
    session.commit()
    session.add(Attempt(run_id=run_id, attempt_number=1))
    with pytest.raises(sa.exc.DBAPIError):
        session.commit()
    session.rollback()


# ---------------------------------------------------------------------------
# 8/9. Sealed attempt update/delete rejected
# ---------------------------------------------------------------------------


def _sealed_attempt(session, tag: str):
    from aecc.models import Attempt, ProcessOutcome

    seed = _seed_identities(session, tag=tag)
    attempt = Attempt(run_id=seed["run"].id, attempt_number=1, exit_code=0)
    attempt.process_outcome = ProcessOutcome.SUCCESS
    session.add(attempt)
    session.commit()
    # seal it (allowed: OLD.sealed_at IS NULL)
    attempt.sealed_at = _utcnow()
    session.commit()
    return attempt.id


def test_sealed_attempt_update_rejected(session):
    attempt_id = _sealed_attempt(session, tag="sealupd")
    with pytest.raises(sa.exc.DBAPIError, match="[Ss]ealed"):
        with session.bind.connect() as conn:
            with conn.begin():
                conn.execute(
                    text("UPDATE attempts SET exit_code=99 WHERE id=:i"), {"i": attempt_id}
                )
    session.rollback()
    assert session.execute(
        text("SELECT exit_code FROM attempts WHERE id=:i"), {"i": attempt_id}
    ).scalar() == 0


def test_sealed_attempt_update_rejected_via_orm(session):
    from aecc.models import Attempt

    attempt_id = _sealed_attempt(session, tag="sealorm")
    attempt = session.get(Attempt, attempt_id)
    assert attempt is not None
    attempt.exit_code = 99
    with pytest.raises(sa.exc.DBAPIError):
        session.commit()
    session.rollback()


def test_sealed_attempt_delete_rejected(session):
    attempt_id = _sealed_attempt(session, tag="sealdel")
    with pytest.raises(sa.exc.DBAPIError, match="[Ss]ealed"):
        with session.bind.connect() as conn:
            with conn.begin():
                conn.execute(text("DELETE FROM attempts WHERE id=:i"), {"i": attempt_id})
    session.rollback()
    assert (
        session.execute(text("SELECT COUNT(*) FROM attempts WHERE id=:i"), {"i": attempt_id}).scalar()
        == 1
    )


def test_unsealed_attempt_can_be_updated(session):
    from aecc.models import Attempt

    seed = _seed_identities(session, tag="unsealed")
    attempt = Attempt(run_id=seed["run"].id, attempt_number=1)
    session.add(attempt)
    session.commit()
    attempt.exit_code = 3
    session.commit()
    assert session.get(Attempt, attempt.id).exit_code == 3


# ---------------------------------------------------------------------------
# 10. Score/verdict correction preserves prior revision
# ---------------------------------------------------------------------------


def test_score_revision_history_preserved(session):
    from aecc.models import EvaluatorVerdict, ScoreRevision

    seed = _seed_identities(session, tag="score")
    run_id = seed["run"].id
    rev1 = ScoreRevision(
        run_id=run_id,
        rubric_version="rubric-a/1.0",
        dimension_scores='{"correctness": 0.2}',
        total_score=0.2,
        verdict=EvaluatorVerdict.FAIL,
        notes="first scoring",
        evaluator_identity="eval-1",
        created_at=_utcnow(),
    )
    session.add(rev1)
    session.commit()
    rev2 = ScoreRevision(
        run_id=run_id,
        rubric_version="rubric-a/1.0",
        dimension_scores='{"correctness": 0.4}',
        total_score=0.4,
        verdict=EvaluatorVerdict.NEEDS_REVIEW,
        notes="correction",
        evaluator_identity="eval-1",
        created_at=_utcnow(),
        supersedes_revision_id=rev1.id,
    )
    session.add(rev2)
    session.commit()

    rows = session.execute(
        text("SELECT id, verdict FROM score_revisions WHERE run_id=:r ORDER BY id"),
        {"r": run_id},
    ).fetchall()
    assert len(rows) == 2
    assert rows[0][1] == "FAIL"
    assert rows[1][1] == "NEEDS_REVIEW"

    with pytest.raises(sa.exc.DBAPIError, match="immutable"):
        with session.bind.connect() as conn:
            with conn.begin():
                conn.execute(
                    text("UPDATE score_revisions SET verdict='PASS' WHERE id=:i"),
                    {"i": rev1.id},
                )
    session.rollback()
    with pytest.raises(sa.exc.DBAPIError, match="immutable"):
        with session.bind.connect() as conn:
            with conn.begin():
                conn.execute(text("DELETE FROM score_revisions WHERE id=:i"), {"i": rev1.id})
    session.rollback()
    assert session.get(ScoreRevision, rev1.id).verdict == EvaluatorVerdict.FAIL


# ---------------------------------------------------------------------------
# 11/12. Qualification requires harness+model+capability; history preserved
# ---------------------------------------------------------------------------


def test_qualification_requires_harness_model_capability(session):
    seed = _seed_identities(session, tag="qualreq")
    # NULL harness must fail (NOT NULL constraint)
    with pytest.raises(sa.exc.DBAPIError):
        with session.bind.connect() as conn:
            with conn.begin():
                conn.execute(
                    text(
                        "INSERT INTO qualification_decisions "
                        "(harness_id, model_id, capability_id, state, methodology_version, decided_at, author) "
                        "VALUES (NULL, :m, :c, 'QUALIFIED', 'm1', CURRENT_TIMESTAMP, 'op')"
                    ),
                    {"m": seed["model"].id, "c": seed["capability"].id},
                )
    with pytest.raises(sa.exc.DBAPIError):
        with session.bind.connect() as conn:
            with conn.begin():
                conn.execute(
                    text(
                        "INSERT INTO qualification_decisions "
                        "(harness_id, model_id, capability_id, state, methodology_version, decided_at, author) "
                        "VALUES (:h, NULL, :c, 'QUALIFIED', 'm1', CURRENT_TIMESTAMP, 'op')"
                    ),
                    {"h": seed["harness"].id, "c": seed["capability"].id},
                )
    with pytest.raises(sa.exc.DBAPIError):
        with session.bind.connect() as conn:
            with conn.begin():
                conn.execute(
                    text(
                        "INSERT INTO qualification_decisions "
                        "(harness_id, model_id, capability_id, state, methodology_version, decided_at, author) "
                        "VALUES (:h, :m, NULL, 'QUALIFIED', 'm1', CURRENT_TIMESTAMP, 'op')"
                    ),
                    {"h": seed["harness"].id, "m": seed["model"].id},
                )


def test_qualification_history_preserved(session):
    from aecc.models import QualificationDecision, QualificationEvidence, QualificationState

    seed = _seed_identities(session, tag="qualhist")
    d1 = QualificationDecision(
        harness_id=seed["harness"].id,
        model_id=seed["model"].id,
        capability_id=seed["capability"].id,
        state=QualificationState.SHADOW,
        methodology_version="policy-1",
        decided_at=_utcnow(),
        author="operator-1",
        evidence_summary="initial shadow",
    )
    session.add(d1)
    session.commit()
    session.add(
        QualificationEvidence(qualification_id=d1.id, run_id=seed["run"].id, attempt_id=None)
    )
    session.commit()
    d2 = QualificationDecision(
        harness_id=seed["harness"].id,
        model_id=seed["model"].id,
        capability_id=seed["capability"].id,
        state=QualificationState.QUALIFIED,
        methodology_version="policy-1",
        decided_at=_utcnow(),
        author="operator-1",
        restrictions="none",
        evidence_summary="promotion",
        supersedes_decision_id=d1.id,
    )
    session.add(d2)
    session.commit()

    rows = session.execute(
        text(
            "SELECT id, state FROM qualification_decisions "
            "WHERE harness_id=:h AND model_id=:m AND capability_id=:c ORDER BY id"
        ),
        {"h": seed["harness"].id, "m": seed["model"].id, "c": seed["capability"].id},
    ).fetchall()
    assert [r[1] for r in rows] == ["SHADOW", "QUALIFIED"]
    # current = latest valid decision
    latest = session.execute(
        text(
            "SELECT state FROM qualification_decisions "
            "WHERE harness_id=:h AND model_id=:m AND capability_id=:c ORDER BY id DESC LIMIT 1"
        ),
        {"h": seed["harness"].id, "m": seed["model"].id, "c": seed["capability"].id},
    ).scalar()
    assert latest == "QUALIFIED"
    # history immutable
    with pytest.raises(sa.exc.DBAPIError, match="immutable"):
        with session.bind.connect() as conn:
            with conn.begin():
                conn.execute(
                    text("UPDATE qualification_decisions SET state='UNQUALIFIED' WHERE id=:i"),
                    {"i": d1.id},
                )
    session.rollback()
    with pytest.raises(sa.exc.DBAPIError, match="immutable"):
        with session.bind.connect() as conn:
            with conn.begin():
                conn.execute(
                    text("DELETE FROM qualification_decisions WHERE id=:i"), {"i": d1.id}
                )
    session.rollback()
    # evidence link retained
    assert (
        session.execute(
            text("SELECT COUNT(*) FROM qualification_evidence WHERE qualification_id=:q"),
            {"q": d1.id},
        ).scalar()
        == 1
    )


# ---------------------------------------------------------------------------
# 13. UNKNOWN distinct from PASS
# ---------------------------------------------------------------------------


def test_unknown_distinct_from_pass(session):
    from aecc.models import EvaluatorVerdict, ScoreRevision

    seed = _seed_identities(session, tag="unk")
    run_id = seed["run"].id
    session.add(
        ScoreRevision(
            run_id=run_id,
            rubric_version="r/1",
            verdict=EvaluatorVerdict.UNKNOWN,
            created_at=_utcnow(),
        )
    )
    session.add(
        ScoreRevision(
            run_id=run_id,
            rubric_version="r/1",
            verdict=EvaluatorVerdict.PASS,
            created_at=_utcnow(),
        )
    )
    session.commit()
    assert EvaluatorVerdict.UNKNOWN.value != EvaluatorVerdict.PASS.value
    pass_count = session.execute(
        text("SELECT COUNT(*) FROM score_revisions WHERE run_id=:r AND verdict='PASS'"),
        {"r": run_id},
    ).scalar()
    unknown_count = session.execute(
        text("SELECT COUNT(*) FROM score_revisions WHERE run_id=:r AND verdict='UNKNOWN'"),
        {"r": run_id},
    ).scalar()
    total = session.execute(
        text("SELECT COUNT(*) FROM score_revisions WHERE run_id=:r"), {"r": run_id}
    ).scalar()
    assert int(pass_count) == 1
    assert int(unknown_count) == 1
    assert int(total) == 2
    # pass-rate query must not count UNKNOWN as PASS
    assert int(pass_count) != int(total)


# ---------------------------------------------------------------------------
# 14. Process success can coexist with deliverable/task failure
# ---------------------------------------------------------------------------


def test_process_success_can_coexist_with_task_failure(session):
    from aecc.models import (
        Attempt,
        DeliverableOutcome,
        EvaluatorVerdict,
        ProcessOutcome,
        ScoreRevision,
        TaskOutcome,
    )

    seed = _seed_identities(session, tag="exit0")
    attempt = Attempt(
        run_id=seed["run"].id,
        attempt_number=1,
        exit_code=0,
        sealed_at=_utcnow(),
    )
    attempt.process_outcome = ProcessOutcome.SUCCESS
    attempt.deliverable_outcome = DeliverableOutcome.MISSING
    attempt.task_outcome = TaskOutcome.FAILED
    session.add(attempt)
    session.commit()
    session.add(
        ScoreRevision(
            run_id=seed["run"].id,
            attempt_id=attempt.id,
            rubric_version="r/1",
            verdict=EvaluatorVerdict.FAIL,
            notes="exit 0 but no deliverable",
            created_at=_utcnow(),
        )
    )
    session.commit()

    row = session.execute(
        text(
            "SELECT exit_code, process_outcome, deliverable_outcome, task_outcome "
            "FROM attempts WHERE id=:i"
        ),
        {"i": attempt.id},
    ).fetchone()
    assert tuple(row) == (0, "SUCCESS", "MISSING", "FAILED")
    verdict = session.execute(
        text("SELECT verdict FROM score_revisions WHERE attempt_id=:a"), {"a": attempt.id}
    ).scalar()
    assert verdict == "FAIL"
    # task failure must be visible, not derived from exit code
    assert row[3] != "SUCCEEDED"


# ---------------------------------------------------------------------------
# 15. Intervention and exclusion history retained (excluded evidence present)
# ---------------------------------------------------------------------------


def test_intervention_and_exclusion_history_retained(session):
    from aecc.models import Attempt, ExclusionEvent, InterventionEvent

    seed = _seed_identities(session, tag="excl")
    run_id = seed["run"].id
    attempt = Attempt(run_id=run_id, attempt_number=1, exit_code=1)
    session.add(attempt)
    session.commit()
    session.add(
        InterventionEvent(
            run_id=run_id,
            attempt_id=attempt.id,
            kind="retry_authorization",
            actor="operator-1",
            reason="infra flake, authorized retry",
            created_at=_utcnow(),
        )
    )
    session.add(
        ExclusionEvent(
            run_id=run_id,
            attempt_id=attempt.id,
            reason="broken fixture, excluded from aggregates",
            author="operator-1",
            created_at=_utcnow(),
            methodology_version="m1",
            scope="aggregate-pass-rate",
        )
    )
    session.commit()

    assert (
        session.execute(
            text("SELECT COUNT(*) FROM intervention_events WHERE run_id=:r"), {"r": run_id}
        ).scalar()
        == 1
    )
    assert (
        session.execute(
            text("SELECT COUNT(*) FROM exclusion_events WHERE run_id=:r"), {"r": run_id}
        ).scalar()
        == 1
    )
    # excluded evidence remains present, not deleted
    assert session.get(Attempt, attempt.id) is not None
    assert (
        session.execute(text("SELECT COUNT(*) FROM attempts WHERE id=:i"), {"i": attempt.id}).scalar()
        == 1
    )
    # history immutable
    interv_id = session.execute(
        text("SELECT id FROM intervention_events WHERE run_id=:r"), {"r": run_id}
    ).scalar()
    excl_id = session.execute(
        text("SELECT id FROM exclusion_events WHERE run_id=:r"), {"r": run_id}
    ).scalar()
    with pytest.raises(sa.exc.DBAPIError, match="immutable"):
        with session.bind.connect() as conn:
            with conn.begin():
                conn.execute(
                    text("UPDATE intervention_events SET reason='edited' WHERE id=:i"),
                    {"i": interv_id},
                )
    session.rollback()
    with pytest.raises(sa.exc.DBAPIError, match="immutable"):
        with session.bind.connect() as conn:
            with conn.begin():
                conn.execute(text("DELETE FROM exclusion_events WHERE id=:i"), {"i": excl_id})
    session.rollback()
    assert (
        session.execute(
            text("SELECT COUNT(*) FROM intervention_events WHERE id=:i"), {"i": interv_id}
        ).scalar()
        == 1
    )
    assert (
        session.execute(
            text("SELECT COUNT(*) FROM exclusion_events WHERE id=:i"), {"i": excl_id}
        ).scalar()
        == 1
    )


def test_audit_events_append_only(session):
    from aecc.models import AuditEvent

    seed = _seed_identities(session, tag="audit")
    session.add(
        AuditEvent(
            action="registration",
            actor="operator-1",
            created_at=_utcnow(),
            details="registered v1",
        )
    )
    session.add(
        AuditEvent(
            action="qualification_decision",
            actor="operator-1",
            created_at=_utcnow(),
            run_id=seed["run"].id,
            details="shadow",
        )
    )
    session.commit()
    assert (
        session.execute(text("SELECT COUNT(*) FROM audit_events")).scalar() == 2
    )
    audit_id = session.execute(text("SELECT id FROM audit_events LIMIT 1")).scalar()
    with pytest.raises(sa.exc.DBAPIError, match="immutable"):
        with session.bind.connect() as conn:
            with conn.begin():
                conn.execute(
                    text("UPDATE audit_events SET action='edited' WHERE id=:i"), {"i": audit_id}
                )
    session.rollback()
    with pytest.raises(sa.exc.DBAPIError, match="immutable"):
        with session.bind.connect() as conn:
            with conn.begin():
                conn.execute(text("DELETE FROM audit_events WHERE id=:i"), {"i": audit_id})
    session.rollback()


def test_failure_classification_separate_from_task_outcome(session):
    from aecc.models import (
        Attempt,
        FailureClassification,
        ProcessOutcome,
        TaskOutcome,
    )

    seed = _seed_identities(session, tag="failclass")
    attempt = Attempt(run_id=seed["run"].id, attempt_number=1, exit_code=1)
    attempt.process_outcome = ProcessOutcome.FAILURE
    attempt.task_outcome = TaskOutcome.FAILED
    attempt.failure_primary = FailureClassification.HARNESS_FAILURE
    attempt.failure_secondary = FailureClassification.UNKNOWN
    session.add(attempt)
    session.commit()
    row = session.execute(
        text("SELECT task_outcome, failure_primary, failure_secondary FROM attempts WHERE id=:i"),
        {"i": attempt.id},
    ).fetchone()
    assert tuple(row) == ("FAILED", "HARNESS_FAILURE", "UNKNOWN")
