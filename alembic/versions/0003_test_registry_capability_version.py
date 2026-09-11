"""Test Registry: preserve exact capability version per TestVersion.

Revision ID: 0003_test_registry_capability_version
Revises: 0002_registry_foundation
Create Date: 2026-09-11

Adds capability_version to test_versions to preserve the exact
capability key+version pair selected at registration. The column is
nullable to keep existing historical rows intact with UNKNOWN (NULL)
when no deterministic evidence exists. New registrations must supply an
exact active capability id and therefore a version. Definition hashes
for new registrations include capability_version so two otherwise
identical definitions against different capability versions cannot
collide. Existing historical definition hashes are not rewritten.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "0003_test_registry_capability_version"
down_revision = "0002_registry_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("test_versions", sa.Column("capability_version", sa.String(64), nullable=True))
    # Evidence-integrity: do NOT infer capability_version for historical rows.
    # Historical TestVersion records created before this column existed do not
    # contain enough evidence to determine the exact capability version when
    # multiple versions of the same key exist. UNKNOWN must remain UNKNOWN
    # (NULL). New registrations will require and preserve exact version.
    try:
        op.create_index("ix_test_versions_capability", "test_versions", ["capability_key", "capability_version"])
    except Exception:
        pass


def downgrade() -> None:
    try:
        op.drop_index("ix_test_versions_capability", table_name="test_versions")
    except Exception:
        pass
    op.drop_column("test_versions", "capability_version")
