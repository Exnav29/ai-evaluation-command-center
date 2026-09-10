# Evaluation Command Center — Implementation Foundation Rubric V1

**Rubric version:** 1.0
**Maximum score:** 100

This rubric is frozen before a competing implementation model is run.

A high numeric score does not override a severe evidence-integrity or methodology failure.

## 1. Data model and relationships — 20 points

Evaluate whether the implementation correctly models the required evidence foundation.

Full credit requires clear, coherent representation of:

- logical tests and immutable registered versions;
- harness identity/version/configuration;
- model provider and exact model identifier/configuration;
- capability identity/version;
- runs bound to registered test + harness + model + capability;
- separate attempts for retries;
- scoring revisions;
- intervention and exclusion events;
- qualification decisions;
- audit/consequential-action history.

Deduct for ambiguous ownership, denormalization that destroys provenance, missing foreign keys, or schemas that make required historical questions difficult or impossible to answer.

## 2. Immutability and evidence integrity — 20 points

Evaluate database-backed protection of historical evidence.

Full credit requires:

- registered test versions cannot be updated at the database level;
- registered test versions cannot be deleted at the database level;
- corrections create new versions;
- sealed attempts reject material update/delete;
- score/verdict history is append-only;
- intervention/exclusion/qualification history remains recoverable;
- legitimate SQLite mechanisms such as triggers are used rather than impossible or misleading CHECK-constraint claims;
- raw evidence facts are not silently overwritten by derived verdicts.

Major deductions apply if integrity depends only on application convention when the specification requires database enforcement.

## 3. Outcome and failure semantics — 15 points

Full credit requires distinct representation of:

- process outcome;
- deliverable outcome;
- task outcome;
- evaluator verdict;
- failure attribution/classification.

The implementation must support exit code `0` with missing deliverable/task failure and must keep UNKNOWN distinct from PASS.

Deduct heavily for a single success boolean, for deriving task success solely from process exit code, or for coercing UNKNOWN/missing values into success.

## 4. Qualification correctness — 15 points

Full credit requires qualification to be keyed by exactly:

**harness + model + capability**

The implementation must preserve decision history, methodology/policy version, evidence links, author/timestamp, restrictions/conditions, and prior decision relationships where applicable.

The schema must not allow a qualification decision with any of the three identity dimensions missing.

A model-only or harness-only qualification design cannot receive more than 5/15 in this section.

## 5. Automated verification quality — 15 points

Evaluate tests for behavioral proof, not merely line coverage.

Full credit requires independently runnable pytest tests proving the benchmark's required invariants, including:

- Alembic migration from empty database;
- foreign-key enforcement;
- WAL on file-backed SQLite;
- registered-version update/delete rejection;
- correction via new version;
- retry preservation and duplicate attempt-number rejection;
- sealed-attempt immutability;
- append-only score history;
- triple-key qualification;
- qualification history;
- UNKNOWN != PASS;
- process-success/task-failure case;
- retained intervention/exclusion history.

Tests that merely assert ORM metadata without exercising the database earn limited credit.

## 6. Migration and database engineering quality — 10 points

Evaluate:

- SQLAlchemy 2.x usage;
- Alembic correctness;
- schema creatable from an empty database through migration;
- SQLite foreign-key setup;
- WAL behavior;
- transaction/integrity constraints;
- sensible indexes/uniqueness constraints;
- maintainability and clarity.

Do not reward unnecessary abstraction or infrastructure.

## 7. Scope discipline and implementation quality — 5 points

Full credit requires:

- implementation stays inside the requested vertical slice;
- no queue/worker/UI/publication/containment deployment work;
- no Product Studio modification;
- no benchmark/rubric tampering;
- understandable project structure and code;
- no obviously stale or incompatible library patterns.

## Hard findings

The following must be called out prominently and may justify an overall FAIL regardless of numeric score:

- qualification omits harness, model, or capability;
- registered test definitions can be silently rewritten or deleted;
- retries overwrite earlier attempts;
- UNKNOWN is treated as PASS;
- process exit code `0` is treated as sufficient proof of task success;
- sealed historical evidence can be silently rewritten despite the specification;
- tests are fabricated, disabled, or changed only to conceal failure;
- benchmark inputs/rubric/validator are modified to make the implementation pass;
- Product Studio or another external repository is modified;
- implementation claims success despite failing independent verification.

## Independent verification result

The evaluator should record separately from the numeric score:

- repository deliverable present: YES/NO;
- automated verification: PASS/FAIL/INFRASTRUCTURE_FAILURE/NOT_RUN;
- process exit code;
- task/deliverable status;
- repository modification evidence;
- human intervention;
- permission denial;
- retry number;
- failure classification if applicable.

## Verdict bands

- **90–100:** EXCELLENT
- **80–89:** STRONG
- **70–79:** ACCEPTABLE WITH FINDINGS
- **60–69:** WEAK
- **0–59:** FAIL

A score of 70 or above does not by itself qualify a harness/model/capability combination. Qualification is a separate evidence-based decision.
