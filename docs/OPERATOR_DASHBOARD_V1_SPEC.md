# AI Evaluation Command Center — Phase 3 Operator Dashboard V1 Spec

**Product phase:** 3 — Operator Dashboard V1
**Benchmark capability:** `operator_dashboard_web_engineering`
**Status:** Frozen benchmark input once referenced by the freeze manifest

## 1. Goal

Build the first real Operator-facing dashboard for the AI Evaluation Command Center on top of the existing Phase 2 evidence foundation.

This is not a static mockup. The application must read persisted evidence from the existing SQLAlchemy/SQLite model and render useful Operator views from that data.

The dashboard exists to answer, at a glance:

- What evaluation runs have occurred recently?
- Which harness + model + capability combination was evaluated?
- What was the latest evaluator verdict/score?
- How long did the attempt take?
- How many input/output tokens were used and what did it cost?
- Was there human intervention, a permission denial, timeout, or failure classification?
- What is the current qualification state for that exact harness + model + capability?
- Can the Operator drill into the run and inspect the evidence lineage rather than trusting a summary badge?

## 2. Required stack

Use the existing Python project and evidence model.

Required additions:

- FastAPI
- Jinja2 templates
- server-rendered HTML
- progressive enhancement; HTMX may be used but is not required for every interaction
- SQLite through the existing SQLAlchemy foundation
- pytest
- FastAPI/Starlette test client or equivalent HTTP-level tests

Do not introduce React, Vue, Next.js, Node build tooling, Redis, Celery, BullMQ, a SPA framework, or a second persistence layer.

CSS may be plain project CSS. Small local JavaScript is allowed when it provides a clear UX benefit, but the core views must work as server-rendered HTML without requiring client-side application state.

## 3. Existing evidence model is authoritative

The Phase 2 SQLAlchemy model and Alembic migration on the frozen source commit are the source of truth. Extend them only if a small, clearly justified dashboard-supporting change is unavoidable. Prefer queries/view-models over schema changes.

Important semantics that the UI must preserve:

- UNKNOWN must remain visibly distinct from PASS/success.
- Process outcome, deliverable outcome, task outcome, and evaluator verdict are separate axes.
- Process exit code 0 must never be presented as proof that the task passed.
- Qualification belongs to the exact harness + model + capability triple.
- The latest score/verdict is the newest revision in append-only score history; prior revisions remain historical evidence.
- The latest qualification state is the newest decision in append-only qualification history; prior decisions remain historical evidence.
- Missing cost is UNKNOWN/Not recorded, not `$0.00`.
- Missing token counts are UNKNOWN/Not recorded, not zero.
- Excluded evidence remains inspectable and should not silently disappear.

## 4. Required application structure

The exact module names are flexible, but the deliverable must have a clear application entry point and separate template/static assets.

A reasonable structure is:

```text
src/aecc/
  web.py or app.py
  dashboard_queries.py
  dashboard_viewmodels.py
  templates/
  static/
```

Avoid embedding large HTML documents directly in Python strings.

## 5. Required routes/views

### 5.1 Operator dashboard — `GET /operator`

Render an overview page with:

#### Summary cards
At minimum:

- total runs represented by the current data set;
- runs requiring review or carrying a failing/non-pass latest verdict;
- qualified harness/model/capability combinations;
- UNKNOWN/unscored runs.

Summary calculations must be derived from persisted evidence, not hard-coded demo numbers.

#### Recent runs table
Show recent runs in deterministic newest-first order. Each row must expose enough information to distinguish:

- run identifier;
- test/logical test name or key;
- exact model identifier;
- harness identity/version;
- capability + version;
- run state;
- latest evaluator verdict and total score, or explicit `UNKNOWN`/`Not scored`;
- latest/relevant attempt elapsed time;
- input/output tokens when known;
- cost when known, with unknown cost explicitly distinguished from zero cost;
- human intervention indicator;
- permission denial indicator;
- current qualification state for the exact harness+model+capability triple;
- link to the run detail page.

The table may be paginated or initially limited, but ordering and behavior must be deterministic and tested.

### 5.2 Run detail — `GET /operator/runs/{run_id}`

Render an evidence-oriented run page containing:

- test/version identity and source commit when present;
- harness, exact model identifier, capability/version;
- run state and timestamps;
- all attempts in attempt-number order;
- for each attempt: timing, exit code, process outcome, deliverable outcome, task outcome, permission denial, human intervention, timeout, token counts, cost/cost source, failure classifications, sealed state, and evidence/artifact references when present;
- score/verdict revision history in chronological order, with latest clearly identified without hiding prior revisions;
- intervention events;
- exclusion events;
- current qualification decision and qualification history for the exact harness+model+capability triple;
- qualification evidence links relevant to the displayed qualification decision(s), when present.

A nonexistent run must return HTTP 404 rather than an empty success page.

### 5.3 Qualification overview — `GET /operator/qualifications`

Render one row per known harness+model+capability combination that has qualification history. Show:

- harness identity/version;
- exact model identifier/provider;
- capability/version;
- current qualification state;
- decision date, author, methodology version;
- restrictions/conditions when present;
- evidence summary when present;
- link(s) or drill-through path to supporting run evidence.

Current state must be derived from the newest qualification decision for the exact triple. Do not collapse qualification to model-only status.

## 6. Seed/demo evidence for deterministic verification

Provide a deterministic test/demo data fixture or seeding helper that populates the existing database model with enough evidence to exercise the UI. It must include at least:

1. one successful/pass-scored run with known zero-dollar cost;
2. one run with process SUCCESS but task FAILED and a failing verdict;
3. one run/attempt with permission denial and human intervention evidence;
4. one run with UNKNOWN/not-recorded score or cost fields;
5. at least two score revisions for one run so history/latest logic can be verified;
6. at least two qualification decisions for one harness+model+capability triple so current/history logic can be verified;
7. at least one qualification evidence link to a run or attempt;
8. at least one exclusion or intervention event retained for drill-down.

This fixture is for verification/demo only. Production route logic must query the database and must not depend on hard-coded rows.

## 7. Visual/UX requirements

The dashboard should look like an operations/research command center rather than framework-default HTML.

Required qualities:

- clear hierarchy and readable typography;
- responsive layout usable on desktop and narrow screens;
- status badges must include text labels, not color alone;
- PASS, FAIL, NEEDS_REVIEW, UNKNOWN, EXCLUDED and qualification states must be visually distinguishable;
- UNKNOWN must never be styled as green/success;
- tables remain readable with long exact model identifiers;
- evidence drill-down should prioritize facts over decorative UI;
- navigation among Overview, Runs/detail, and Qualifications must be obvious;
- basic accessibility: semantic headings, table headers, link/button labels, adequate contrast, keyboard-usable navigation.

Do not spend benchmark time on logos, marketing copy, public website pages, or elaborate animations.

## 8. Query correctness requirements

Implement and test deterministic logic for:

- newest-first recent runs;
- selecting latest score revision without destroying access to prior revisions;
- selecting latest qualification decision separately for each exact harness+model+capability triple;
- selecting the relevant/latest attempt for overview metrics while preserving all attempts on detail;
- distinguishing `None`/missing cost from numeric `0.0`;
- distinguishing missing tokens from numeric zero;
- rendering UNKNOWN/unscored states explicitly;
- preserving process/task/verdict separation in presentation.

Avoid N+1 query explosions where straightforward eager loading or composed queries can prevent them, but do not introduce unnecessary abstraction solely for optimization.

## 9. Required automated verification

`python -m pytest -q` must run from repository root and pass.

Tests must include HTTP/rendered-page behavior, not only helper-unit tests. At minimum prove:

- `/operator` returns 200;
- `/operator/qualifications` returns 200;
- known run detail returns 200 and unknown run returns 404;
- recent runs order is deterministic/newest-first;
- exact model/harness/capability identity appears in rendered output;
- latest score/verdict is shown while score history remains visible on detail;
- qualification current state is triple-keyed and history remains visible;
- process SUCCESS + task FAILED is rendered as distinct facts and not presented as PASS;
- UNKNOWN verdict/state is not rendered as PASS;
- missing cost is rendered as unknown/not recorded and numeric zero cost renders as zero;
- permission denial and human intervention indicators render from evidence;
- run detail includes attempts and evidence/history sections;
- HTML has navigation and basic semantic structure;
- existing Phase 2 invariant tests continue to pass.

The benchmark should contain at least 15 meaningful dashboard-specific tests in addition to preserving the existing foundation test suite.

## 10. Deliverables

Produce working repository code including:

- FastAPI application entry point;
- dashboard queries/view-model logic;
- Jinja templates;
- CSS/static assets needed by the UI;
- deterministic fixture/seeding helper for tests/demo;
- automated tests;
- dependency updates in `pyproject.toml` if required.

At the end, return a concise implementation report stating:

1. what was implemented;
2. important files added/changed;
3. exact test command and result;
4. routes implemented;
5. any unresolved issue or assumption.

Do not claim success if the test suite does not pass.

## 11. Explicitly out of scope

Do not implement in this benchmark:

- benchmark execution queue/worker;
- model invocation;
- Podman/container execution controls;
- network egress controls;
- login/authentication/SSO;
- Stakeholder or Public portals;
- public sanitization/projector pipeline;
- WebSockets/live streaming;
- external analytics services;
- ECharts or complex charting unless trivially useful after all required views/tests are complete;
- Product Studio integration;
- systemd/deployment services.

## 12. Files that must not be modified

Do not modify benchmark/methodology inputs or prior historical specifications, including:

- `docs/ARCHITECTURE_BASELINE_V1.md`
- `docs/IMPLEMENTATION_FOUNDATION_V1_SPEC.md`
- `docs/IMPLEMENTATION_RUBRIC_V1.md`
- `docs/OPERATOR_DASHBOARD_V1_SPEC.md`
- `prompts/phase3-operator-dashboard-v1.txt`
- `validators/phase3-operator-dashboard-v1.json`
- prior benchmark freeze manifests
- `scripts/run_benchmark.py`
- `scripts/run_implementation_benchmark.py`
- `opencode.jsonc`

Do not access or modify `~/work/product-studio-ops` or any external repository.
