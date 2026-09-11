"""Demo-data lifecycle with explicit structural provenance.

Demo rows are marked is_demo=True at insertion. All queries can distinguish
demo from user data via that column, not by key/name heuristics. Demo evidence
is labeled in UI and excluded from real qualification evidence unless
explicitly requested.

Provides a safe operator action to remove demo data only, never user-created
data, and never reseeds automatically after removal.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aecc.models import (
    AuditEvent,
    Attempt,
    Capability,
    ExclusionEvent,
    Harness,
    InterventionEvent,
    LogicalTest,
    Model,
    QualificationDecision,
    QualificationEvidence,
    Run,
    ScoreRevision,
    TestVersion,
)

# Tables in deletion order respecting FKs (child -> parent). Audit events and
# qualification evidence both reference qualification decisions, so they must
# be removed *before* the decisions; score/intervention/exclusion events
# reference attempts, so they precede attempts.
_DEMO_ORDER = [
    QualificationEvidence,
    AuditEvent,
    QualificationDecision,
    ScoreRevision,
    InterventionEvent,
    ExclusionEvent,
    Attempt,
    Run,
    TestVersion,
    LogicalTest,
    Harness,
    Model,
    Capability,
]

# For counting demo presence quickly
_DEMO_TABLES = _DEMO_ORDER


def has_demo_data(session: Session) -> bool:
    for cls in _DEMO_TABLES:
        cnt = session.scalar(select(cls.id).where(cls.is_demo == True).limit(1))  # noqa: E712
        if cnt is not None:
            return True
    return False


def count_demo_rows(session: Session) -> dict[str, int]:
    from sqlalchemy import func as _func

    out: dict[str, int] = {}
    for cls in _DEMO_TABLES:
        cnt = session.scalar(select(_func.count(cls.id)).where(cls.is_demo == True))  # noqa: E712
        out[cls.__tablename__] = int(cnt or 0)
    return out


def seed_demo_data(session: Session) -> dict:
    """Insert demo rows with structural provenance (is_demo=1) at insertion time.

    Provenance is set on INSERT by the seeder itself; it is never inferred or
    back-filled by UPDATE (immutable tables would reject that anyway).

    Idempotent: if demo data already exists this is a no-op, and a concurrent
    duplicate seed that loses the unique-key race is treated as already seeded
    rather than surfacing a spurious error or relabeling existing rows.
    """
    from aecc.seed_dashboard import seed_dashboard_data

    if has_demo_data(session):
        return {"already_seeded": True}
    try:
        return seed_dashboard_data(session, is_demo=True)
    except IntegrityError:
        session.rollback()
        if has_demo_data(session):
            return {"already_seeded": True}
        raise



class DemoDataReferencedError(RuntimeError):
    """Raised when non-demo evidence references demo rows, so demo removal
    would orphan real evidence. Nothing is deleted in that case."""


def clear_demo_data(session: Session) -> dict[str, int]:
    """Remove only demo rows (is_demo=1). Never deletes user data.

    Order is child -> parent so FK RESTRICT is respected. If a non-demo row
    still references a demo row, the whole operation is rolled back and
    DemoDataReferencedError is raised: user evidence is never touched and
    demo rows are never partially removed.
    Returns counts per table.
    """
    counts: dict[str, int] = {}
    from sqlalchemy import func as _func
    from sqlalchemy.exc import IntegrityError

    # Order already is child->parent; for self-referential tables delete descending id
    self_ref_tables = {TestVersion, ScoreRevision, QualificationDecision}
    try:
        for cls in _DEMO_ORDER:
            before = session.scalar(select(_func.count(cls.id)).where(cls.is_demo == True))  # noqa: E712
            if not before:
                counts[cls.__tablename__] = 0
                continue
            if cls in self_ref_tables:
                # iterative delete newest first
                ids = session.scalars(select(cls.id).where(cls.is_demo == True).order_by(cls.id.desc())).all()  # noqa: E712
                for _id in ids:
                    session.execute(delete(cls).where(cls.id == _id))
                    session.flush()
            else:
                session.execute(delete(cls).where(cls.is_demo == True))  # noqa: E712
                session.flush()
            counts[cls.__tablename__] = int(before or 0)
        session.commit()
    except IntegrityError as e:
        session.rollback()
        raise DemoDataReferencedError(
            "demo data is referenced by non-demo evidence; refusing to delete anything. "
            "Remove or re-point the referencing rows first."
        ) from e
    return counts
