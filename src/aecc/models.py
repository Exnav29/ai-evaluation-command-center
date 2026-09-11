"""SQLAlchemy 2.x domain model for the private Operator evidence foundation.

Concepts (see docs/ARCHITECTURE_BASELINE_V1.md section 6):
  logical tests + immutable registered test versions, harness identity,
  model identity, capability identity/version, runs, attempts,
  score/verdict revisions, intervention events, exclusion events,
  qualification decisions, audit events.

Evidence-integrity rules enforced at the database level (SQLite triggers
created in the Alembic migration, see alembic/versions/0001_foundation.py):
  * registered test versions: no UPDATE, no DELETE;
  * sealed attempts (sealed_at IS NOT NULL): no UPDATE, no DELETE;
  * score revisions, intervention events, exclusion events, qualification
    decisions, qualification evidence, audit events: append-only
    (no UPDATE, no DELETE).

Process outcome, deliverable outcome, task outcome, and evaluator verdict
are separate columns. UNKNOWN is a distinct enum value in every axis and
is never coerced to PASS.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text as sa_text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Enumerations (each axis keeps UNKNOWN distinct; verdict keeps PASS distinct)
# ---------------------------------------------------------------------------


class ProcessOutcome(str, enum.Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


class DeliverableOutcome(str, enum.Enum):
    PRESENT = "PRESENT"
    MISSING = "MISSING"
    NOT_CHECKED = "NOT_CHECKED"
    UNKNOWN = "UNKNOWN"


class TaskOutcome(str, enum.Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    NOT_EVALUATED = "NOT_EVALUATED"
    UNKNOWN = "UNKNOWN"


class EvaluatorVerdict(str, enum.Enum):
    PASS = "PASS"
    PASS_WITH_FINDINGS = "PASS_WITH_FINDINGS"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    FAIL = "FAIL"
    INFRASTRUCTURE_FAILURE = "INFRASTRUCTURE_FAILURE"
    EXCLUDED = "EXCLUDED"
    UNKNOWN = "UNKNOWN"


class FailureClassification(str, enum.Enum):
    MODEL_FAILURE = "MODEL_FAILURE"
    HARNESS_FAILURE = "HARNESS_FAILURE"
    INFRASTRUCTURE_FAILURE = "INFRASTRUCTURE_FAILURE"
    TASK_FAILURE = "TASK_FAILURE"
    PERMISSION_POLICY_FAILURE = "PERMISSION_POLICY_FAILURE"
    MIXED = "MIXED"
    UNKNOWN = "UNKNOWN"


class QualificationState(str, enum.Enum):
    UNQUALIFIED = "UNQUALIFIED"
    SHADOW = "SHADOW"
    QUALIFIED = "QUALIFIED"
    RESTRICTED = "RESTRICTED"
    NOT_AUTHORIZED = "NOT_AUTHORIZED"


class RunState(str, enum.Enum):
    QUEUED = "QUEUED"
    CLAIMED = "CLAIMED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    SCORING = "SCORING"
    FINALIZED = "FINALIZED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    INFRASTRUCTURE_FAILURE = "INFRASTRUCTURE_FAILURE"
    EXCLUDED = "EXCLUDED"


class RepoModificationOutcome(str, enum.Enum):
    MODIFIED = "MODIFIED"
    UNMODIFIED = "UNMODIFIED"
    NOT_CHECKED = "NOT_CHECKED"
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# Identity tables
# ---------------------------------------------------------------------------


class LogicalTest(Base):
    """A logical test that may have multiple registered versions (drafts evolve)."""

    __tablename__ = "logical_tests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    versions: Mapped[list["TestVersion"]] = relationship(back_populates="logical_test")


class Harness(Base):
    """Harness identity: stable key plus exact version/build/config identity."""

    __tablename__ = "harnesses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    harness_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    build: Mapped[str | None] = mapped_column(String(255), nullable=True)
    config_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    config_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)


class Model(Base):
    """Model identity: provider plus exact executed provider/model identifier."""

    __tablename__ = "models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(255), nullable=False)
    exact_identifier: Mapped[str] = mapped_column(String(500), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    pricing_class: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pricing_tier: Mapped[str | None] = mapped_column(String(20), nullable=True)  # free/paid/unknown
    price_input: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_output: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=sa_text("1"))
    harness_config: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON snapshot of supported harnesses/config
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    config_params: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON snapshot


class Capability(Base):
    """Versionable evaluation dimension (e.g. bug fixing, refactoring)."""

    __tablename__ = "capabilities"
    __table_args__ = (UniqueConstraint("capability_key", "version", name="uq_capability_key_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    capability_key: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("capabilities.id", ondelete="SET NULL"), nullable=True
    )
    display_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    definition: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=sa_text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    parent: Mapped["Capability | None"] = relationship(
        "Capability", remote_side="Capability.id", backref="children", foreign_keys="[Capability.parent_id]"
    )


# ---------------------------------------------------------------------------
# Registered test versions (append-only, DB-immutable)
# ---------------------------------------------------------------------------


class TestVersion(Base):
    """One frozen, registered evaluation definition. Never updated/deleted."""

    __tablename__ = "test_versions"
    __table_args__ = (
        UniqueConstraint("logical_test_id", "version_number", name="uq_test_version_number"),
        Index("ix_test_versions_logical_test", "logical_test_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    logical_test_id: Mapped[int] = mapped_column(
        ForeignKey("logical_tests.id", ondelete="RESTRICT"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    task_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    capability_key: Mapped[str] = mapped_column(String(255), nullable=False)
    acceptance_criteria: Mapped[str] = mapped_column(Text, nullable=False)
    rubric_id: Mapped[str] = mapped_column(String(255), nullable=False)
    rubric_version: Mapped[str] = mapped_column(String(64), nullable=False)
    retry_policy: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON snapshot
    timeout_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expected_artifacts: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON snapshot
    permission_profile: Mapped[str] = mapped_column(String(255), nullable=False)
    source_fixture_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_commit: Mapped[str | None] = mapped_column(String(255), nullable=True)
    harness_policy: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_policy: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    definition_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    supersedes_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("test_versions.id", ondelete="RESTRICT"), nullable=True
    )

    logical_test: Mapped[LogicalTest] = relationship(back_populates="versions")


# ---------------------------------------------------------------------------
# Runs and attempts
# ---------------------------------------------------------------------------


class Run(Base):
    """Logical assignment of one registered test version to harness+model+capability."""

    __tablename__ = "runs"
    __table_args__ = (
        Index("ix_runs_test_version", "test_version_id"),
        Index("ix_runs_harness_model_capability", "harness_id", "model_id", "capability_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    test_version_id: Mapped[int] = mapped_column(
        ForeignKey("test_versions.id", ondelete="RESTRICT"), nullable=False
    )
    harness_id: Mapped[int] = mapped_column(
        ForeignKey("harnesses.id", ondelete="RESTRICT"), nullable=False
    )
    model_id: Mapped[int] = mapped_column(
        ForeignKey("models.id", ondelete="RESTRICT"), nullable=False
    )
    capability_id: Mapped[int] = mapped_column(
        ForeignKey("capabilities.id", ondelete="RESTRICT"), nullable=False
    )
    source_commit: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_fixture: Mapped[str | None] = mapped_column(String(500), nullable=True)
    evaluator_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    methodology_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    permission_profile: Mapped[str | None] = mapped_column(String(255), nullable=True)
    state: Mapped[RunState] = mapped_column(
        SAEnum(RunState, native_enum=False, create_constraint=True, length=32),
        nullable=False,
        default=RunState.QUEUED,
    )
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    attempts: Mapped[list["Attempt"]] = relationship(back_populates="run", cascade="save-update")


class Attempt(Base):
    """One actual invocation for a run. Retries are new rows. Sealing freezes evidence."""

    __tablename__ = "attempts"
    __table_args__ = (
        UniqueConstraint("run_id", "attempt_number", name="uq_attempt_run_number"),
        Index("ix_attempts_run", "run_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="RESTRICT"), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    elapsed_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    time_to_first_output_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Separate outcome axes — never collapsed into one boolean.
    process_outcome: Mapped[ProcessOutcome | None] = mapped_column(
        SAEnum(ProcessOutcome, native_enum=False, create_constraint=True, length=16),
        nullable=True,
    )
    deliverable_outcome: Mapped[DeliverableOutcome | None] = mapped_column(
        SAEnum(DeliverableOutcome, native_enum=False, create_constraint=True, length=16),
        nullable=True,
    )
    task_outcome: Mapped[TaskOutcome | None] = mapped_column(
        SAEnum(TaskOutcome, native_enum=False, create_constraint=True, length=16),
        nullable=True,
    )
    repo_modification_outcome: Mapped[RepoModificationOutcome | None] = mapped_column(
        SAEnum(RepoModificationOutcome, native_enum=False, create_constraint=True, length=16),
        nullable=True,
    )

    permission_denied: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    permission_denial_evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    timed_out: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    cancelled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    tokens_input: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_output: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost: Mapped[float | None] = mapped_column(Float, nullable=True)  # NULL/UNKNOWN, never $0 by default
    cost_source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_response_meta: Mapped[str | None] = mapped_column(Text, nullable=True)

    human_intervention: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    frontier_escalation: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    failure_primary: Mapped[FailureClassification | None] = mapped_column(
        SAEnum(FailureClassification, native_enum=False, create_constraint=True, length=32),
        nullable=True,
    )
    failure_secondary: Mapped[FailureClassification | None] = mapped_column(
        SAEnum(FailureClassification, native_enum=False, create_constraint=True, length=32),
        nullable=True,
    )

    raw_evidence_location: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    artifact_refs: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON snapshot
    invocation_meta: Mapped[str | None] = mapped_column(Text, nullable=True)  # command/metadata snapshot

    sealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    run: Mapped[Run] = relationship(back_populates="attempts")


# ---------------------------------------------------------------------------
# Scores / verdicts (append-only revisions)
# ---------------------------------------------------------------------------


class ScoreRevision(Base):
    """One scoring of a run (optionally scoped to an attempt). Corrections append."""

    __tablename__ = "score_revisions"
    __table_args__ = (
        Index("ix_score_revisions_run", "run_id"),
        Index("ix_score_revisions_attempt", "attempt_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="RESTRICT"), nullable=False)
    attempt_id: Mapped[int | None] = mapped_column(
        ForeignKey("attempts.id", ondelete="RESTRICT"), nullable=True
    )
    rubric_version: Mapped[str] = mapped_column(String(64), nullable=False)
    dimension_scores: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON snapshot
    total_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    verdict: Mapped[EvaluatorVerdict] = mapped_column(
        SAEnum(EvaluatorVerdict, native_enum=False, create_constraint=True, length=32),
        nullable=False,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    evaluator_identity: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    supersedes_revision_id: Mapped[int | None] = mapped_column(
        ForeignKey("score_revisions.id", ondelete="RESTRICT"), nullable=True
    )


# ---------------------------------------------------------------------------
# Intervention / exclusion events (append-only)
# ---------------------------------------------------------------------------


class InterventionEvent(Base):
    __tablename__ = "intervention_events"
    __table_args__ = (Index("ix_interventions_run", "run_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="RESTRICT"), nullable=False)
    attempt_id: Mapped[int | None] = mapped_column(
        ForeignKey("attempts.id", ondelete="RESTRICT"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(255), nullable=False)
    actor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class ExclusionEvent(Base):
    """An exclusion is not a deletion: the target evidence stays queryable."""

    __tablename__ = "exclusion_events"
    __table_args__ = (Index("ix_exclusions_run", "run_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="RESTRICT"), nullable=False)
    attempt_id: Mapped[int | None] = mapped_column(
        ForeignKey("attempts.id", ondelete="RESTRICT"), nullable=True
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    methodology_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scope: Mapped[str | None] = mapped_column(String(255), nullable=True)


# ---------------------------------------------------------------------------
# Qualification (keyed by harness + model + capability, append-only history)
# ---------------------------------------------------------------------------


class QualificationDecision(Base):
    __tablename__ = "qualification_decisions"
    __table_args__ = (
        Index("ix_qual_harness_model_capability", "harness_id", "model_id", "capability_id"),
        CheckConstraint(
            "harness_id IS NOT NULL AND model_id IS NOT NULL AND capability_id IS NOT NULL",
            name="ck_qualification_triple_key",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    harness_id: Mapped[int] = mapped_column(
        ForeignKey("harnesses.id", ondelete="RESTRICT"), nullable=False
    )
    model_id: Mapped[int] = mapped_column(
        ForeignKey("models.id", ondelete="RESTRICT"), nullable=False
    )
    capability_id: Mapped[int] = mapped_column(
        ForeignKey("capabilities.id", ondelete="RESTRICT"), nullable=False
    )
    state: Mapped[QualificationState] = mapped_column(
        SAEnum(QualificationState, native_enum=False, create_constraint=True, length=16),
        nullable=False,
    )
    methodology_version: Mapped[str] = mapped_column(String(64), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    author: Mapped[str] = mapped_column(String(255), nullable=False)
    restrictions: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    supersedes_decision_id: Mapped[int | None] = mapped_column(
        ForeignKey("qualification_decisions.id", ondelete="RESTRICT"), nullable=True
    )

    evidence_links: Mapped[list["QualificationEvidence"]] = relationship(
        back_populates="qualification", cascade="save-update"
    )


class QualificationEvidence(Base):
    """Drill-through links from a qualification decision to supporting evidence."""

    __tablename__ = "qualification_evidence"
    __table_args__ = (
        Index("ix_qual_evidence_qual", "qualification_id"),
        CheckConstraint(
            "run_id IS NOT NULL OR attempt_id IS NOT NULL",
            name="ck_qual_evidence_target",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    qualification_id: Mapped[int] = mapped_column(
        ForeignKey("qualification_decisions.id", ondelete="RESTRICT"), nullable=False
    )
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("runs.id", ondelete="RESTRICT"), nullable=True
    )
    attempt_id: Mapped[int | None] = mapped_column(
        ForeignKey("attempts.id", ondelete="RESTRICT"), nullable=True
    )

    qualification: Mapped[QualificationDecision] = relationship(back_populates="evidence_links")


# ---------------------------------------------------------------------------
# Audit events (append-only consequential-action history)
# ---------------------------------------------------------------------------


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_action", "action"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    actor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("runs.id", ondelete="RESTRICT"), nullable=True
    )
    attempt_id: Mapped[int | None] = mapped_column(
        ForeignKey("attempts.id", ondelete="RESTRICT"), nullable=True
    )
    qualification_id: Mapped[int | None] = mapped_column(
        ForeignKey("qualification_decisions.id", ondelete="RESTRICT"), nullable=True
    )
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
