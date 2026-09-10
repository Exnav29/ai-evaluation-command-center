# AI Evaluation Command Center — Architecture Baseline V1

**Version:** 1.0-draft  
**Status:** Human review required before implementation  
**Repository:** `Exnav29/ai-evaluation-command-center`  
**V1 development root:** `~/work/opencode-eval`  
**Out of scope / prohibited target:** `~/work/product-studio-ops`

## 1. Purpose of this document

This document is the human-reviewed architecture contract for AI Evaluation Command Center V1.

It converts the preregistered V1 product specification and the planning-benchmark evidence into a single implementation baseline. Implementation models may make local design choices inside this contract, but they must not silently weaken or bypass its security, evidence-integrity, qualification, publication, or scope boundaries.

The governing research question is:

> How much engineering work can free or very-low-cost models perform reliably, and when is escalation to frontier models actually necessary?

The system must evaluate models and coding-agent harnesses separately, preserve failures and retries, prevent cherry-picking, and support evidence-based qualification.

This document does **not** authorize implementation until it has been reviewed and accepted by the human Operator.

---

## 2. Non-negotiable V1 principles

The following are architectural invariants, not suggestions:

1. **Evidence before claims.**
2. **UNKNOWN never becomes PASS by default, coercion, missing data, aggregation, or UI presentation.**
3. **Process success is not task success.** Exit code `0` may coexist with a failed or missing deliverable.
4. **Failed runs remain evidence.**
5. **Retries remain separate, visible attempts.**
6. **Exclusions remain visible with reasons.**
7. **Human intervention and frontier escalation are recorded.**
8. **Registered test criteria are immutable.** Corrections create new versions.
9. **Qualification is specific to `harness + model + capability`.**
10. **Qualification is evidence-based and historically auditable.**
11. **Model failure, harness failure, infrastructure failure, and task failure must be distinguishable.**
12. **Operator is the only plane that may cause execution.**
13. **Information moves outward only: `Operator -> Stakeholder -> Public`.**
14. **Stakeholder and Public surfaces never directly query unrestricted private evidence.**
15. **A working directory is not a security sandbox.**
16. **Write-capable or shell-capable AI execution requires real OS/container-level containment.**
17. **Execution networking is restricted, not universally disabled; approved model-provider egress must remain possible.**
18. **V1 uses a SQLite-backed queue. Redis/BullMQ or other broker infrastructure is prohibited unless later evidence justifies an architecture change.**
19. **V1 development remains inside `~/work/opencode-eval`.**
20. **Product Studio must not be modified, mounted into evaluation sandboxes, or used as an implementation target for Command Center V1.**

If an implementation model cannot satisfy one of these invariants, it must stop, identify the conflict, and request human review rather than substitute a weaker design.

---

## 3. V1 technology baseline

V1 will use a deliberately small Python-centric stack:

- **Python** for application, worker, evaluation orchestration, sanitization, and publication logic.
- **FastAPI** for server-side HTTP routing and application endpoints.
- **Jinja2** for server-rendered HTML.
- **HTMX or equivalent progressive enhancement** for targeted interactive behavior without creating a separate SPA architecture.
- **SQLite in WAL mode** for V1 persistence.
- **SQLAlchemy** for database access.
- **Alembic** for schema migrations.
- **ECharts** for dashboard visualizations.
- **Pytest** for unit and integration tests.
- **Playwright** for browser-level verification.
- **systemd** for long-running V1 processes on the VPS.
- **Podman, preferably rootless, for per-run execution containment**, subject to the containment requirements in this document.
- **An allowlisting HTTP/HTTPS egress proxy or equivalent controlled egress mechanism** for execution containers that require approved model-provider access.

Versions must be pinned in the implementation repository or lock files. A material framework, harness, or execution-runtime upgrade must be evidence-visible and must not silently inherit prior qualification.

### 3.1 Explicitly rejected for V1

Unless a later architecture decision is backed by measured need, V1 will not introduce:

- Redis;
- BullMQ;
- Kafka;
- RabbitMQ;
- Kubernetes;
- a microservice mesh;
- a separate Node/Next.js API tier;
- Prisma;
- a mandatory SPA frontend;
- distributed tracing infrastructure;
- multi-tenant SaaS infrastructure.

The V1 objective is a maintainable, inspectable system whose complexity is justified by the research task.

---

## 4. Process topology and trust boundaries

V1 uses three application processes plus the execution containment boundary.

### 4.1 Control web process

The **Control Web** process serves the authenticated Operator plane.

It may:

- read and write the private evaluation database;
- register immutable test versions;
- enqueue evaluation jobs;
- display private evidence;
- accept evaluator scores, verdicts, notes, exclusions, and qualification decisions;
- initiate explicit sanitization/publication actions;
- manage authorized Operator/Stakeholder identities if V1 user management is implemented.

It must **not** directly execute arbitrary model-generated shell commands inside the web request process.

### 4.2 Worker process

The **Worker** process:

- reads eligible queued jobs from the private queue;
- atomically claims work;
- creates a distinct execution attempt;
- prepares a disposable subject workspace;
- launches the approved harness/model inside the execution containment boundary;
- captures stdout/stderr, timing, exit code, artifacts, repository state, permission events, and other measurable evidence;
- seals the attempt when collection is complete;
- records infrastructure interruption or UNKNOWN evidence when collection cannot be completed.

The worker has no browser-facing route.

### 4.3 Read web process

The **Read Web** process serves:

- authenticated Stakeholder pages; and
- unauthenticated Public pages.

It may read only sanitized projection stores and the minimum authentication/session store required for Stakeholder access.

It must not have filesystem permission to read:

- `data/evaluations.sqlite`;
- private raw artifacts;
- model-provider secrets;
- execution credentials;
- private run workspaces.

It must not have any execution adapter, worker control socket, shell endpoint, or model-provider credential.

### 4.4 Publication projector

Projection/sanitization logic is an explicit application component invoked from the Operator side. It is not a public endpoint.

Publication occurs in two stages:

1. `Private Operator evidence -> Stakeholder projection`
2. `Stakeholder projection -> Public projection`

A Public record must have provenance to an already-sanitized Stakeholder representation or a formally approved aggregate derived from that representation.

### 4.5 Reverse proxy

An existing or lightweight reverse proxy may terminate TLS and route traffic. It does not change authorization rules. Public routing must never expose Control Web or Worker execution routes.

---

## 5. Storage separation

V1 uses separate SQLite files to enforce the publication boundary:

- `data/evaluations.sqlite` — private Operator/Worker evidence and queue.
- `data/auth.sqlite` — authentication/session data if application-managed authentication is used.
- `data/stakeholder.sqlite` — sanitized Stakeholder projection only.
- `data/public.sqlite` — sanitized Public projection only.

The Public and Stakeholder surfaces must never query `data/evaluations.sqlite`.

SQLite databases are runtime evidence and remain excluded from source control.

Raw artifacts remain private by default under ignored runtime storage, for example:

- `artifacts/private/...`
- `runs/...`

Published derivatives belong in explicit sanitized export/projection locations, for example:

- `exports/stakeholder/...`
- `exports/public/...`

Public source-controlled datasets, if intentionally published later, must be created by a separate explicit publication step after human review. They must never be copied directly from private runtime storage.

---

## 6. Core domain model

The implementation may choose exact table names, but it must preserve the following concepts and relationships.

### 6.1 Test identity and immutable test versions

A logical test may have multiple versions.

Each registered test version must capture, directly or by immutable reference:

- logical test identifier;
- version identifier;
- name and description;
- capability/task category;
- exact prompt/task bytes;
- acceptance criteria;
- rubric identifier and version;
- retry policy;
- timeout;
- expected artifacts;
- permission profile;
- source/fixture identifier;
- source commit/ref where applicable;
- harness selection policy where applicable;
- model selection policy where applicable;
- creation timestamp;
- registration timestamp;
- content hash.

A new correction creates a new registered version with a relationship such as `supersedes_version_id`. The previous version remains queryable.

### 6.2 Harnesses

Harness records must identify at minimum:

- stable harness key;
- display name;
- exact version/build where measurable;
- configuration snapshot or configuration hash relevant to the run.

A harness version change is evidence-relevant.

### 6.3 Models

Model records must identify at minimum:

- stable model key;
- provider;
- exact provider/model identifier used for execution;
- pricing/free-tier classification snapshot where relevant;
- configuration parameters that can materially affect evaluation, such as reasoning effort when exposed.

Aliases must not erase the exact executed provider/model identifier.

### 6.4 Capabilities

Capabilities are explicit, versionable evaluation dimensions such as:

- repository exploration;
- documentation;
- architecture planning;
- frontend development;
- backend development;
- test generation;
- bug fixing;
- refactoring;
- shell diagnostics;
- security review;
- production operations.

A capability definition may evolve, but historical qualification must retain the capability definition/version that applied at decision time.

### 6.5 Evaluation runs

A **run** is the logical evaluation assignment of a registered test version to a specific harness/model combination.

A run must bind:

- registered test version;
- harness identity/version;
- model identity/configuration;
- capability;
- source commit/fixture;
- evaluator/methodology version;
- requested permission profile;
- queue state;
- timestamps;
- current logical run state.

A run may contain one or more attempts.

### 6.6 Attempts

An **attempt** is one actual invocation of the harness/model for a run.

Retries create new attempt rows. They do not overwrite prior attempts.

Each attempt records where measurable:

- attempt number;
- start and finish timestamps;
- elapsed time;
- time to first process output;
- exact command/harness invocation metadata;
- process exit code;
- process outcome;
- deliverable outcome;
- task outcome;
- repository modification outcome;
- permission denial events;
- timeout/cancellation;
- artifact references and hashes;
- token usage;
- cost;
- model-provider response metadata where available;
- human intervention;
- frontier escalation;
- failure classifications;
- raw evidence location;
- seal timestamp.

### 6.7 Scores and verdicts

Scoring data is append-only by revision.

A score/verdict revision must record:

- run or attempt being evaluated;
- rubric version;
- dimension scores;
- total score if applicable;
- evaluator verdict;
- notes/findings;
- evaluator identity;
- timestamp;
- superseded score revision if this is a correction.

Prior score revisions remain visible.

### 6.8 Interventions

Human interventions must be recorded as explicit events, not buried only in prose.

Examples:

- permission override;
- prompt clarification;
- retry authorization;
- manual file repair;
- harness recovery;
- frontier escalation;
- evaluator exclusion.

Each event records who/what caused it, when, why, and which run/attempt it affected.

### 6.9 Exclusions

An exclusion is not deletion.

Exclusions require:

- target run/attempt;
- reason;
- author;
- timestamp;
- methodology basis;
- whether exclusion affects a particular aggregate.

Excluded evidence remains inspectable and aggregate reports must disclose exclusion counts.

---

## 7. Registered-test immutability

Registered test versions are append-only.

### 7.1 Required enforcement

V1 must enforce immutability in both:

1. **application logic**, and
2. **the database**.

A normal SQLite `CHECK` constraint is not sufficient to compare historical row state.

The preferred V1 design is:

- mutable draft data is stored separately or remains a draft object;
- registration creates a new immutable test-version row containing the frozen definition and hash;
- registered test-version rows are never edited in place;
- SQLite `BEFORE UPDATE` and `BEFORE DELETE` triggers reject mutation of immutable registered-definition tables using `RAISE(ABORT, ...)`;
- corrections insert a new version.

Rubric/methodology definitions used by a registered test must likewise be versioned and historically recoverable.

### 7.2 Canonical definition hash

Registration must compute a deterministic hash over the frozen evaluation definition or its exact referenced bytes.

The hash must cover all evaluation-relevant inputs, including:

- prompt/task;
- acceptance criteria;
- rubric version;
- source/fixture reference;
- permission profile;
- retry policy;
- timeout;
- expected artifacts.

The purpose is detection and reproducibility, not secrecy.

---

## 8. SQLite-backed queue

The private evaluation database is also the V1 queue.

### 8.1 Queue requirements

Jobs must support at least:

- `QUEUED`;
- `CLAIMED` or `STARTING`;
- `RUNNING`;
- `COMPLETED`;
- `CANCEL_REQUESTED`;
- `CANCELLED`;
- `NEEDS_REVIEW`;
- `INFRASTRUCTURE_FAILURE`.

The implementation may use a stricter state machine.

### 8.2 Atomic claim

A worker claim must occur inside an atomic SQLite transaction so two workers cannot legitimately claim the same queued job.

`BEGIN IMMEDIATE` or an equivalently safe transaction pattern may be used.

V1 should begin with **concurrency 1** unless benchmark evidence justifies more parallel workers.

### 8.3 Worker lease and heartbeat

A running job must expose a worker lease/heartbeat.

If the lease becomes stale:

- the existing attempt must not disappear;
- the stale attempt is marked as interrupted/UNKNOWN or infrastructure-failed according to available evidence;
- the job is not silently treated as successful;
- a retry becomes a new attempt and must be authorized by the frozen retry policy or the Operator.

Automatic recovery must never overwrite the failed/interrupted attempt.

### 8.4 No queue broker in V1

Redis or another broker is not part of V1. If SQLite queue contention becomes a measured limitation, that evidence becomes the basis for a later architecture decision.

---

## 9. Execution containment

This is a release-blocking security requirement.

### 9.1 Minimum containment

Any evaluation that grants meaningful write authority or shell/tool authority to AI-generated behavior must execute inside an OS/container isolation boundary.

A writable Git worktree alone is insufficient.

The preferred V1 boundary is a disposable Podman container per attempt with:

- non-root execution;
- user namespace/rootless mode where practical;
- no privileged mode;
- no host PID namespace;
- no host IPC namespace;
- no host network mode;
- no Docker/Podman socket mounted into the container;
- no SSH agent socket;
- no host home directory mount;
- no `~/.ssh`;
- no Product Studio repository mount;
- only the disposable evaluation workspace mounted writable;
- required benchmark inputs mounted read-only where possible;
- dropped Linux capabilities;
- `no-new-privileges`;
- process/PID limits;
- memory limits;
- CPU/time limits;
- temporary filesystem limits where practical;
- seccomp or runtime-default syscall filtering;
- deterministic cleanup after evidence capture.

An equivalent containment mechanism may replace Podman only after human review and only if it demonstrates the same security properties.

### 9.2 Source workspace

Each attempt receives a disposable source workspace created from the exact registered source commit/ref or fixture.

The host repository used to orchestrate evaluation must not become the model's unrestricted writable environment.

Repository modification inside the disposable workspace is evidence and must be measured.

### 9.3 Restricted network egress

Zero network is not the default because evaluated models may require provider APIs.

Execution containers must not receive general unrestricted Internet access.

The V1 design must provide:

- access only to approved model-provider endpoints and other specifically preregistered endpoints;
- denial of arbitrary outbound destinations;
- no inbound listening exposure from the public Internet;
- evidence of denied network actions where measurable.

The preferred V1 mechanism is a dedicated allowlisting HTTP/HTTPS egress proxy reachable from the execution namespace while direct Internet routing is unavailable.

Provider allowlists are configuration, not model-controlled input.

If the selected harness/provider cannot operate under restricted egress, that is a visible architecture or harness constraint; the system must not silently grant unrestricted Internet access.

### 9.4 Secrets

Only the minimum credentials required for the selected model/provider may enter the execution boundary.

Secrets must:

- come from runtime secret/configuration storage outside Git;
- not be copied into benchmark prompts;
- not be written into published evidence;
- not be inherited wholesale from the Operator shell environment;
- be scoped per provider/use when possible.

### 9.5 Containment gate

Until containment tests pass, V1 may run read-only/no-shell planning-style evaluations under an appropriately restrictive permission profile, but it must not claim that write/bash-capable execution is safely supported.

Implementation qualification that grants write/bash authority is blocked until containment is verified.

---

## 10. Outcome and failure model

The system must not compress execution into a single “success” boolean.

### 10.1 Required separate outcome axes

At minimum, each attempt must preserve separate fields for:

**Process outcome**
- SUCCESS
- FAILURE
- TIMEOUT
- CANCELLED
- UNKNOWN

**Deliverable outcome**
- PRESENT
- MISSING
- NOT_CHECKED
- UNKNOWN

**Task outcome**
- SUCCEEDED
- FAILED
- NEEDS_REVIEW
- NOT_EVALUATED
- UNKNOWN

**Evaluator verdict**
- PASS
- PASS_WITH_FINDINGS
- NEEDS_REVIEW
- FAIL
- INFRASTRUCTURE_FAILURE
- EXCLUDED
- UNKNOWN

A process exit code of `0` may produce:

- process outcome = SUCCESS;
- deliverable outcome = MISSING;
- task outcome = FAILED;
- evaluator verdict = FAIL.

This is valid and expected.

### 10.2 Failure classification

Failure attribution is evidence separate from task outcome.

The system must support at least:

- MODEL_FAILURE;
- HARNESS_FAILURE;
- INFRASTRUCTURE_FAILURE;
- TASK_FAILURE;
- PERMISSION_POLICY_FAILURE;
- MIXED;
- UNKNOWN.

Primary and secondary/contributing classifications may be recorded.

A failure may remain UNKNOWN when evidence does not support attribution. UNKNOWN must not be rewritten into a convenient cause merely to improve aggregate reporting.

### 10.3 Preserve first-order raw facts

Derived verdicts must never replace raw evidence such as:

- exit code;
- first process output;
- stdout/stderr;
- permission request/denial;
- repository diff/status;
- validator result;
- timestamps.

---

## 11. Evidence sealing and corrections

Runtime records may be updated while an attempt is actively collecting evidence. Once finalized, the attempt is sealed.

After sealing:

- material evidence rows may not be silently rewritten;
- database triggers or equivalent database enforcement must reject direct destructive mutation of sealed evidence;
- corrections are appended as explicit correction/review events;
- the original value remains historically recoverable.

Artifact hashes are immutable facts. Replacing an artifact creates a new artifact record.

Audit events must cover consequential Operator actions including:

- registration;
- queue submission;
- cancellation;
- retry authorization;
- score/verdict entry or correction;
- exclusion;
- qualification decision;
- stakeholder publication;
- public publication.

---

## 12. Qualification model

Qualification is keyed by:

**`harness + model + capability`**

No V1 schema or UI may reduce qualification to only model+capability or harness+capability.

### 12.1 Qualification evidence

Every qualification decision must record:

- harness key and relevant version/build;
- exact model key/provider identifier;
- capability key/version;
- qualification state;
- evidence runs/attempts supporting the decision;
- methodology/policy version;
- decision timestamp;
- decision author;
- restrictions or conditions;
- superseded prior qualification decision, if any.

States include:

- UNQUALIFIED;
- SHADOW;
- QUALIFIED;
- RESTRICTED;
- NOT_AUTHORIZED.

### 12.2 Qualification is append-only

Qualification changes create decision records. They do not overwrite history.

The “current” state is a projection of the latest valid decision.

### 12.3 Version changes

A material harness version, model identifier/configuration, capability definition, or qualification-methodology change must not silently inherit prior qualification.

The UI may show historical qualification, but the current combination returns to the state required by the active qualification policy, normally UNQUALIFIED or SHADOW, until evidence supports promotion.

### 12.4 No cherry-picking

Qualification evidence selection must disclose:

- failed attempts;
- retries;
- exclusions;
- human interventions;
- relevant methodology changes.

A qualification view must provide drill-through to the evidence set used for the decision.

---

## 13. Publication and sanitization

Publication is an explicit transformation, not a view flag over private tables.

### 13.1 Operator to Stakeholder

The Operator selects eligible evidence for stakeholder projection.

The sanitizer/projector:

- applies an allowlist schema;
- strips secrets and private paths;
- strips environment variables and credentials;
- strips unrestricted shell output unless specifically sanitized;
- strips private source content;
- converts private artifact references into sanitized derivatives;
- retains required research facts such as model, harness, task category, timing, outcomes, scores, retries, interventions, exclusion reasons, and qualification provenance;
- records projection version and source provenance.

The result is written into `data/stakeholder.sqlite` and/or sanitized stakeholder artifacts.

### 13.2 Stakeholder to Public

Public publication starts from sanitized Stakeholder data, not unrestricted private evidence.

The public projector may further:

- aggregate;
- redact;
- generalize private identifiers;
- publish safe datasets;
- create chart-ready tables.

The Public projection must retain enough methodology and sample-size context to prevent misleading claims.

### 13.3 Deny by default

Sanitization uses **field allowlists**, not a blacklist of known secrets.

Unknown fields are not published automatically.

New private schema fields therefore do not become public merely because the sanitizer has not learned their names.

### 13.4 Publication provenance

Published records must retain machine-readable provenance such as:

- projection version;
- methodology version;
- source run identifiers represented by safe public/stakeholder IDs;
- publication timestamp;
- approving Operator action.

A public correction creates a new publication revision or tombstone/correction record; it does not rewrite research history without trace.

---

## 14. Authentication, authorization, and request security

### 14.1 Roles

V1 requires:

- OPERATOR;
- STAKEHOLDER;
- PUBLIC/anonymous.

There is no public self-service elevation path.

### 14.2 Server-side authorization

Authorization is enforced server-side on every protected operation.

Hiding a button is not authorization.

The system fails closed when identity or authorization is unknown.

### 14.3 Sessions

If application-managed authentication is used:

- passwords are stored only as modern salted password hashes such as Argon2id;
- sessions are server-validated;
- cookies use Secure, HttpOnly, and appropriate SameSite settings;
- session fixation is prevented;
- logout invalidates the session;
- mutating browser requests use CSRF protection.

### 14.4 Execution input

Browser input must never be concatenated into shell commands.

Harness commands are built from:

- registered immutable definitions;
- server-owned executable mappings;
- validated identifiers;
- server-owned permission profiles.

No Public or Stakeholder input may reach an execution adapter.

### 14.5 Operator-only execution boundary

Only authenticated, authorized Operator actions may:

- register executable test versions;
- enqueue jobs;
- cancel jobs;
- authorize retries outside an automatic preregistered policy.

The worker independently validates that a claimed job references a registered immutable definition and an allowed execution profile before launch.

---

## 15. Permission profiles

Execution authority is represented by named, server-owned permission profiles rather than arbitrary user-supplied tool permissions.

Examples may include:

- `READ_ONLY_NO_SHELL`;
- `READ_ONLY_DIAGNOSTIC`;
- `WORKSPACE_WRITE_RESTRICTED`;
- `WORKSPACE_WRITE_AND_SHELL_CONTAINED`.

Each profile defines:

- permitted harness tools/actions;
- filesystem access;
- shell authority;
- network policy;
- timeout/resource limits;
- whether human permission prompts are allowed;
- expected denial behavior.

Permission-profile definitions are versioned and recorded with each run.

A model asking for a disallowed tool is evaluation evidence. The system must not silently expand authority to help the model succeed.

---

## 16. Artifact model

Artifacts are content-addressed or otherwise integrity-hashed.

Artifact metadata includes:

- artifact ID;
- owning attempt;
- media/type;
- private storage location;
- SHA-256 or equivalent strong hash;
- byte size;
- creation timestamp;
- visibility classification;
- sanitized derivative relationship if one exists.

Visibility states should distinguish at least:

- PRIVATE;
- STAKEHOLDER_SANITIZED;
- PUBLIC_SANITIZED.

Changing visibility does not mutate raw bytes. Publication creates a sanitized derivative or projection reference.

---

## 17. Operator experience

Minimum Operator navigation remains:

- **Overview**
- **New Evaluation**
- **Run Queue**
- **Results Explorer**
- **Compare**
- **Qualification Board**
- **Methodology**

The Operator UI must make the following visually obvious:

- QUEUED/RUNNING/COMPLETED state;
- UNKNOWN state;
- process success vs task failure;
- retries;
- human intervention;
- permission denial;
- infrastructure failure;
- exclusions;
- unpublished/private status;
- qualification state and evidence.

The Operator must not need raw SQL for routine operation.

---

## 18. Stakeholder experience

Stakeholder is authenticated and read-only.

It may expose:

- sanitized individual runs;
- comparisons;
- methodology;
- scores/verdicts;
- timing/cost;
- retries/interventions;
- failure classifications;
- qualification evidence;
- sanitized artifacts;
- chart data/tables.

It exposes no execution controls and has no route whose downstream service can enqueue or invoke a model.

---

## 19. Public experience

Public is read-only and Internet-facing.

It may expose:

- project purpose;
- methodology;
- sample sizes;
- aggregate outcomes;
- model comparisons;
- harness comparisons;
- capability comparisons;
- timing and cost findings;
- free-vs-frontier utilization;
- qualification summaries;
- exclusions and limitations;
- safe public datasets.

Public reporting must visibly communicate that:

- failed runs are retained;
- retries are retained;
- UNKNOWN is not PASS;
- qualification is evidence-based;
- sample size and methodology versions matter.

---

## 20. Visualization contract

ECharts visualizations must be driven from sanitized projection data on Stakeholder/Public surfaces.

Required V1 chart families include:

- outcome distribution;
- pass rate by model;
- pass rate by harness;
- model × capability heatmap;
- performance over time;
- duration by model;
- human-intervention rate;
- failure categories;
- free vs frontier utilization;
- frontier escalation rate;
- quality vs duration;
- quality vs cost where known;
- qualification progression.

Every important chart must expose the underlying tabular values.

UNKNOWN, missing cost, and missing timing data must remain explicit rather than being converted to zero.

Axes and aggregation choices must not exaggerate differences.

---

## 21. State machines

### 21.1 Test lifecycle

A conceptual lifecycle is:

`DRAFT -> REGISTERED`

A registered version is immutable.

A changed test becomes a **new DRAFT/new version**, then a new REGISTERED version. It does not transition backward.

### 21.2 Run lifecycle

A run may follow:

`QUEUED -> CLAIMED -> RUNNING -> COMPLETED -> SCORING -> FINALIZED`

With explicit alternate states such as:

- CANCEL_REQUESTED;
- CANCELLED;
- NEEDS_REVIEW;
- INFRASTRUCTURE_FAILURE;
- EXCLUDED.

State transitions are validated server-side and logged.

### 21.3 Attempt lifecycle

An attempt may follow:

`STARTING -> RUNNING -> COLLECTING -> SEALED`

With terminal alternatives such as:

- PROCESS_FAILED;
- TIMED_OUT;
- CANCELLED;
- INTERRUPTED;
- INFRASTRUCTURE_FAILURE;
- UNKNOWN.

The precise enum may differ, but the implementation must preserve the distinction between run state, process state, deliverable state, task state, and evaluator verdict.

---

## 22. Testing and verification requirements

Implementation is not complete because code exists or a server starts.

### 22.1 Database invariant tests

Automated tests must prove:

- registered test versions cannot be updated;
- registered test versions cannot be deleted;
- a corrected test creates a new version;
- sealed evidence cannot be silently mutated;
- retries create new attempts;
- qualification keys require harness + model + capability;
- UNKNOWN is not counted as PASS;
- excluded evidence remains present;
- score corrections retain prior revisions.

### 22.2 Queue tests

Automated tests must prove:

- only one worker can claim a queued job;
- stale leases do not produce phantom success;
- a recovered/retried job retains the prior interrupted attempt;
- cancellation state is auditable.

### 22.3 Authorization tests

Automated tests must prove:

- Public cannot access Operator routes;
- Stakeholder cannot access Operator routes;
- Stakeholder cannot mutate sanitized data;
- Public/Stakeholder cannot enqueue execution;
- missing/invalid authorization fails closed.

### 22.4 Publication leakage tests

Tests must seed private evidence containing synthetic secrets and private paths and prove they do not appear in:

- stakeholder projection;
- public projection;
- public API/HTML;
- sanitized artifact exports.

Unknown newly added private fields must remain unpublished until explicitly allowlisted.

### 22.5 Execution containment tests

Before write/bash-capable evaluation is enabled, fresh verification must prove that an evaluated process cannot:

- read Product Studio;
- read the Operator home directory;
- read SSH keys;
- access container-engine sockets;
- write outside the disposable workspace;
- become privileged;
- reach arbitrary unapproved Internet destinations;
- bypass configured resource/time limits.

Tests must also prove that approved model-provider egress still works.

### 22.6 Outcome tests

Tests must include a fixture where:

- process exit code = `0`;
- no valid requested deliverable is produced;
- task result = failure.

The UI and aggregate queries must show this as task failure, not success.

### 22.7 Browser verification

Playwright or equivalent browser tests must verify:

- core Operator workflows;
- read-only Stakeholder workflow;
- Public dashboard;
- loading/empty/error/UNKNOWN states;
- responsive behavior;
- status not conveyed by color alone.

### 22.8 Reproducibility verification

A benchmark executed against a pinned source commit must record:

- subject commit;
- evaluator commit;
- prompt/rubric/validator hashes;
- harness/model identities;
- attempt evidence location.

A later evaluator implementation must not change the subject snapshot presented to the model.

---

## 23. Operational baseline

V1 runs as systemd-managed services on the existing VPS.

Expected long-running units are conceptually:

- `aecc-control`;
- `aecc-worker`;
- `aecc-read`;
- optional dedicated egress-proxy unit if not supplied by existing infrastructure.

Services should:

- run under dedicated least-privilege Unix identities where practical;
- have explicit working directories;
- restart according to safe service policy;
- write structured logs without secrets;
- expose health/readiness checks;
- fail loudly when required databases, migrations, or security prerequisites are missing.

The read service must not be granted filesystem access to the private evidence database simply for convenience.

SQLite must use:

- foreign keys enabled;
- WAL mode;
- bounded busy timeout;
- transactionally safe migrations;
- backups appropriate for WAL databases.

Migration and backup operations must preserve evidence integrity.

---

## 24. Cost and utilization evidence

Because the research question includes low-cost/free models and frontier escalation, each attempt should record where available:

- provider;
- exact model identifier;
- token usage by provider-reported category;
- billed or estimated cost;
- pricing snapshot/source version;
- whether the run used a free/contributor/free-tier route;
- whether frontier escalation occurred.

Missing cost data is UNKNOWN, not `$0`.

Historical cost should not be silently recomputed using today's prices without labeling the result as a re-estimate.

---

## 25. Harness-versus-model analysis

The data model and reporting layer must support all of the following without restructuring the database:

- model performance across harnesses;
- harness performance across models;
- exact harness+model combination performance;
- capability-specific performance;
- failure attribution by model;
- failure attribution by harness;
- permission-denial recovery behavior;
- duration/cost/intervention by model and harness.

A run always binds both a harness and a model. Aggregate views may group by one dimension while retaining the other as evidence.

---

## 26. V1 implementation sequence

The architecture is intended to support vertical slices, not a large “big bang” build.

The first implementation benchmark should focus on the **database/evidence foundation**:

1. schema and migrations;
2. immutable preregistered test definitions;
3. harness/model/capability identity;
4. runs and attempts;
5. separate process/deliverable/task/verdict fields;
6. scores and verdict revisions;
7. intervention/exclusion events;
8. qualification keyed by harness + model + capability;
9. database-level immutability/sealing rules;
10. automated tests proving the invariants.

The queue, worker, containment, publication, and UI should build on that foundation in later reviewed slices.

No implementation slice is authorized to modify Product Studio.

---

## 27. Architecture change rule

An implementation model may not independently replace a baseline architectural decision because another framework is more familiar.

A proposed deviation must include:

- the baseline rule being changed;
- measured or demonstrated reason;
- security/evidence-integrity impact;
- operational complexity impact;
- migration impact;
- verification plan.

Human approval is required before the deviation becomes part of V1.

Redis/BullMQ, a SPA/API split, unrestricted egress, removal of separate projection stores, or weakening of execution containment are examples of changes requiring explicit human architecture approval.

---

## 28. Definition of architecture-compliant V1

An implementation is architecture-compliant only when fresh evidence demonstrates that:

1. immutable registered test definitions cannot be silently rewritten;
2. runs and attempts preserve failures and retries;
3. process success and task success are separate;
4. UNKNOWN remains UNKNOWN throughout storage, scoring, aggregation, and UI;
5. failure attribution can distinguish model, harness, infrastructure, and task failure;
6. qualification is keyed by harness + model + capability and links to evidence;
7. Operator alone can cause execution;
8. Stakeholder/Public cannot query unrestricted private evidence;
9. publication is a sanitized, allowlisted projection;
10. meaningful AI write/shell execution occurs only inside verified containment;
11. execution egress is restricted to approved destinations;
12. Product Studio is neither modified nor exposed to evaluation sandboxes;
13. significant historical corrections are additive and auditable;
14. charts expose underlying values and preserve missing/UNKNOWN data;
15. the implementation passes automated and browser-level verification appropriate to the completed slice.

Until those claims are supported by evidence, the corresponding capability is **not yet proven**, regardless of code completeness or process exit status.

---

## 29. Human review checkpoints before implementation qualification

Before freezing the first implementation benchmark, the Operator should explicitly approve:

- this architecture baseline;
- the exact first vertical-slice task;
- the implementation rubric;
- the source commit exposed to competing models;
- allowed tools/permission profile;
- timeout/retry policy;
- structural deliverable validator;
- scoring method;
- whether the benchmark is read-only or write-capable;
- if write-capable, evidence that the containment gate has already passed.

The benchmark must then be frozen before the competing model sees it.

---

## 30. V1 scope boundary

V1 does not include:

- modification or autonomous operation of Product Studio;
- production changes to unrelated applications;
- multi-tenant SaaS;
- billing;
- customer self-service accounts;
- mobile applications;
- arbitrary public prompt execution;
- unrestricted agent Internet access;
- autonomous qualification without an approved evidence policy;
- infrastructure added only for hypothetical future scale.

The Command Center is an evaluation laboratory first. Architecture should remain as simple as possible **without weakening evidence integrity or security**.
