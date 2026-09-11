"""Guard is_demo provenance against relabeling.

Revision ID: 0005_provenance_relabel_guard
Revises: 0004_execution_and_demo
Create Date: 2026-09-11

Demo provenance is structural (is_demo) and must be immutable for a given row.
Without this guard, the conditional immutability triggers from 0004 (which
allow UPDATE/DELETE of demo rows) would let a demo row be flipped to is_demo=0
and thereby laundered into real evidence. These triggers abort any UPDATE that
changes is_demo in either direction on any domain table.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "0005_provenance_relabel_guard"
down_revision = "0004_execution_and_demo"
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
        op.execute(sa.text(
            f"CREATE TRIGGER trg_{table}_no_relabel "
            f"BEFORE UPDATE OF is_demo ON {table} "
            f"WHEN OLD.is_demo IS NOT NEW.is_demo "
            f"BEGIN SELECT RAISE(ABORT, '{table} is_demo provenance is immutable: relabeling is not allowed'); END"
        ))


def downgrade() -> None:
    for table in TABLES_WITH_DEMO:
        try:
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{table}_no_relabel"))
        except Exception:
            pass
