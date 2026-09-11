"""Registry Foundation: capability hierarchy + model registry metadata.

Revision ID: 0002_registry_foundation
Revises: 0001_foundation
Create Date: 2026-09-11

Adds non-destructive, additive columns to preserve existing records:

- capabilities: parent_id (self-FK), display_name, is_active, updated_at
- models: display_name, pricing_tier, price_input, price_output, is_active,
          harness_config, description, updated_at

Existing rows receive is_active=1 and pricing_tier derived from pricing_class.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "0002_registry_foundation"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ----- capabilities -----
    op.add_column("capabilities", sa.Column("parent_id", sa.Integer(), nullable=True))
    op.add_column("capabilities", sa.Column("display_name", sa.String(500), nullable=True))
    op.add_column(
        "capabilities",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
    )
    op.add_column("capabilities", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))

    # SQLite does not support adding FK via add_column directly with FK constraint in all versions
    # via batch mode. Use a standalone FK via create_foreign_key.
    # parent_id -> capabilities.id ON DELETE SET NULL
    try:
        op.create_foreign_key(
            "fk_capabilities_parent_id",
            "capabilities",
            "capabilities",
            ["parent_id"],
            ["id"],
            ondelete="SET NULL",
        )
    except Exception:
        pass
    try:
        op.create_index("ix_capabilities_parent_id", "capabilities", ["parent_id"])
    except Exception:
        pass
    try:
        op.create_index("ix_capabilities_is_active", "capabilities", ["is_active"])
    except Exception:
        pass

    # ----- models -----
    op.add_column("models", sa.Column("display_name", sa.String(500), nullable=True))
    op.add_column("models", sa.Column("pricing_tier", sa.String(20), nullable=True))
    op.add_column("models", sa.Column("price_input", sa.Float(), nullable=True))
    op.add_column("models", sa.Column("price_output", sa.Float(), nullable=True))
    op.add_column(
        "models",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
    )
    op.add_column("models", sa.Column("harness_config", sa.Text(), nullable=True))
    op.add_column("models", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("models", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))

    try:
        op.create_index("ix_models_is_active", "models", ["is_active"])
    except Exception:
        pass
    try:
        op.create_index("ix_models_pricing_tier", "models", ["pricing_tier"])
    except Exception:
        pass

    # Backfill: is_active already defaulted via server_default, but ensure existing NULLs become 1
    op.execute(sa.text("UPDATE capabilities SET is_active=1 WHERE is_active IS NULL"))
    op.execute(sa.text("UPDATE models SET is_active=1 WHERE is_active IS NULL"))
    # Derive pricing_tier from legacy pricing_class when possible
    op.execute(
        sa.text(
            "UPDATE models SET pricing_tier = CASE "
            "WHEN lower(pricing_class)='free' THEN 'free' "
            "WHEN lower(pricing_class)='paid' THEN 'paid' "
            "WHEN pricing_class IS NULL THEN 'unknown' "
            "ELSE 'unknown' END "
            "WHERE pricing_tier IS NULL"
        )
    )
    # Ensure any remaining NULL becomes unknown
    op.execute(sa.text("UPDATE models SET pricing_tier='unknown' WHERE pricing_tier IS NULL"))

    # Add CHECK for pricing_tier values (SQLite enforces via check constraint)
    # Use batch mode to avoid recreating tables where possible; instead create a trigger-based check?
    # Simpler: add a CHECK via raw SQL that validates on insert/update using trigger.
    # For portability, add a trigger that aborts on invalid pricing_tier.
    op.execute(
        sa.text(
            "CREATE TRIGGER IF NOT EXISTS trg_models_pricing_tier_check "
            "BEFORE INSERT ON models "
            "WHEN NEW.pricing_tier IS NOT NULL AND NEW.pricing_tier NOT IN ('free','paid','unknown') "
            "BEGIN SELECT RAISE(ABORT, 'invalid pricing_tier: must be free/paid/unknown'); END"
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER IF NOT EXISTS trg_models_pricing_tier_check_upd "
            "BEFORE UPDATE ON models "
            "WHEN NEW.pricing_tier IS NOT NULL AND NEW.pricing_tier NOT IN ('free','paid','unknown') "
            "BEGIN SELECT RAISE(ABORT, 'invalid pricing_tier: must be free/paid/unknown'); END"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_models_pricing_tier_check_upd"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_models_pricing_tier_check"))
    try:
        op.drop_index("ix_models_pricing_tier", table_name="models")
    except Exception:
        pass
    try:
        op.drop_index("ix_models_is_active", table_name="models")
    except Exception:
        pass
    op.drop_column("models", "updated_at")
    op.drop_column("models", "description")
    op.drop_column("models", "harness_config")
    op.drop_column("models", "is_active")
    op.drop_column("models", "price_output")
    op.drop_column("models", "price_input")
    op.drop_column("models", "pricing_tier")
    op.drop_column("models", "display_name")

    try:
        op.drop_index("ix_capabilities_is_active", table_name="capabilities")
    except Exception:
        pass
    try:
        op.drop_index("ix_capabilities_parent_id", table_name="capabilities")
    except Exception:
        pass
    try:
        op.drop_constraint("fk_capabilities_parent_id", "capabilities", type_="foreignkey")
    except Exception:
        pass
    op.drop_column("capabilities", "updated_at")
    op.drop_column("capabilities", "is_active")
    op.drop_column("capabilities", "display_name")
    op.drop_column("capabilities", "parent_id")
