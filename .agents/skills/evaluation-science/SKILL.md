---
name: evaluation-science
description: Design fair, repeatable AI model and coding-harness evaluations with preregistered criteria, preserved failures, comparable runs, and defensible conclusions. Use when creating, running, scoring, comparing, or reporting evaluation tests.
---

# Evaluation Science

The purpose of evaluation is discovery, not proving a preferred conclusion.

## Before a test runs

Record before seeing the result:

- test ID
- task definition
- task category
- source state or fixture
- harness
- exact model identifier
- permissions
- acceptance criteria
- scoring rubric version
- retry policy
- expected artifacts
- timeout or execution limits

Do not change acceptance criteria after seeing a model's result.

## Fair comparisons

When comparing models or harnesses:

- use equivalent instructions;
- use equivalent source state;
- use equivalent permissions and tools unless the difference itself is under test;
- distinguish model failures from harness failures;
- distinguish infrastructure failures from task failures;
- record all retries;
- record human interventions;
- preserve unsuccessful runs.

Do not quietly rerun a model until it succeeds.

If retries are allowed, define the retry policy before execution.

## Scoring

Separate:

1. objective acceptance checks;
2. evaluator judgments;
3. observed facts;
4. interpretation;
5. conclusion.

Useful scoring dimensions include:

- correctness;
- instruction compliance;
- scope discipline;
- code quality;
- testing discipline;
- security awareness;
- tool selection;
- human intervention required;
- completion time;
- cost;
- escalation required.

Do not allow one high score to conceal a disqualifying failure.

## Outcomes

Use explicit states such as:

- PASS
- PASS WITH FINDINGS
- NEEDS REVIEW
- FAIL
- INFRASTRUCTURE FAILURE
- EXCLUDED
- UNKNOWN

UNKNOWN is never PASS.

An EXCLUDED run remains part of the historical ledger and must include a documented exclusion reason.

## Evidence integrity

Preserve:

- original test definition;
- original output;
- logs;
- diffs;
- test output;
- evaluator notes;
- retry history;
- scoring version;
- model and harness identifiers.

Historical evidence must never be rewritten to improve later conclusions.

Corrections must be additive and auditable.

## Reporting

Always report:

- sample size;
- methodology version;
- important limitations;
- failures as well as successes;
- human intervention;
- exclusions;
- uncertainty where evidence is incomplete.

Do not generalize from a small sample without stating that limitation.

## Model versus harness

Treat model performance and harness performance as separate variables.

A model may perform differently across harnesses.

A harness may perform differently across models.

Do not attribute a result to one when the evidence only establishes the combined result.

## Benchmark integrity

The evaluated system must not:

- choose which failed results are published;
- change its own scoring criteria after execution;
- remove unfavorable runs;
- silently alter fixtures;
- overwrite historical evidence.

The evaluation system should make cherry-picking difficult by design.
