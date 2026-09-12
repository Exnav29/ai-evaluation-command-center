# AI Evaluation Command Center

**AI Evaluation Command Center (AECC)** is an open-source system for testing AI models on real engineering work, preserving the evidence, and determining what each model is actually good enough to do.

The goal is not to find one universal "best model."

The goal is to answer a more useful question:

> **Which model, in which setup, is proven to handle this kind of work reliably, at an acceptable cost and level of supervision?**

AECC is being built toward an evidence-based control system for an AI engineering workforce.

## Why I started this

I use AI models heavily in day-to-day development work.

Over time, I kept noticing something that bothered me:

**The benchmark rankings and my actual experience did not always agree.**

A newly released model might arrive with outstanding benchmark scores, yet struggle with an engineering task I expected it to handle easily. Meanwhile, another model — sometimes a much cheaper model, or even a free one — could quietly complete the same type of work very well.

Most benchmarks are useful, but they do not always answer the question that matters to someone actually building software:

> **Can this model reliably do my work?**

Public benchmarks are also known targets. Model developers know which benchmarks matter, and models can be optimized around them. That does not make those benchmarks useless, but benchmark performance and real-world usefulness are not necessarily the same thing.

AECC exists to investigate the second one.

## The token problem

There is another issue becoming increasingly noticeable for people using AI development tools heavily: **token fatigue**.

Agentic development can consume enormous amounts of context and tokens. A coding agent may inspect dozens of files, reread a repository, call tools, retry failed approaches, generate and revise code, run tests, debug failures, hand work to another model, and repeat the cycle.

Frontier models can be extremely capable, but using the most expensive model for every step can become costly very quickly.

So I started asking a different question:

> **Do I really need a frontier model for every task?**

Maybe the better approach is not one extremely powerful model doing everything. Maybe it is a team.

A lower-cost model might be excellent at routine backend implementation. Another may be stronger at visual design. Another may be good at debugging. A frontier model may be worth calling only when the cheaper model fails, when the work becomes ambiguous, or when deeper reasoning is required.

That is the research direction AECC is exploring. It is a hypothesis to test, not a conclusion the project assumes in advance.

## The core idea

Instead of asking:

> **What is the best AI model?**

AECC asks:

> **What is the best proven model for this particular type of work?**

The long-term goal is an evidence-based AI engineering workforce where models can be treated as specialists.

For example:

- one model may prove strong at backend architecture;
- another may excel at API implementation;
- another may be effective at frontend development;
- another may be useful for visual design;
- another may be the right inexpensive choice for routine debugging;
- a stronger model may be reserved for escalation.

A model does not earn a role because of reputation, price, or leaderboard position.

**It earns the role by producing evidence.**

## Evidence before claims

AECC is built around a few strict principles:

- **UNKNOWN is never treated as PASS.**
- Missing evidence is not silently converted into zero.
- Failed runs remain part of the record.
- Retries remain part of the record.
- Human intervention is recorded.
- Escalation to a stronger model is recorded.
- Demo evidence is kept separate from real qualification evidence.
- Evaluation criteria are defined before results are known.
- Model identity is preserved exactly.
- Work setup matters.
- Qualification is specific to the type of work being tested.
- A model that succeeds in one environment does not automatically inherit that result elsewhere.

AECC would rather say:

> **We don't know yet.**

than manufacture confidence the evidence does not support.

## Machine facts, human judgment, AI explanation

AECC separates different kinds of evidence instead of pretending they are interchangeable.

**Machine-observed facts** — such as exact model identity, timestamps, exit state, elapsed time, artifacts, retry counts, and preserved output — are recorded deterministically wherever possible.

**Human judgments** — such as rubric scoring — are explicitly attributed to an evaluator and rubric version. A numeric rubric result is a record of how that particular artifact was scored; it is not automatically a measurement of permanent model ability.

**AI explanation** may help interpret evidence, but it should not silently rewrite either machine-observed facts or attributed human judgments.

> **Facts by software. Judgments attributed. Explanations by AI. Evidence before authority.**

## Model + Work Setup + Skill

AECC does not treat a model name alone as the evaluated object.

The actual identity of an evaluated setup includes:

**Work Setup + Provider + Exact Model + Configuration**

The same underlying model running through two different coding harnesses may behave differently. Evidence collected through one setup should not automatically be transferred to another.

Likewise, success at one skill does not automatically prove success at another. A model may be excellent at `backend.api_implementation` and poor at `frontend.visual_design`.

AECC is designed to preserve those distinctions.

## What works today, what is in development, and what is planned

| Area | Status | What that means today |
| --- | --- | --- |
| Model and capability registry | **Working on `main`** | Exact provider/model identity, capability catalog, active/inactive stewardship, and historical evidence identity are implemented. |
| Versioned test registry | **Working on `main`** | Logical tests and versioned definitions can be registered and preserved. |
| OpenCode execution adapter | **Working on `main`** | AECC can execute registered work through OpenCode. OpenCode is currently the implemented harness adapter. |
| Evidence persistence | **Working on `main`** | Runs, attempts, outputs, failures, intervention-related evidence, and provenance are preserved. |
| Comparison and qualification logic | **Working on `main`** | Deterministic logic derives comparison/qualification state from persisted evidence. UNKNOWN does not collapse into PASS, and demo evidence is excluded from real qualification by default. |
| Rubric scoring | **Human-attributed today** | Score revisions are entered as evaluator judgments with evaluator identity and rubric version. AECC does not currently automate rubric scoring. |
| Operator dashboard and charts | **Working on `main`** | The current server-rendered operator dashboard exposes evidence, comparison, qualification, registry, and reporting views. |
| V2 plain-language operator experience | **In development** | The product is moving toward the `ADD / TEST → COMPARE → CHOOSE → UNDERSTAND WHY` workflow. Not all V2 journeys are available on `main` yet. |
| Additional harness/provider discovery | **Planned / in development** | The architecture is intended to support more setups, but OpenCode is the implemented execution harness today. |
| Project recommendation and AI-team routing | **Planned** | Recommendations will require accumulated qualification evidence; thin evidence should remain UNKNOWN rather than being turned into routing confidence. |
| Public/demo exploration dataset | **Planned** | The repository has a location reserved for demonstration data, but a complete ready-to-explore public demo dataset is not shipped yet. |

## A current benchmark artifact

The strongest published benchmark artifact in the repository today is:

**[Phase 3 Foundation Implementation — Results](benchmarks/phase3-foundation-implementation-v1/RESULTS.md)**

That benchmark records the harness version, benchmark image, subject and evaluator commits, containment policy, rubric results, verification results, elapsed time, observed provider usage, sealed workspace SHA-256 values, and instrument limitations.

The published scores are **run scores** for those specific observed artifacts. They are not general measurements of permanent model capability, and that benchmark alone does not establish broad qualification.

## What AECC measures

Depending on the test, preserved evidence can include:

- task completion;
- acceptance criteria;
- attributed rubric scoring;
- failure classification;
- attempts;
- human intervention;
- escalation;
- execution time;
- token usage;
- cost;
- exact model identity;
- exact test version;
- exact work setup;
- preserved output;
- qualification history.

The goal is to eventually answer questions like:

- Which models are strongest for a specific class of work?
- Which models need the least supervision?
- Which inexpensive models perform surprisingly well?
- Which tasks consistently require stronger models?
- How often does a model need escalation?
- What does successful completion actually cost?
- Which models have accumulated enough evidence to be trusted with a particular class of work?

## Free and low-cost models

One research question is whether free and low-cost models can replace frontier models for some categories of work.

AECC does **not** begin with the assumption that cheaper models are better. They have to prove themselves under the same evidence rules.

The objective is not:

> Use the cheapest model possible.

The objective is:

> **Use the least expensive model that has earned the right to do the work, and escalate when the evidence says you should.**

Sometimes that may be a free model. Sometimes that may be a frontier model. Where the evidence is too thin, the correct result is still UNKNOWN.

## Quick Start

AECC is under active development, so this quick start is aimed at contributors who want to inspect the current application and run the test suite.

### Requirements

- Python 3.11 or newer
- Git

### Install

```bash
git clone https://github.com/Exnav29/ai-evaluation-command-center.git
cd ai-evaluation-command-center
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[test]"
```

The `test` extra is intentional: `httpx` is required by the test suite.

### Run the tests

```bash
pytest -q
```

### Start the current operator dashboard

```bash
uvicorn aecc.web:app --reload
```

Then open:

`http://127.0.0.1:8000/operator`

By default AECC uses `data/evaluations.sqlite` and applies pending migrations when the application starts. You can override the database path with `AECC_DB_PATH`.

### About executing evaluations

Cloning the repository is enough to inspect the application and run its tests, but **real model execution is not yet a one-command public quick start**.

The execution worker currently supports OpenCode and expects registered test fixtures under a server-owned fixture root. `AECC_FIXTURES_ROOT` defaults to `<repo>/fixtures`, and that fixture collection is not currently shipped as a ready-to-run public evaluation pack.

That limitation is intentional to state plainly rather than implying that a fresh clone can immediately reproduce every private or historical execution.

## What AECC is not

AECC is not intended to be another generic model leaderboard.

It is also not designed to declare one model the winner across every category. A model may be excellent at one type of work and poor at another.

A failed evaluation is useful evidence. An UNKNOWN result is useful evidence. A model requiring human intervention is useful evidence. Knowing when **not** to use a model is often just as valuable as knowing when to use it.

## Reproducibility

A major goal is for another builder to be able to understand and, where public fixtures permit, reproduce:

1. what was tested;
2. which exact model and work setup were used;
3. which test and rubric versions were used;
4. what happened during execution;
5. how the artifact was scored;
6. what conclusions the evidence does and does not support.

Evaluation methodology and scoring rules are version-controlled so changes remain auditable.

## Current product direction

The V2 product direction is:

**ADD / TEST → COMPARE → CHOOSE → UNDERSTAND WHY**

The intended operator journeys are:

1. **Home / Work-Area Guidance**
2. **Add a New Model**
3. **Test a Model**
4. **Compare / Rankings**
5. **Help Me Choose**
6. **Understand Why**

These are product-direction targets. The current `main` branch should be treated according to the status table above, not as if every V2 journey is already complete.

## Current development workflow

AECC is also being used to experiment with AI-assisted software development itself.

Development work is tracked through structured GitHub issues, implementation branches, automated tests, pull requests, review cycles, rework, and escalation.

The intent is to preserve not just resulting code, but evidence about which AI model performed work, how many attempts were required, whether review found defects, how much rework was required, whether escalation was necessary, and when human judgment entered the process.

## Project status

**Active development. Expect change.**

AECC has reached the point where there is real software and real evidence to inspect, but it is not a finished product.

Current work includes improving the operator experience, expanding real-world test packs, model discovery through coding harnesses, richer comparisons, qualification progression, project-level recommendations, better cost/intervention analysis, additional harness/provider support, and stronger development/review automation.

## I want people to challenge this

This repository is public because I do not want AECC to become an evaluation system that only confirms my own assumptions.

Useful participation includes:

- proposing real-world engineering tests;
- testing additional models;
- reproducing existing evaluations;
- questioning scoring rules;
- testing rubric reliability and evaluator consistency;
- finding flaws in the methodology;
- improving the user experience;
- identifying misleading conclusions;
- contributing provider or harness support;
- suggesting better ways to measure model usefulness;
- showing cases where benchmark reputation and real-world performance diverge.

If AECC produces a conclusion that the evidence does not support, I want that challenged.

## Contributing

Contribution guidelines are available in **[CONTRIBUTING.md](CONTRIBUTING.md)**.

Issues and discussions around methodology, testing ideas, model behavior, bugs, UX, architecture, reproducibility, and evidence interpretation are welcome.

## Repository contents

This repository contains the AECC application, including the evaluation engine, operator dashboard, schemas, registries, scoring methodology, benchmark/test definitions, execution adapter code, agent skills, tests, documentation, and published benchmark artifacts.

It intentionally does **not** contain production credentials, private API keys, live private evaluation databases, unsanitized private model output, private operational artifacts, or VPS-specific secrets.

## Methodology

Relevant methodology and architecture documents are maintained under `docs/`, with version-controlled prompts and evaluation definitions elsewhere in the repository.

Important starting points include:

- `docs/COMMAND_CENTER_V1_SPEC.md`
- `docs/PLANNING_RUBRIC_V1.md`
- `benchmarks/phase3-foundation-implementation-v1/RESULTS.md`
- `prompts/`

## Roadmap

The broad direction is:

**Working Command Center → AI Workforce Intelligence → Recommendation / Routing → Public Research**

### 1. Working Command Center

Reliable evaluation infrastructure, model registry, test registry, execution, evidence preservation, attributed scoring, comparison, and qualification.

### 2. AI Workforce Intelligence

Determine which exact setups are proven for which kinds of work, while measuring cost, intervention burden, escalation, reliability, and execution characteristics.

### 3. Recommendation and Routing

Given a real project, recommend an AI team only where qualification evidence is sufficient. UNKNOWN must remain a valid answer.

### 4. Public Research

Publish sanitized findings, reproducible methodology, comparative evidence, and datasets that other builders can challenge and reproduce.

## Independence

AECC is an independent evaluation effort.

It is not intended to promote a particular model vendor, provider, coding harness, or pricing tier.

If an expensive frontier model wins, AECC should show that.

If a free model wins, AECC should show that.

If the evidence is mixed, AECC should show that.

If there is not enough evidence:

**We don't know yet.**

That is a valid result.

## License

Licensed under the Apache License 2.0.
