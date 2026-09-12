# Contributing to AI Evaluation Command Center

Thank you for your interest in AI Evaluation Command Center (AECC).

AECC is being built to answer a practical question:

> Which AI models are actually good enough to do which kinds of work?

The project is still under active development. That means contributions are welcome not only in code, but also in methodology, test design, model evaluation, reproducibility, UX, architecture, documentation, and criticism.

One of the goals of opening this repository is to make the evaluation process itself open to challenge.

If you think an AECC conclusion is wrong, the methodology is weak, a test is unfair, or a model is being evaluated incorrectly, that is useful feedback.

## Ways to contribute

You do not need to be a software developer to contribute.

Useful contributions include:

- proposing real-world engineering tasks for evaluation;
- testing additional AI models;
- reproducing existing results;
- challenging scoring or qualification rules;
- identifying benchmark bias or weak methodology;
- reporting bugs;
- improving the user experience;
- improving documentation;
- contributing new model providers or work setups;
- suggesting better ways to measure cost, supervision, reliability, or escalation;
- contributing analysis of where benchmark rankings differ from real-world performance.

## Start with an Issue

Before making a substantial code or methodology change, please open an Issue first.

Describe:

- the problem you are trying to solve;
- why you think it matters;
- your proposed approach;
- whether the change affects evaluation semantics, methodology, evidence, or only presentation;
- any assumptions you are making.

This helps prevent duplicated work and gives us a chance to discuss changes before significant effort is spent.

Small documentation fixes and obvious bug fixes may not require prior discussion.

## Evidence before claims

AECC is built around several rules that contributions must preserve.

### UNKNOWN is not PASS

Missing or insufficient evidence must remain unknown.

Do not convert missing values to zero, PASS, GREEN, or any other apparently successful state.

### Failure is evidence

Failed runs, retries, exclusions, review findings, intervention, and escalation are part of the record.

Do not remove inconvenient evidence simply because it makes a model or workflow look worse.

### Demo evidence is not production evidence

Synthetic or demonstration data must remain distinguishable from real evaluation evidence.

Demo results must not qualify a model for production work.

### Exact identity matters

Evaluation evidence belongs to the exact configuration that produced it.

That may include:

- work setup / harness;
- provider;
- exact model identifier;
- configuration;
- test version;
- capability or work type.

Do not silently transfer evidence from one setup to another.

### Evaluation criteria come before results

Tests and scoring criteria should be defined before the result is known.

Do not adjust a rubric merely to make a preferred model pass.

### Reproducibility matters

Where practical, another contributor should be able to understand:

- what was tested;
- which model was used;
- which setup was used;
- what the acceptance criteria were;
- what happened;
- how the result was scored.

## Real-world tests are encouraged

AECC is especially interested in tests that resemble actual work.

Good test candidates generally have:

- a clear task;
- realistic engineering context;
- explicit acceptance criteria;
- enough difficulty to expose meaningful differences between models;
- a result that can be evaluated without relying entirely on subjective opinion.

Examples may include:

- API implementation;
- bug fixing;
- database work;
- frontend implementation;
- visual design;
- refactoring;
- integration work;
- reasoning;
- instruction following;
- debugging;
- architectural planning.

If you propose a new test, explain why it represents useful real-world work.

## Model evaluations

Please do not submit model claims based only on reputation or a public benchmark.

Statements such as:

> Model X is the best coding model.

are not useful by themselves.

AECC is interested in statements such as:

> Model X completed this specific test through this work setup, under these conditions, with this result and this level of intervention.

A surprising result is welcome whether it favors a frontier model, a low-cost model, or a free model.

## Free and low-cost models

AECC has a particular interest in determining when inexpensive models can perform work that would otherwise be sent to expensive frontier models.

This does not mean the project is biased toward cheap models.

Low-cost and free models must earn qualification through evidence just like any other model.

The principle is:

> Use the least expensive model that has earned the right to do the work, and escalate when the evidence says you should.

## Pull requests

Keep pull requests focused.

A good pull request should explain:

- what problem it addresses;
- which Issue it relates to, if applicable;
- what changed;
- what was intentionally not changed;
- how the change was tested;
- any assumptions or limitations;
- whether evaluation semantics were affected.

Avoid combining unrelated refactoring, feature work, methodology changes, and visual changes into one pull request when they can reasonably be separated.

## Testing

Changes should include appropriate tests.

Before submitting a pull request, run the established repository test suite.

AECC currently uses containerized testing to avoid depending on host-specific Python environments.

Do not install host dependencies merely to make a test pass unless the project explicitly adopts that dependency.

If a test cannot be run, say so clearly in the pull request.

Do not report a test as passing if it was not actually executed.

## User interface changes

For significant UI changes:

- test populated-data behavior, not only empty states;
- check desktop and mobile layouts;
- avoid hiding UNKNOWN or missing information;
- keep technical evidence accessible even when the primary interface uses plain language;
- do not introduce visual summaries that imply confidence the underlying evidence does not support.

AECC should favor clarity over dashboard density.

## Security and private data

Never commit:

- API keys;
- access tokens;
- passwords;
- production credentials;
- live private evaluation databases;
- private customer data;
- unsanitized model output containing sensitive information;
- VPS-specific secrets.

If you believe sensitive information has been committed, report it immediately rather than attempting to conceal the history yourself.

## Development data

Do not delete, recreate, or silently rewrite evaluation databases or evidence stores as part of normal development work.

Tests should use isolated fixtures, temporary databases, or synthetic data.

Preserved evidence is part of the product.

## Architecture changes

Large architectural changes should begin with discussion.

Please open an Issue before replacing major subsystems, changing evidence semantics, altering qualification logic, or introducing a new framework.

A working system with understandable evidence is preferred over unnecessary architectural complexity.

## AI-generated contributions

AI-assisted contributions are welcome.

If an AI model materially performed the implementation, please identify the model and work setup when practical.

The important question is not whether AI was used.

The important questions are:

- What changed?
- Was it reviewed?
- Was it tested?
- Is the evidence trustworthy?

AI-generated code is held to the same standards as human-generated code.

## Review and rework

A pull request may require multiple review and rework cycles.

Review findings should be preserved rather than erased.

Repeated failure may result in escalation to:

- a stronger model;
- a different specialist;
- a human contributor;
- or, when appropriate, an outside expert.

This is intentional.

AECC treats intervention and escalation as useful evidence rather than something to hide.

## Respectful disagreement

Strong criticism of ideas, methodology, benchmarks, architecture, and conclusions is welcome.

Personal attacks are not.

Challenge the evidence.

Challenge the assumptions.

Challenge the design.

But keep discussion focused on the work.

## Project maturity

AECC is not finished.

Interfaces, schemas, workflows, test packs, and methodology may change as the project matures.

Contributors should expect active iteration.

Backward compatibility will be considered carefully where evidence integrity or reproducibility depends on it.

## Questions

If you are unsure where to begin, open an Issue describing what interests you.

Good starting points include:

- a model you want evaluated;
- a real engineering task you think should become a test;
- a result you want to reproduce;
- a methodology concern;
- a bug;
- a UX improvement;
- a provider or harness you would like supported.

## Final principle

AECC is not trying to prove that expensive models are overrated.

It is not trying to prove that free models are better.

It is trying to determine what the evidence actually supports.

If the evidence says a frontier model is required, we should say so.

If the evidence says a free model can do the work, we should say so.

If the evidence is insufficient:

> **We don't know yet.**

That is a valid result.
