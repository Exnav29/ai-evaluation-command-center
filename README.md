# AI Evaluation Command Center

An open-source laboratory for evaluating AI coding models and agent harnesses through reproducible, real-world engineering tasks.

## Why this exists

Model benchmarks rarely answer the question engineers actually have:

**Can this model and this coding harness reliably do my work?**

AI Evaluation Command Center is designed to test that question with controlled engineering tasks, preserved evidence, explicit scoring rubrics, model-to-model comparisons, and visual reporting.

The initial research program is evaluating whether OpenCode and free or low-cost models can reduce dependence on frontier models and other coding harnesses such as Codex and Claude Code.

The project is vendor-independent. A failed evaluation is useful evidence.

## Core principles

- Evidence before claims.
- UNKNOWN is never treated as PASS.
- Test criteria are registered before results are known.
- Failed runs, retries, exclusions, and human intervention are preserved.
- Model performance and harness performance are measured separately.
- Qualification is capability-specific and must be earned through evidence.
- Public findings should be reproducible without exposing private operational data.

## Three access planes

**Operator** — creates and runs evaluations, reviews private evidence, scores results, manages qualification, and controls publication.

**Stakeholder** — read-only access to detailed sanitized evidence, comparisons, methodology, and underlying data.

**Public** — public research findings, charts, methodology, comparisons, qualification summaries, and safe datasets.

Only the Operator plane has execution authority.

## What this repository contains

This repository contains the evaluation engine, dashboard source, schemas, methodologies, benchmark definitions, scoring rubrics, agent skills, tests, and synthetic demonstration data.

It intentionally does **not** contain live evaluation databases, raw private model output, credentials, unsanitized artifacts, or VPS-specific runtime information.

## Current status

The project is under active development.

The initial OpenCode environment has been established and multiple free models have passed basic connectivity tests. Formal planning and engineering benchmarks are now being conducted using preregistered specifications and scoring rubrics.

## Reproducing evaluations

The goal is for anyone to be able to clone this repository, configure their own models and harnesses, run the same or modified evaluations, and compare their findings with ours.

Synthetic demonstration data will be included so the dashboard can also be explored without API credentials or private evaluation results.

## Methodology

See:

- `docs/COMMAND_CENTER_V1_SPEC.md`
- `docs/PLANNING_RUBRIC_V1.md`
- `prompts/`

Evaluation methodology and scoring rules are version-controlled so changes remain auditable.

## Agent capabilities

The project uses curated upstream agent skills plus project-specific evaluation methodology skills. Installed skill sources and hashes are recorded to make evaluation environments reproducible.

## License

Licensed under the Apache License 2.0.

## Independence

This project is an independent evaluation effort. Results are intended to show what actually happened in our environment, including failures and limitations—not to promote a particular model, vendor, or coding harness.
