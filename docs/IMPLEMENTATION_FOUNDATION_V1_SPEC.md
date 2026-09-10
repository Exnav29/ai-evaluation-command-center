# Evaluation Command Center — Implementation Foundation Benchmark V1

**Version:** 1.0
**Status:** Pre-registered benchmark specification
**Capability under test:** Backend/database engineering

## 1. Purpose

Implement the first vertical slice of AI Evaluation Command Center V1: the private database/evidence foundation.

This benchmark tests whether a coding model, operating through a coding-agent harness, can turn the approved architecture into a correct, migration-backed, automatically tested evidence ledger.

This benchmark intentionally does **not** include the web UI, queue worker, execution sandbox, publication pipeline, charts, authentication, or deployment services.

## 2. Governing architecture

The implementation must follow `docs/ARCHITECTURE_BASELINE_V1.md`.

For purposes of this benchmark, that document is the human-approved architecture contract despite its draft-status header at the freeze point. The benchmark must not weaken its evidence-integrity rules.

## 3. Required stack

Use:

- Python;
- SQLAlchemy 2.x;
- Alembic;
- SQLite;
- pytest.

Create a conventional Python project configuration (`pyproject.toml`) with the dependencies required to run the implementation and tests.

Do not add FastAPI routes, frontend code, Redis, a worker, container orchestration, or unrelated infrastructure.

## 4. Required domain foundation

The implementation must represent, at minimum, these concepts:

1. logical tests and immutable registered test versions;
2. harness identities;
3. model identities;
4. capability identities/versions;
5. evaluation runs;
6. execution attempts;
7. score/verdict revisions;
8. intervention events;
9. exclusion events;
10. qualification decisions;
11. audit events or equivalent consequential-action history.

Exact table/class names are not prescribed.

## 5. Registered test versions

A registered test version must preserve the frozen evaluation definition, including enough structured data or immutable references to recover:

- logical test identity;
- version identity;
- task/prompt;
- capability;
- acceptance criteria;
- rubric identity/version;
- retry policy;
- timeout;
- expected artifacts;
- permission profile;
- source/fixture reference;
- creation/registration timestamps;
- deterministic definition hash;
- optional relationship to a superseded prior version.

Registered versions are append-only.

Database-level enforcement is required. A normal SQLite `CHECK` constraint is not sufficient. Attempts to `UPDATE` or `DELETE` a registered version must fail at the database level, for example through SQLite triggers using `RAISE(ABORT, ...)`.

A correction creates a new version rather than rewriting the old one.

## 6. Harness, model, and capability identity

A run must bind all three dimensions explicitly.

### Harness
Preserve a stable harness key plus exact version/build or configuration identity where represented.

### Model
Preserve provider plus exact provider/model identifier. Configuration that can materially change behavior should have a place to be recorded.

### Capability
Preserve a stable capability key and a definition/version identity.

Aliases must not erase the exact executed model or harness identity.

## 7. Runs and attempts

A **run** is the logical assignment of one registered test version to one harness/model/capability combination.

An **attempt** is one actual invocation for that run.

Retries must create additional attempts. They must not overwrite the prior attempt.

The database must prevent duplicate attempt numbers within one run.

Attempts must have space to record, where measurable:

- attempt number;
- start/finish timestamps;
- elapsed time;
- time to first process output;
- process exit code;
- process outcome;
- deliverable outcome;
- task outcome;
- repository-modification outcome;
- permission-denial evidence;
- timeout/cancellation;
- token usage/cost;
- human intervention;
- frontier escalation;
- failure classification;
- raw evidence/artifact references;
- seal timestamp.

The schema may normalize these fields further if useful.

## 8. Separate outcome axes

Do not collapse execution into a single success boolean.

At minimum preserve separate values equivalent to:

### Process outcome
- SUCCESS
- FAILURE
- TIMEOUT
- CANCELLED
- UNKNOWN

### Deliverable outcome
- PRESENT
- MISSING
- NOT_CHECKED
- UNKNOWN

### Task outcome
- SUCCEEDED
- FAILED
- NEEDS_REVIEW
- NOT_EVALUATED
- UNKNOWN

### Evaluator verdict
- PASS
- PASS_WITH_FINDINGS
- NEEDS_REVIEW
- FAIL
- INFRASTRUCTURE_FAILURE
- EXCLUDED
- UNKNOWN

The model must support this valid case:

- process exit code = `0`;
- process outcome = SUCCESS;
- deliverable outcome = MISSING;
- task outcome = FAILED;
- evaluator verdict = FAIL.

`UNKNOWN` must never be treated as PASS.

## 9. Failure classification

The evidence model must support at least:

- MODEL_FAILURE;
- HARNESS_FAILURE;
- INFRASTRUCTURE_FAILURE;
- TASK_FAILURE;
- PERMISSION_POLICY_FAILURE;
- MIXED;
- UNKNOWN.

Failure attribution is separate from task outcome.

## 10. Sealed attempt evidence

An attempt may be updated while evidence is being collected.

Once `sealed_at` (or an equivalent finalization marker) is set, material attempt evidence must not be silently updated or deleted.

Database-level enforcement is required.

Corrections after sealing must be additive/auditable rather than destructive rewriting.

## 11. Append-only revisions and events

Score/verdict revisions must be append-only and capable of linking a correction to a superseded revision.

Intervention, exclusion, and qualification-decision history must remain historically recoverable.

Database-level immutability should protect these historical rows after insertion.

## 12. Qualification

Qualification identity is exactly:

**harness + model + capability**

A qualification decision must bind all three dimensions and preserve:

- state;
- methodology/policy version;
- decision timestamp;
- decision author/actor;
- restrictions/conditions if any;
- evidence runs/attempts supporting the decision;
- prior decision relationship when superseding an earlier decision.

States include:

- UNQUALIFIED;
- SHADOW;
- QUALIFIED;
- RESTRICTED;
- NOT_AUTHORIZED.

The schema must make it impossible to represent a qualification decision that omits harness, model, or capability.

Qualification history is append-only. Current qualification is derived from history rather than destructive replacement.

## 13. SQLite behavior

The database setup/migration must enable and test:

- foreign-key enforcement;
- WAL mode for a file-backed SQLite database;
- uniqueness/integrity constraints required by the model;
- the immutability triggers required above.

Use Alembic for the initial schema migration. The schema must be creatable from an empty database through Alembic rather than relying only on `metadata.create_all()`.

## 14. Automated tests

Provide pytest tests that create isolated temporary databases and prove the important invariants.

At minimum tests must demonstrate:

1. Alembic can create the schema from an empty database;
2. foreign keys are enforced;
3. WAL is enabled for a file-backed database;
4. a registered test version cannot be updated;
5. a registered test version cannot be deleted;
6. a correction/new version preserves the original;
7. retries create separate attempts and duplicate attempt numbers are rejected;
8. a sealed attempt cannot be materially updated;
9. a sealed attempt cannot be deleted;
10. score/verdict correction preserves the prior revision;
11. qualification requires harness + model + capability;
12. qualification history preserves prior decisions;
13. UNKNOWN is distinct from PASS;
14. process success can coexist with deliverable/task failure;
15. exclusion/intervention history is retained.

Tests must run from the repository root with:

`python -m pytest -q`

## 15. Scope constraints

Do not implement:

- web pages or HTTP routes;
- evaluation queue/worker execution;
- model invocation;
- Podman/container containment;
- network egress controls;
- Stakeholder/Public projection databases;
- charts;
- authentication;
- systemd units;
- Product Studio integration.

Do not modify `~/work/product-studio-ops` or any external directory.

Do not rewrite the benchmark specification, rubric, prompt, or validator to make the implementation pass.

## 16. Deliverable

The deliverable is working repository code, migrations, and tests.

At completion, provide a concise report containing:

- what was implemented;
- important files added/changed;
- test command and result;
- any unresolved issue or assumption.

The report is secondary evidence. The repository changes and independent verification determine success.
