"""Execution worker + demo provenance.

Revision ID: 0004_execution_and_demo
Revises: 0003_test_registry_capability_version
Create Date: 2026-09-11

- Adds explicit structural demo provenance (is_demo) to all domain tables
  (not name-based). Defaults to false for historical/user rows.
- Adds idempotency_key to runs for duplicate-submit prevention.
- Recreates immutability triggers to allow deletion of demo rows (is_demo=1)
  while preserving protection for user rows and sealed attempts.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "0004_execution_and_demo"
down_revision = "0003_test_registry_capability_version"
branch_labels = None
depends_on = None

TABLES_WITH_DEMO = [
    "logical_tests",
    "harnesses",
    "models",
    "capabilities",
    "test_versions",
    "runs",
    "attempts",
    "score_revisions",
    "intervention_events",
    "exclusion_events",
    "qualification_decisions",
    "qualification_evidence",
    "audit_events",
]


def upgrade() -> None:
    for table in TABLES_WITH_DEMO:
        try:
            op.add_column(table, sa.Column("is_demo", sa.Boolean(), server_default=sa.text("0"), nullable=False))
        except Exception:
            pass
        # ensure existing rows are not demo
        try:
            op.execute(sa.text(f"UPDATE {table} SET is_demo=0 WHERE is_demo IS NULL"))
        except Exception:
            pass
    # idempotency_key for runs
    try:
        op.add_column("runs", sa.Column("idempotency_key", sa.String(64), nullable=True))
        op.create_index("ix_runs_idempotency_key", "runs", ["idempotency_key"], unique=True)
    except Exception:
        pass

    # --- recreate immutability triggers to allow demo deletion ---
    # Drop existing triggers first (if any)
    old_triggers = [
        "trg_test_versions_no_update", "trg_test_versions_no_delete",
        "trg_score_revisions_no_update", "trg_score_revisions_no_delete",
        "trg_intervention_events_no_update", "trg_intervention_events_no_delete",
        "trg_exclusion_events_no_update", "trg_exclusion_events_no_delete",
        "trg_qualification_decisions_no_update", "trg_qualification_decisions_no_delete",
        "trg_qualification_evidence_no_update", "trg_qualification_evidence_no_delete",
        "trg_audit_events_no_update", "trg_audit_events_no_delete",
        "trg_attempts_no_update_sealed", "trg_attempts_no_delete_sealed",
    ]
    for trg in old_triggers:
        try:
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS {trg}"))
        except Exception:
            pass

    # Helper to create conditional triggers
    # Demo rows (is_demo=1) can be updated/deleted; user rows cannot.
    immutable_tables = [
        "test_versions",
        "score_revisions",
        "intervention_events",
        "exclusion_events",
        "qualification_decisions",
        "qualification_evidence",
        "audit_events",
    ]
    for table in immutable_tables:
        op.execute(sa.text(
            f"CREATE TRIGGER trg_{table}_no_update "
            f"BEFORE UPDATE ON {table} "
            f"WHEN OLD.is_demo IS NULL OR OLD.is_demo = 0 "
            f"BEGIN SELECT RAISE(ABORT, '{table} is immutable: UPDATE is not allowed'); END"
        ))
        op.execute(sa.text(
            f"CREATE TRIGGER trg_{table}_no_delete "
            f"BEFORE DELETE ON {table} "
            f"WHEN OLD.is_demo IS NULL OR OLD.is_demo = 0 "
            f"BEGIN SELECT RAISE(ABORT, '{table} is immutable: DELETE is not allowed'); END"
        ))

    # Sealed attempts: allow mutation/deletion only if is_demo=1; otherwise blocked when sealed
    op.execute(sa.text(
        "CREATE TRIGGER trg_attempts_no_update_sealed "
        "BEFORE UPDATE ON attempts "
        "WHEN OLD.sealed_at IS NOT NULL AND (OLD.is_demo IS NULL OR OLD.is_demo = 0) "
        "BEGIN SELECT RAISE(ABORT, 'sealed attempt evidence is immutable: UPDATE is not allowed'); END"
    ))
    op.execute(sa.text(
        "CREATE TRIGGER trg_attempts_no_delete_sealed "
        "BEFORE DELETE ON attempts "
        "WHEN OLD.sealed_at IS NOT NULL AND (OLD.is_demo IS NULL OR OLD.is_demo = 0) "
        "BEGIN SELECT RAISE(ABORT, 'sealed attempt evidence is immutable: DELETE is not allowed'); END"
    ))
    # Also protect non-demo attempts deletion before sealing? Only sealed? keep simple.


def downgrade() -> None:
    # Drop conditional triggers
    for table in ["test_versions","score_revisions","intervention_events","exclusion_events","qualification_decisions","qualification_evidence","audit_events"]:
        try:
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{table}_no_update"))
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{table}_no_delete"))
        except Exception:
            pass
    try:
        op.execute(sa.text("DROP TRIGGER IF EXISTS trg_attempts_no_update_sealed"))
        op.execute(sa.text("DROP TRIGGER IF EXISTS trg_attempts_no_delete_sealed"))
    except Exception:
        pass

    # Recreate original unconditional triggers
    immutable_tables = [
        "test_versions","score_revisions","intervention_events","exclusion_events","qualification_decisions","qualification_evidence","audit_events"
    ]
    for table in immutable_tables:
        op.execute(sa.text(
            f"CREATE TRIGGER trg_{table}_no_update "
            f"BEFORE UPDATE ON {table} "
            f"BEGIN SELECT RAISE(ABORT, '{table} is immutable: UPDATE is not allowed'); END"
        ))
        op.execute(sa.text(
            f"CREATE TRIGGER trg_{table}_no_delete "
            f"BEFORE DELETE ON {table} "
            f"BEGIN SELECT RAISE(ABORT, '{table} is immutable: DELETE is not allowed'); END"
        ))
    op.execute(sa.text(
        "CREATE TRIGGER trg_attempts_no_update_sealed "
        "BEFORE UPDATE ON attempts WHEN OLD.sealed_at IS NOT NULL "
        "BEGIN SELECT RAISE(ABORT, 'sealed attempt evidence is immutable: UPDATE is not allowed'); END"
    ))
    op.execute(sa.text(
        "CREATE TRIGGER trg_attempts_no_delete_sealed "
        "BEFORE DELETE ON attempts WHEN OLD.sealed_at IS NOT NULL "
        "BEGIN SELECT RAISE(ABORT, 'sealed attempt evidence is immutable: DELETE is not allowed'); END"
    ))

    try:
        op.drop_index("ix_runs_idempotency_key", table_name="runs")
    except Exception:
        pass
    try:
        op.drop_column("runs", "idempotency_key")
    except Exception:
        pass
    for table in TABLES_WITH_DEMO:
        try:
            op.drop_column(table, "is_demo")
        except Exception:
            pass
