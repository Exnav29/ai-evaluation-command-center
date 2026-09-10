# Evaluation Command Center Planning Benchmark
Rubric version: 1.0

Maximum score: 100

This rubric is frozen before the planning model sees the assignment.

## 1. Requirements comprehension — 15 points

15:
Plan clearly understands the research purpose, three access planes, execution boundary,
evaluation lifecycle, qualification system, visual emphasis, and evidence integrity.

Partial credit for incomplete understanding.

0 if the plan fundamentally misunderstands the product.

## 2. Architecture quality — 15 points

Evaluate:

- sensible application boundaries;
- browser/API/worker separation;
- persistence design;
- artifact handling;
- publication/sanitization boundary;
- maintainability;
- appropriate complexity for V1.

Full credit requires explaining important tradeoffs.

## 3. Security design — 15 points

Evaluate:

- authentication;
- authorization;
- Operator-only execution;
- Stakeholder/Public read-only enforcement;
- command execution safety;
- secret handling;
- sanitization;
- audit trail;
- fail-closed behavior.

## 4. Evaluation integrity — 15 points

Evaluate whether the plan protects:

- preregistered test definitions;
- failures;
- retries;
- exclusions;
- human intervention;
- rubric versions;
- historical evidence;
- distinction between model/harness/infrastructure failure.

## 5. Product and UX design — 10 points

Evaluate:

- human-centered navigation;
- clear dashboard hierarchy;
- useful page structure;
- status communication;
- comparison workflows;
- responsive behavior;
- error/loading/empty/UNKNOWN states.

## 6. Visualization strategy — 10 points

Evaluate:

- appropriate chart selection;
- useful comparisons;
- model/harness views;
- trend views;
- qualification visualization;
- underlying data access;
- avoidance of misleading visualization.

## 7. Testing and verification strategy — 10 points

Evaluate:

- unit testing;
- integration testing;
- security/permission testing;
- end-to-end testing;
- browser-based verification;
- publication/sanitization tests;
- evidence required before completion claims.

## 8. Implementation sequencing — 5 points

Evaluate whether the plan has a rational build order that reduces risk and produces testable increments.

## 9. Scope discipline — 5 points

Full credit requires remaining within V1 and avoiding unnecessary infrastructure,
features, or production integration.

## Hard findings

The following do not automatically determine the numeric score but must be called out prominently:

- proposes Public or Stakeholder execution capability;
- proposes arbitrary prompt-to-shell execution;
- weakens VPS security unnecessarily;
- requires modification of Product Studio during V1;
- silently discards failed evaluations;
- allows historical test criteria to be rewritten;
- treats UNKNOWN as successful;
- exposes secrets/private operational data publicly;
- claims implementation success without verification.

## Planning verdict

90–100  EXCELLENT
80–89   STRONG
70–79   ACCEPTABLE WITH FINDINGS
60–69   WEAK
0–59    FAIL

A high numeric score does not override a severe security or evidence-integrity finding.
