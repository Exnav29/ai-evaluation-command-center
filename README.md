# AI Evaluation Command Center

**AI Evaluation Command Center (AECC)** is an open-source system for testing AI models on real engineering work, preserving the evidence, and determining what each model is actually good enough to do.

The goal is not to find one universal "best model."

The goal is to answer a more useful question:

> **Which model, in which setup, is proven to handle this kind of work reliably, at an acceptable cost and level of supervision?**

AECC is being built as an evidence-based control system for an AI engineering workforce.

## Why I started this

I use AI models heavily in day-to-day development work.

Over time, I kept noticing something that bothered me:

**The benchmark rankings and my actual experience did not always agree.**

A newly released model might arrive with outstanding benchmark scores, yet struggle with an engineering task I expected it to handle easily.

Meanwhile, another model — sometimes a much cheaper model, or even a free one — could quietly complete the same type of work very well.

That made me start questioning how we evaluate models.

Most benchmarks are useful, but they do not always answer the question that matters to someone actually building software:

> **Can this model reliably do my work?**

Public benchmarks are also known targets. Model developers know which benchmarks matter, and models can be optimized around them. That does not make those benchmarks useless, but it does mean benchmark performance and real-world usefulness are not necessarily the same thing.

AECC exists to measure the second one.

## The token problem

There is another issue becoming increasingly noticeable for people using AI development tools heavily: **token fatigue**.

Agentic development can consume enormous amounts of context and tokens. A coding agent may inspect dozens of files, repeatedly reread a repository, call tools, retry failed approaches, generate and revise code, run tests, debug failures, hand work to another model, and repeat the cycle.

Frontier models can be extremely capable, but using the most expensive model for every step can become costly very quickly.

So I started asking a different question:

> **Do I really need a frontier model for every task?**

Maybe the better approach is not one extremely powerful model doing everything. Maybe it is a team.

A lower-cost model might be excellent at routine backend implementation. Another may be stronger at visual design. Another may be good at debugging. A frontier model may be worth calling only when the cheaper model fails, when the work becomes ambiguous, or when deeper reasoning is required.

That is the direction AECC is exploring.

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

## Model + Work Setup + Skill

AECC does not treat a model name alone as the evaluated object.

The actual identity of an evaluated setup includes:

**Work Setup + Provider + Exact Model + Configuration**

For example, the same underlying model running through two different coding harnesses may behave differently. Evidence collected through one setup should not automatically be transferred to another.

Likewise, success at one skill does not automatically prove success at another. A model may be excellent at `backend.api_implementation` and poor at `frontend.visual_design`.

AECC is designed to preserve those distinctions.

## What AECC measures

AECC is intended to evaluate more than whether a model eventually produced something that looked correct.

Depending on the test, evidence can include:

- task completion;
- acceptance criteria;
- correctness;
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

- Which models are best for backend work?
- Which models need the least supervision?
- Which inexpensive models perform surprisingly well?
- Which tasks consistently require frontier models?
- How often does a model need escalation?
- What does successful completion actually cost?
- Which models are reliable enough to be trusted with a particular class of work?

## Free and low-cost models

One area of particular interest is whether free and low-cost models can replace frontier models for some categories of work.

AECC does **not** begin with the assumption that cheaper models are better. They have to prove themselves.

But if a free model reliably performs a task that would otherwise consume expensive frontier-model tokens, that is meaningful.

The objective is not:

> Use the cheapest model possible.

The objective is:

> **Use the least expensive model that has earned the right to do the work, and escalate when the evidence says you should.**

Sometimes that may be a free model. Sometimes that may be a frontier model.

**The evidence decides.**

## Current product direction

The operator experience is being rebuilt around a simpler workflow:

**ADD / TEST → COMPARE → CHOOSE → UNDERSTAND WHY**

The six primary operator journeys are:

1. **Home / Work-Area Guidance**
2. **Add a New Model**
3. **Test a Model**
4. **Compare / Rankings**
5. **Help Me Choose**
6. **Understand Why**

The goal is to make AECC understandable to someone who should not need to know its internal evaluation terminology. Technical evidence remains available, but the primary experience should answer practical questions first.

## What exists today

AECC is still under active development, but it is already working software.

Current capabilities include:

- model registry;
- capability registry;
- versioned test definitions;
- exact provider/model identity;
- isolated evaluation execution;
- preserved runs and attempts;
- deterministic scoring;
- comparison views;
- qualification logic;
- evidence history;
- demo-versus-real evidence separation;
- failure classification;
- intervention and escalation tracking;
- cost and execution evidence;
- operator dashboards;
- visual reporting;
- automated regression testing.

The current V2 interface is actively being developed. Some areas are complete, while others are intentionally still shells awaiting their next implementation phase.

## What AECC is not

AECC is not intended to be another generic model leaderboard.

It is also not designed to declare one model the winner across every category. A model may be excellent at one type of work and poor at another.

AECC is designed to preserve that nuance.

It is also not intended to hide failure.

A failed evaluation is useful evidence.

An UNKNOWN result is useful evidence.

A model requiring human intervention is useful evidence.

Knowing when **not** to use a model is often just as valuable as knowing when to use it.

## Reproducibility

A major goal of the project is reproducibility.

Eventually, another builder should be able to:

1. clone the repository;
2. configure their own model providers and work setups;
3. run the same test;
4. inspect the evidence;
5. compare their result with someone else's;
6. challenge the conclusion if the evidence does not support it.

Evaluation methodology and scoring rules are version-controlled so changes remain auditable.

Synthetic demonstration data is used where appropriate so the application can be explored without exposing private operational evidence.

## Architecture principle

AECC separates facts from interpretation.

Deterministic software should establish facts whenever possible. AI may help explain those facts, but AI should not be allowed to quietly rewrite them.

That philosophy applies throughout the project:

> **Facts by software. Explanations by AI. Evidence before authority.**

## Current development workflow

AECC is also being used to experiment with AI-assisted software development itself.

Development work is tracked through structured GitHub issues, implementation branches, automated tests, pull requests, review cycles, rework, and escalation.

The intent is to preserve not just the resulting code, but also evidence about:

- which AI model performed the work;
- how many attempts were required;
- whether review found defects;
- how much rework was required;
- whether escalation was necessary;
- when human judgment entered the process.

That development evidence may eventually become useful AECC evaluation data in its own right.

## Project status

**Active development. Expect change.**

AECC has reached the point where there is something real to inspect and experiment with, but it is not a finished product.

Current work includes:

- improving the operator experience;
- expanding real-world test packs;
- model discovery through coding harnesses;
- richer model comparisons;
- project-level recommendations;
- qualification progression;
- better cost and intervention analysis;
- additional harness/provider support;
- stronger development and review automation.

Interfaces, schemas, and workflows may still evolve.

## I want people to challenge this

This repository is public because I do not want this to become an evaluation system that only confirms my own assumptions.

I want other builders to challenge it.

Useful participation includes:

- proposing real-world engineering tests;
- testing additional models;
- reproducing existing evaluations;
- questioning scoring rules;
- finding flaws in the methodology;
- improving the user experience;
- identifying misleading conclusions;
- contributing provider or harness support;
- suggesting better ways to measure model usefulness;
- showing cases where benchmark reputation and real-world performance diverge.

If AECC produces a conclusion that the evidence does not support, I want that challenged.

## Contributing

Contribution guidelines are being formalized. In the meantime, issues around methodology, testing ideas, model behavior, bugs, UX, architecture, and reproducibility are welcome.

A dedicated `CONTRIBUTING.md` will document the contribution workflow as the project opens further to outside participation.

## Repository contents

This repository contains the AECC application, including:

- evaluation engine;
- operator dashboard;
- schemas;
- model and capability registries;
- scoring methodology;
- benchmark and test definitions;
- execution adapters;
- agent skills;
- tests;
- documentation;
- synthetic demonstration data.

It intentionally does **not** contain:

- production credentials;
- private API keys;
- live private evaluation databases;
- unsanitized private model output;
- private operational artifacts;
- VPS-specific secrets.

## Methodology

Relevant methodology and architecture documents are maintained in the repository under `docs/`, along with version-controlled prompts and evaluation definitions.

Important project documents currently include:

- `docs/COMMAND_CENTER_V1_SPEC.md`
- `docs/PLANNING_RUBRIC_V1.md`
- architecture and execution specifications under `docs/`
- version-controlled prompts under `prompts/`

These will continue evolving as the methodology matures.

## Roadmap

The broad direction is:

**Working Command Center → AI Workforce Intelligence → Recommendation / Routing → Public Research**

### 1. Working Command Center

Reliable evaluation infrastructure, model registry, test registry, execution, scoring, evidence preservation, comparison, and qualification.

### 2. AI Workforce Intelligence

Determine which models are proven for which kinds of work.

Measure cost, intervention burden, escalation, reliability, and execution characteristics.

### 3. Recommendation and Routing

Given a real project, recommend an AI team based on actual evidence.

For example:

- backend architecture;
- backend implementation;
- frontend implementation;
- visual design;
- debugging;
- reasoning/review.

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
