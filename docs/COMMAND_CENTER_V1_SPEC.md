# Evaluation Command Center V1
Version: 1.0
Status: Pre-registered specification

## 1. Purpose

Build a web-based Evaluation Command Center for independently evaluating AI coding harnesses and models through real engineering tasks.

The initial research focus is whether OpenCode plus free models can perform enough useful engineering work to reduce or replace dependence on Codex, Claude Code, and frontier models.

The product must preserve failures as well as successes and must make cherry-picking difficult.

This is a real product intended for human use, not an internal developer demo.

## 2. Primary questions the product must answer

A user should be able to determine:

1. Which model performs best overall?
2. Which model performs best for a specific task category?
3. Which harness performs best?
4. Which model/harness combination performs best?
5. Which models fail most often?
6. Where is human intervention required?
7. How long do models take?
8. What does free-model use save?
9. How often is a frontier model required?
10. Which capabilities have earned qualification?
11. What evidence supports a qualification decision?
12. How have results changed over time?

## 3. Three access planes

### 3.1 Operator

Authenticated control plane.

The Operator may:

- create evaluation tests;
- define task category;
- specify acceptance criteria;
- select one or more models;
- select harness;
- choose an execution permission profile;
- submit tests for execution;
- view queued, running and completed jobs;
- cancel eligible queued/running jobs;
- inspect full private evidence;
- inspect prompts and model responses;
- inspect test output and artifacts;
- enter evaluator scores and notes;
- manage qualification decisions;
- control stakeholder/public publication.

Only the Operator plane may initiate execution.

### 3.2 Stakeholder

Read-only evidence plane.

The Stakeholder may see:

- sanitized individual run results;
- model and harness identifiers;
- evaluation scores;
- task categories;
- test methodology;
- comparisons;
- timing;
- cost;
- intervention and retry information;
- failure reasons;
- qualification evidence;
- sanitized artifacts;
- charts;
- underlying tables/data.

The Stakeholder must never:

- launch evaluations;
- change test definitions;
- change scores;
- alter evidence;
- obtain credentials or secrets;
- gain shell or server execution authority.

### 3.3 Public

Internet-facing transparency/research plane.

The Public view should communicate findings visually and clearly.

It may include:

- methodology;
- total registered tests;
- total completed tests;
- pass/fail/review/exclusion totals;
- model comparisons;
- harness comparisons;
- charts;
- historical trends;
- qualification summaries;
- public datasets;
- documented limitations;
- documented exclusions;
- aggregate findings.

It must not include:

- sensitive/private prompts;
- credentials;
- environment variables;
- internal server reconnaissance;
- unrestricted shell output;
- private repository content;
- execution controls;
- unsanitized artifacts.

## 4. Publication boundary

Information flows outward only:

Operator -> Stakeholder -> Public

Publication must be explicit and sanitized.

Neither Stakeholder nor Public input may directly trigger:

- shell execution;
- model execution;
- job execution;
- repository changes;
- server changes.

## 5. Evaluation workflow

The basic lifecycle is:

DRAFT
  ->
REGISTERED
  ->
QUEUED
  ->
RUNNING
  ->
COMPLETED
  ->
SCORING
  ->
FINALIZED
  ->
OPTIONALLY PUBLISHED

Additional states may include:

- CANCELLED
- INFRASTRUCTURE_FAILURE
- NEEDS_REVIEW
- EXCLUDED

Once REGISTERED, the original test definition must remain historically recoverable.

Changes require a new version rather than silent rewriting.

## 6. Test definition

Before execution, a test should support recording:

- unique test ID;
- name;
- description;
- task category;
- exact task/prompt;
- harness;
- model or model set;
- source/fixture state;
- permission profile;
- acceptance criteria;
- rubric version;
- retry policy;
- timeout;
- expected artifacts;
- creation timestamp.

## 7. Run evidence

Each run should record where measurable:

- run ID;
- test ID;
- harness;
- exact model identifier;
- model provider;
- run mode;
- status;
- started timestamp;
- finished timestamp;
- wall-clock duration;
- time to first useful output if measurable;
- exit code;
- retry number;
- human intervention;
- frontier escalation;
- token usage if available;
- cost if available;
- artifact references;
- failure category;
- notes.

Raw evidence must remain private by default.

## 8. Scoring

Support both objective acceptance checks and evaluator scoring.

Useful dimensions include:

- correctness;
- instruction compliance;
- scope discipline;
- code quality;
- testing discipline;
- security awareness;
- tool-selection judgment;
- product quality;
- human intervention;
- overall verdict.

Verdict states include:

- PASS
- PASS WITH FINDINGS
- NEEDS REVIEW
- FAIL
- INFRASTRUCTURE FAILURE
- EXCLUDED
- UNKNOWN

UNKNOWN must never be treated as PASS.

## 9. Qualification

Qualification is capability-specific.

States:

- UNQUALIFIED
- SHADOW
- QUALIFIED
- RESTRICTED
- NOT AUTHORIZED

Examples of capabilities:

- repository exploration;
- documentation;
- frontend development;
- backend development;
- test generation;
- bug fixing;
- refactoring;
- shell diagnostics;
- architecture planning;
- security review;
- production operations.

Qualification must be evidence-based and should show the runs supporting the decision.

## 10. Required Operator pages

At minimum:

### Overview
Visual status of the evaluation program.

### New Evaluation
Form for registering and submitting tests.

### Run Queue
Queued/running/completed execution jobs.

### Results Explorer
Search/filter/drill into individual runs.

### Compare
Side-by-side model and harness comparison.

### Qualification Board
Capability-specific qualification state and evidence.

### Methodology
Current methodology and rubric versions.

## 11. Required Stakeholder experience

Read-only, sanitized views for:

- overview;
- individual runs;
- comparisons;
- methodology;
- qualification evidence;
- underlying data.

No execution controls.

## 12. Required Public experience

The public site should be polished enough to function as an independent research project.

It should prominently communicate:

- what is being tested;
- why;
- that successes and failures are both retained;
- methodology;
- sample size;
- limitations.

It should emphasize visuals over walls of text.

## 13. Required visualizations

At minimum provide designs for:

- pass/fail outcome distribution;
- pass rate by model;
- pass rate by harness;
- model x capability heatmap;
- performance over time;
- duration by model;
- human-intervention rate;
- failure categories;
- free versus frontier utilization;
- frontier escalation rate;
- quality versus duration;
- quality versus cost where cost exists;
- qualification progression.

Every important visualization must expose underlying tabular values.

Do not use misleading axes or visual exaggeration.

## 14. Comparison experience

A user should be able to select multiple runs or models and compare:

- verdict;
- score;
- task;
- harness;
- duration;
- cost;
- retries;
- human intervention;
- failure reason;
- qualification impact.

The same test run across multiple models should be especially easy to compare.

## 15. Human-centered design

The primary Operator is not expected to inspect raw database records for routine use.

The UI should make important conditions visually obvious.

The product must include intentional:

- loading states;
- empty states;
- error states;
- unavailable/UNKNOWN states;
- success states;
- permission-denied states.

Responsive behavior is required.

Accessibility should target WCAG 2.2 AA behavior.

Do not rely on color alone for status.

## 16. Security

Assume browser/user input is untrusted.

Requirements:

- server-side authorization;
- explicit role separation;
- no arbitrary browser input passed directly to shell;
- no public execution endpoint;
- secrets outside source control;
- explicit sanitization for publication;
- safe working-directory boundaries;
- audit trail for consequential actions;
- fail closed when authorization is unknown.

## 17. Evidence integrity

The system must preserve:

- failed runs;
- retries;
- exclusions;
- human assistance;
- model changes;
- harness changes;
- rubric versions;
- original registered test definitions.

Historical records must not be silently rewritten.

Corrections should be additive and auditable.

## 18. Architecture constraints

For V1:

- run on the existing VPS;
- live entirely inside ~/work/opencode-eval during development;
- do not modify Product Studio;
- do not alter existing Codex or Claude installations;
- SQLite may be used initially;
- prefer a maintainable monolith over unnecessary distributed services;
- minimize operational complexity;
- keep execution worker separate from browser-facing request handling;
- retain an upgrade path to Postgres if justified later.

The implementation stack is NOT prescribed.

The engineer should recommend an appropriate stack and explain the tradeoffs before implementation.

## 19. V1 boundaries

V1 does NOT require:

- production access to Product Studio;
- autonomous production server changes;
- replacing Codex;
- replacing Claude Code;
- multi-tenant SaaS;
- billing;
- external customer accounts;
- mobile applications.

## 20. Definition of success

V1 succeeds when an Operator can:

1. register a test;
2. choose multiple models;
3. submit evaluation jobs;
4. see job status;
5. inspect results;
6. record/see scores;
7. compare models visually;
8. inspect underlying data;
9. see qualification status;
10. view a sanitized Stakeholder representation;
11. view a safe Public representation;
12. verify that execution controls exist only in the Operator plane.

The system must demonstrate these behaviors with fresh verification evidence before being described as complete.
