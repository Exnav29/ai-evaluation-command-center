---
name: product-studio-evaluation
description: Apply Product Studio's rules for evaluating OpenCode, Codex, Claude Code, free models, frontier models, qualification evidence, and the Evaluation Command Center. Use for any Product Studio model or harness benchmark, qualification decision, dashboard feature, or evaluation workflow.
---

# Product Studio Evaluation Laboratory

This repository is an independent laboratory for evaluating AI coding models and coding harnesses through real engineering work.

The purpose is not to promote OpenCode or any model.

A negative result is useful evidence.

## Primary research questions

Determine:

- Can OpenCode replace or materially reduce reliance on Codex and Claude Code?
- What percentage of useful engineering work can free models perform reliably?
- Which task categories still justify frontier-model escalation?
- Which free models perform best for which capabilities?
- How much performance comes from the model versus the harness?
- How much human intervention does each combination require?
- What are the speed and operational tradeoffs of free models?
- Which model/harness combinations earn authority for which tasks?

## Default model policy

Free models are the default evaluation target.

Frontier models may later be used for:

- difficult planning;
- architecture;
- escalation after defined failure;
- comparison baselines.

Any frontier-model use must be recorded as an escalation.

Cost alone is not sufficient justification for choosing a model.

Quality, latency, intervention burden, reliability and safety all matter.

## Qualification states

Authority is capability-specific.

Use states such as:

- UNQUALIFIED
- SHADOW
- QUALIFIED
- RESTRICTED
- NOT AUTHORIZED

A model may be QUALIFIED for documentation and UNQUALIFIED for shell modification.

Qualification must be based on accumulated evidence, not reputation or a single successful run.

## Three access planes

### Operator

Authenticated control plane.

May:

- create tests;
- select models and harnesses;
- launch evaluations;
- inspect private evidence;
- review prompts and artifacts;
- score runs;
- manage qualification;
- control publication.

Only the Operator plane may request execution.

### Stakeholder

Read-only evidence plane.

May expose:

- sanitized run details;
- scores;
- comparisons;
- methodology;
- underlying data;
- qualification evidence;
- selected artifacts.

Must not expose credentials, secrets or unsafe operational details.

Must not launch evaluations or modify evidence.

### Public

Internet-facing transparency plane.

May expose:

- methodology;
- aggregate findings;
- charts;
- model comparisons;
- harness comparisons;
- public datasets;
- qualification summaries;
- failures and limitations.

Must not expose:

- private prompts where inappropriate;
- credentials;
- environment variables;
- server reconnaissance;
- private repository contents;
- unrestricted logs;
- sensitive operational artifacts;
- execution controls.

## Publication boundary

Information may move outward only through explicit sanitization:

Operator → Stakeholder → Public

Execution authority must never flow backward from Stakeholder or Public.

Public input must never directly cause shell execution or model execution.

## Product philosophy

The Evaluation Command Center is a real product, not an internal engineering demo.

It should be understandable to a non-developer operator.

Favor:

- visual evidence;
- charts;
- comparisons;
- clear status;
- drill-down;
- underlying data access;
- responsive layouts;
- accessible design.

Every important chart should provide access to underlying values.

The interface should make these questions easy to answer:

1. Which model is performing best?
2. Which harness is performing best?
3. Which combinations fail most often?
4. Where is human intervention required?
5. How much slower are free models?
6. How often do we escalate to frontier models?
7. Which capabilities have earned qualification?
8. What evidence supports that qualification?

## Product Studio principles

Evidence before claims.

UNKNOWN never collapses to GREEN or PASS.

Human intervention must be recorded.

Failed tests remain evidence.

A model must not earn authority merely because it produced a convincing explanation.

Operational permissions must remain separate from model confidence.

## Special metrics

Track where practical:

- pass rate;
- pass-with-findings rate;
- failure rate;
- time to completion;
- time to first useful output where measurable;
- human intervention rate;
- retry rate;
- frontier escalation rate;
- model cost;
- operator time burden;
- qualification evidence count;
- failure category;
- tool-selection errors;
- scope violations.

A useful long-term metric is Frontier Escape Rate:

percentage of tasks that cannot be completed acceptably by the qualified free-model path and require a frontier model.

## Independence

Do not optimize tests to make OpenCode look good.

Do not optimize tests to make Codex or Claude Code look bad.

The laboratory should be capable of concluding that OpenCode is not suitable.

The laboratory should also be capable of concluding that frontier models remain necessary.

Let evidence determine the result.
