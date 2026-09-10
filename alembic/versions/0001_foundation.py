"""V1 evidence foundation: immutable test versions, runs/attempts, scores, events, qualification.

Revision ID: 0001_foundation
Revises:
Create Date: 2026-09-10
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "0001_foundation"
down_revision = None
branch_labels = None
depends_on = None


IMMUTABLE_TABLES = (
    "test_versions",
    "score_revisions",
    "intervention_events",
    "exclusion_events",
    "qualification_decisions",
    "qualification_evidence",
    "audit_events",
)


def _immutability_triggers() -> list[str]:
    statements = []
    for table in IMMUTABLE_TABLES:
        statements.append(
            f"CREATE TRIGGER trg_{table}_no_update "
            f"BEFORE UPDATE ON {table} "
            f"BEGIN SELECT RAISE(ABORT, '{table} is immutable: UPDATE is not allowed'); END"
        )
        statements.append(
            f"CREATE TRIGGER trg_{table}_no_delete "
            f"BEFORE DELETE ON {table} "
            f"BEGIN SELECT RAISE(ABORT, '{table} is immutable: DELETE is not allowed'); END"
        )
    statements.append(
        "CREATE TRIGGER trg_attempts_no_update_sealed "
        "BEFORE UPDATE ON attempts WHEN OLD.sealed_at IS NOT NULL "
        "BEGIN SELECT RAISE(ABORT, 'sealed attempt evidence is immutable: UPDATE is not allowed'); END"
    )
    statements.append(
        "CREATE TRIGGER trg_attempts_no_delete_sealed "
        "BEFORE DELETE ON attempts WHEN OLD.sealed_at IS NOT NULL "
        "BEGIN SELECT RAISE(ABORT, 'sealed attempt evidence is immutable: DELETE is not allowed'); END"
    )
    return statements


def upgrade() -> None:
    # Enums are imported lazily so the migration reflects the same value sets
    # as the application models without duplicating literal lists.
    from aecc.models import (  # noqa: PLC0415
        DeliverableOutcome,
        EvaluatorVerdict,
        FailureClassification,
        ProcessOutcome,
        QualificationState,
        RepoModificationOutcome,
        RunState,
        TaskOutcome,
    )

    op.create_table(
        "logical_tests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("key", sa.String(255), nullable=False, unique=True),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "harnesses",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("harness_key", sa.String(255), nullable=False, unique=True),
        sa.Column("display_name", sa.String(500), nullable=True),
        sa.Column("version", sa.String(255), nullable=True),
        sa.Column("build", sa.String(255), nullable=True),
        sa.Column("config_snapshot", sa.Text(), nullable=True),
        sa.Column("config_hash", sa.String(128), nullable=True),
    )

    op.create_table(
        "models",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("model_key", sa.String(255), nullable=False, unique=True),
        sa.Column("provider", sa.String(255), nullable=False),
        sa.Column("exact_identifier", sa.String(500), nullable=False),
        sa.Column("pricing_class", sa.String(255), nullable=True),
        sa.Column("config_params", sa.Text(), nullable=True),
    )

    op.create_table(
        "capabilities",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("capability_key", sa.String(255), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("definition", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("capability_key", "version", name="uq_capability_key_version"),
    )

    op.create_table(
        "test_versions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("logical_test_id", sa.Integer(), sa.ForeignKey("logical_tests.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("task_prompt", sa.Text(), nullable=False),
        sa.Column("capability_key", sa.String(255), nullable=False),
        sa.Column("acceptance_criteria", sa.Text(), nullable=False),
        sa.Column("rubric_id", sa.String(255), nullable=False),
        sa.Column("rubric_version", sa.String(64), nullable=False),
        sa.Column("retry_policy", sa.Text(), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=True),
        sa.Column("expected_artifacts", sa.Text(), nullable=True),
        sa.Column("permission_profile", sa.String(255), nullable=False),
        sa.Column("source_fixture_ref", sa.String(500), nullable=True),
        sa.Column("source_commit", sa.String(255), nullable=True),
        sa.Column("harness_policy", sa.Text(), nullable=True),
        sa.Column("model_policy", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("definition_hash", sa.String(128), nullable=False),
        sa.Column("supersedes_version_id", sa.Integer(), sa.ForeignKey("test_versions.id", ondelete="RESTRICT"), nullable=True),
        sa.UniqueConstraint("logical_test_id", "version_number", name="uq_test_version_number"),
    )
    op.create_index("ix_test_versions_logical_test", "test_versions", ["logical_test_id"])

    op.create_table(
        "runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("test_version_id", sa.Integer(), sa.ForeignKey("test_versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("harness_id", sa.Integer(), sa.ForeignKey("harnesses.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("model_id", sa.Integer(), sa.ForeignKey("models.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("capability_id", sa.Integer(), sa.ForeignKey("capabilities.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_commit", sa.String(255), nullable=True),
        sa.Column("source_fixture", sa.String(500), nullable=True),
        sa.Column("evaluator_version", sa.String(64), nullable=True),
        sa.Column("methodology_version", sa.String(64), nullable=True),
        sa.Column("permission_profile", sa.String(255), nullable=True),
        sa.Column("state", sa.Enum(RunState, native_enum=False, create_constraint=True, length=32), nullable=False, server_default="QUEUED"),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_runs_test_version", "runs", ["test_version_id"])
    op.create_index("ix_runs_harness_model_capability", "runs", ["harness_id", "model_id", "capability_id"])

    op.create_table(
        "attempts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("runs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("elapsed_seconds", sa.Float(), nullable=True),
        sa.Column("time_to_first_output_seconds", sa.Float(), nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("process_outcome", sa.Enum(ProcessOutcome, native_enum=False, create_constraint=True, length=16), nullable=True),
        sa.Column("deliverable_outcome", sa.Enum(DeliverableOutcome, native_enum=False, create_constraint=True, length=16), nullable=True),
        sa.Column("task_outcome", sa.Enum(TaskOutcome, native_enum=False, create_constraint=True, length=16), nullable=True),
        sa.Column("repo_modification_outcome", sa.Enum(RepoModificationOutcome, native_enum=False, create_constraint=True, length=16), nullable=True),
        sa.Column("permission_denied", sa.Boolean(), nullable=True),
        sa.Column("permission_denial_evidence", sa.Text(), nullable=True),
        sa.Column("timed_out", sa.Boolean(), nullable=True),
        sa.Column("cancelled", sa.Boolean(), nullable=True),
        sa.Column("tokens_input", sa.Integer(), nullable=True),
        sa.Column("tokens_output", sa.Integer(), nullable=True),
        sa.Column("cost", sa.Float(), nullable=True),
        sa.Column("cost_source", sa.String(255), nullable=True),
        sa.Column("provider_response_meta", sa.Text(), nullable=True),
        sa.Column("human_intervention", sa.Boolean(), nullable=True),
        sa.Column("frontier_escalation", sa.Boolean(), nullable=True),
        sa.Column("failure_primary", sa.Enum(FailureClassification, native_enum=False, create_constraint=True, length=32), nullable=True),
        sa.Column("failure_secondary", sa.Enum(FailureClassification, native_enum=False, create_constraint=True, length=32), nullable=True),
        sa.Column("raw_evidence_location", sa.String(1024), nullable=True),
        sa.Column("artifact_refs", sa.Text(), nullable=True),
        sa.Column("invocation_meta", sa.Text(), nullable=True),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("run_id", "attempt_number", name="uq_attempt_run_number"),
    )
    op.create_index("ix_attempts_run", "attempts", ["run_id"])

    op.create_table(
        "score_revisions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("runs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("attempt_id", sa.Integer(), sa.ForeignKey("attempts.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("rubric_version", sa.String(64), nullable=False),
        sa.Column("dimension_scores", sa.Text(), nullable=True),
        sa.Column("total_score", sa.Float(), nullable=True),
        sa.Column("verdict", sa.Enum(EvaluatorVerdict, native_enum=False, create_constraint=True, length=32), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("evaluator_identity", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("supersedes_revision_id", sa.Integer(), sa.ForeignKey("score_revisions.id", ondelete="RESTRICT"), nullable=True),
    )
    op.create_index("ix_score_revisions_run", "score_revisions", ["run_id"])
    op.create_index("ix_score_revisions_attempt", "score_revisions", ["attempt_id"])

    op.create_table(
        "intervention_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("runs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("attempt_id", sa.Integer(), sa.ForeignKey("attempts.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("kind", sa.String(255), nullable=False),
        sa.Column("actor", sa.String(255), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_interventions_run", "intervention_events", ["run_id"])

    op.create_table(
        "exclusion_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("runs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("attempt_id", sa.Integer(), sa.ForeignKey("attempts.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("author", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("methodology_version", sa.String(64), nullable=True),
        sa.Column("scope", sa.String(255), nullable=True),
    )
    op.create_index("ix_exclusions_run", "exclusion_events", ["run_id"])

    op.create_table(
        "qualification_decisions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("harness_id", sa.Integer(), sa.ForeignKey("harnesses.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("model_id", sa.Integer(), sa.ForeignKey("models.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("capability_id", sa.Integer(), sa.ForeignKey("capabilities.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("state", sa.Enum(QualificationState, native_enum=False, create_constraint=True, length=16), nullable=False),
        sa.Column("methodology_version", sa.String(64), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("author", sa.String(255), nullable=False),
        sa.Column("restrictions", sa.Text(), nullable=True),
        sa.Column("evidence_summary", sa.Text(), nullable=True),
        sa.Column("supersedes_decision_id", sa.Integer(), sa.ForeignKey("qualification_decisions.id", ondelete="RESTRICT"), nullable=True),
        sa.CheckConstraint(
            "harness_id IS NOT NULL AND model_id IS NOT NULL AND capability_id IS NOT NULL",
            name="ck_qualification_triple_key",
        ),
    )
    op.create_index(
        "ix_qual_harness_model_capability",
        "qualification_decisions",
        ["harness_id", "model_id", "capability_id"],
    )

    op.create_table(
        "qualification_evidence",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("qualification_id", sa.Integer(), sa.ForeignKey("qualification_decisions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("runs.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("attempt_id", sa.Integer(), sa.ForeignKey("attempts.id", ondelete="RESTRICT"), nullable=True),
        sa.CheckConstraint("run_id IS NOT NULL OR attempt_id IS NOT NULL", name="ck_qual_evidence_target"),
    )
    op.create_index("ix_qual_evidence_qual", "qualification_evidence", ["qualification_id"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("action", sa.String(255), nullable=False),
        sa.Column("actor", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("runs.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("attempt_id", sa.Integer(), sa.ForeignKey("attempts.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("qualification_id", sa.Integer(), sa.ForeignKey("qualification_decisions.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
    )
    op.create_index("ix_audit_events_action", "audit_events", ["action"])

    for statement in _immutability_triggers():
        op.execute(sa.text(statement))


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_attempts_no_delete_sealed"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_attempts_no_update_sealed"))
    for table in IMMUTABLE_TABLES:
        op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{table}_no_delete"))
        op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{table}_no_update"))

    op.drop_index("ix_audit_events_action", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_qual_evidence_qual", table_name="qualification_evidence")
    op.drop_table("qualification_evidence")
    op.drop_index("ix_qual_harness_model_capability", table_name="qualification_decisions")
    op.drop_table("qualification_decisions")
    op.drop_index("ix_exclusions_run", table_name="exclusion_events")
    op.drop_table("exclusion_events")
    op.drop_index("ix_interventions_run", table_name="intervention_events")
    op.drop_table("intervention_events")
    op.drop_index("ix_score_revisions_attempt", table_name="score_revisions")
    op.drop_index("ix_score_revisions_run", table_name="score_revisions")
    op.drop_table("score_revisions")
    op.drop_index("ix_attempts_run", table_name="attempts")
    op.drop_table("attempts")
    op.drop_index("ix_runs_harness_model_capability", table_name="runs")
    op.drop_index("ix_runs_test_version", table_name="runs")
    op.drop_table("runs")
    op.drop_index("ix_test_versions_logical_test", table_name="test_versions")
    op.drop_table("test_versions")
    op.drop_table("capabilities")
    op.drop_table("models")
    op.drop_table("harnesses")
    op.drop_table("logical_tests")
