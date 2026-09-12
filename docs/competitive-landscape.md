# AECC Competitive Landscape

**Research date:** 2026-09-12  
**Scope:** coding-agent evaluation, agent-evaluation infrastructure, evidence/provenance, model qualification, and model routing.

This document is a point-in-time research note, not a claim that the market is exhaustively covered. Product capabilities change quickly. Claims below are tied to public documentation or papers available at the research date.

## Executive summary

AECC sits at the intersection of three increasingly mature categories:

1. **Execution and evaluation harnesses** — systems that run tasks, capture traces/artifacts, and score outcomes.
2. **Evidence and experiment platforms** — systems that preserve evaluation results, compare experiments, and monitor quality.
3. **Model routers** — systems that select among models based on predicted quality, cost, latency, policy, or request difficulty.

The market is already strong in all three categories. AECC should therefore avoid positioning itself as uniquely able to run realistic tasks, preserve traces, compare models, or route requests cheaply.

The more defensible differentiation is the **qualification layer** between evaluation and routing:

> **AECC turns accumulated evidence into earned authority for an exact AI worker setup.**

The intended chain is:

**Evidence → Qualification → Decision / Routing**

An execution system may produce the evidence. A router may consume a list of eligible workers. AECC's distinctive role is deciding which exact setups have earned eligibility for which kinds of work, under what supervision and escalation conditions, while preserving UNKNOWN when the evidence is insufficient.

---

## 1. Academic validation of the setup-identity thesis

### Claw-SWE-Bench

**Source:** https://arxiv.org/abs/2606.12344

Claw-SWE-Bench evaluates OpenClaw-style coding harnesses under controlled conditions. The paper reports that changing the harness while holding models fixed can materially change Pass@1, and that systems with similar accuracy can differ substantially in API cost.

**Why it matters to AECC:**

This independently supports AECC's principle that a model name by itself is not a sufficient evidence identity. Harness behavior belongs in the evaluated configuration.

**AECC implication:**

Keep exact setup identity as a first-class key:

**Work Setup + Provider + Exact Model + Configuration + Capability**

Do not collapse evidence across harnesses merely because the underlying base model is the same.

### Harness-Bench

**Source:** https://arxiv.org/abs/2605.27922

Harness-Bench evaluates realistic agent workflows across multiple harness configurations and model backends. It records final artifacts, execution traces, usage statistics, and validator outputs, and argues that capability should be reported at the model-harness configuration level rather than attributed only to the base model.

**Why it matters to AECC:**

This is very close to AECC's evidence-identity philosophy and reinforces the value of preserving not just outputs but execution context and process evidence.

**AECC implication:**

The setup identity is not merely implementation metadata. It is part of the capability claim.

### CoEval

**Source:** https://arxiv.org/abs/2606.03650

CoEval addresses the problem of ranking models for custom tasks when standard public benchmarks may be contaminated or poorly matched to the target workload. It generates fresh, domain-targeted evaluations from a task description and uses a cross-family judge ensemble.

**Why it matters to AECC:**

It supports the broader argument that public benchmark leadership does not automatically answer whether a model is fit for a specific real-world workflow.

**AECC implication:**

AECC should continue emphasizing workload-specific evidence, but should not claim that "real work instead of benchmarks" is unique. Others are solving that problem too.

---

## 2. Execution and evaluation harnesses

### Coder Eval — UiPath

**Sources:**

- https://github.com/UiPath/coder_eval
- https://coder-eval.com/docs
- https://github.com/UiPath/coder_eval/blob/main/docs/agents/OPENCODE.md
- https://github.com/UiPath/coder_eval/blob/main/docs/agents/CLAUDE_CODE.md

Coder Eval is the closest software comparison found in this research to AECC's execution/evaluation layer.

Public documentation shows support for multiple coding agents, including Claude Code, Codex, Antigravity, and OpenCode. It includes sandboxed execution, declarative task definitions, weighted criteria, continuous scoring, early-stop behavior, telemetry, token/cost accounting, A/B experiments, and an evaluation UI.

**Where Coder Eval appears stronger today:**

- multiple harnesses rather than a single OpenCode adapter;
- mature sandbox/execution plumbing;
- richer automated criterion types;
- extensive telemetry normalization;
- documented quick-start and task schema;
- CI-oriented evaluation workflow.

**Where AECC is pursuing a different problem:**

Coder Eval evaluates tasks and produces scores/results. AECC is building a persistent qualification model around accumulated evidence, intervention, escalation, UNKNOWN, and earned authority.

**Strategic conclusion:**

AECC should investigate Coder Eval as a possible evidence producer rather than automatically duplicating every execution feature.

### aau-harness

**Source:** https://pypi.org/project/aau-harness/

The package describes itself as a reproducible harness for tool-using LLM agents with seeded worlds, exact scoring, measured cost, repeated runs with confidence intervals, and provenance on every result.

**Why it matters:**

It already addresses two areas that AECC still needs to strengthen:

- repeated-run statistics;
- explicit uncertainty/confidence reporting around repeated executions.

**Strategic conclusion:**

Do not reinvent repeat-run statistical machinery without first evaluating whether AECC can consume evidence from aau-harness or borrow its statistical design.

### Promptfoo

**Sources:**

- https://www.promptfoo.dev/docs/getting-started/
- https://www.promptfoo.dev/docs/integrations/ci-cd/
- https://github.com/promptfoo/promptfoo

Promptfoo provides declarative evaluation, model/provider comparison, CI/CD integration, quality gates, cost tracking, security testing, and a web UI.

**Why it matters:**

Promptfoo demonstrates how mature the generic LLM-evaluation layer already is. It also makes clear that simple "compare several models with a declarative config" functionality is not a durable AECC differentiator.

**Strategic conclusion:**

AECC should focus engineering effort on evidence semantics and qualification, not recreating broad generic prompt-evaluation features unless they are required by the qualification system.

---

## 3. Evidence and experiment platforms

### LangSmith

**Source:** https://docs.langchain.com/langsmith/evaluation

LangSmith supports offline and online evaluation, datasets, human/code/LLM evaluators, repetitions, experiment comparison, production traces, and feedback loops from production failures back into evaluation datasets.

**Why it matters:**

It is strong evidence that experiment management, repeated evaluation, trace analysis, and production feedback loops are already established product categories.

**AECC opening:**

AECC's opportunity is not merely to preserve experiments. It is to translate accumulated evidence into explicit work authorization and supervision policy.

### Braintrust

**Sources:**

- https://www.braintrust.dev/docs/evaluate
- https://www.braintrust.dev/docs/evaluate/run-evaluations

Braintrust supports systematic evaluation, immutable experiment snapshots, experiment comparison, online scoring, production traces, cost analysis, and continuous evaluation.

**Why it matters:**

Braintrust's immutable experiment concept overlaps with AECC's evidence-preservation goals. It is another reason AECC should be precise about its differentiation.

**AECC opening:**

The qualification state machine — especially UNKNOWN, accumulated evidence, intervention burden, and escalation history — remains the more distinctive layer.

---

## 4. Model routing market

Routing is already crowded. AECC should not position generic cost/quality routing as a unique destination.

### RouteLLM

**Source:** https://github.com/lm-sys/RouteLLM

RouteLLM is an open framework for serving and evaluating routers that decide between stronger and weaker models. It uses learned routing strategies and configurable thresholds to trade cost against quality.

**Key distinction from AECC:**

RouteLLM predicts which model should answer a request. AECC's intended qualification layer asks which models have accumulated enough evidence to be eligible for a class of work in the first place.

### Not Diamond

**Sources:**

- https://docs.notdiamond.ai/docs/what-is-model-routing
- https://docs.notdiamond.ai/docs/router-training-quickstart
- https://docs.notdiamond.ai/docs/routing-between-custom-models

Not Diamond routes queries among candidate models to optimize quality, cost, or latency. Its custom router can be trained on user-supplied evaluation data, including custom models or arbitrary inference endpoints.

This is an important competitive finding because it weakens any claim that routers only use generic request-time heuristics. Not Diamond can learn from a customer's own evaluation results.

**What still appears different:**

Its routing input is evaluation-score data used to train a prediction model. AECC is pursuing an explicit persistent qualification record with states, evidence provenance, intervention/escalation history, and UNKNOWN as a first-class outcome.

**Positioning caution:**

Do not claim that "nobody routes from evaluation evidence." That claim is too strong.

A safer distinction is:

> AECC is exploring explicit evidence-gated eligibility and earned authority before routing optimization occurs.

### Microsoft Foundry Model Router

**Sources:**

- https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/model-router
- https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/model-router

Microsoft Foundry offers prompt-time model routing with Balanced, Quality, and Cost modes and configurable model subsets. Microsoft recommends evaluating the router against a baseline on quality, cost, and latency using a representative workload.

Notably, its guidance recommends at least 100 prompts for statistically reliable workload evaluation and says fewer than 30 prompts provide only directional signal.

**Why it matters to AECC:**

This reinforces the need to keep recommendation/qualification thresholds conservative and to avoid broad capability claims from one or two runs.

### TrueFoundry Auto Routing

**Sources:**

- https://www.truefoundry.com/blog/llm-routing-cost-quality-aware-model-selection
- https://www.truefoundry.com/blog/engineering/llm-cost-routing-benchmark/

TrueFoundry describes cost-aware routing as selecting the cheapest model that clears a quality bar for the task and explicitly identifies determining that quality bar as the hard problem. It has also published measured routing results over thousands of calls showing substantial cost savings while retaining most baseline quality, while also documenting quality degradation when prompt-difficulty classification is wrong.

**Why it matters to AECC:**

This gets very close to AECC's economic thesis. The opening is not the idea of using a cheaper model when it is sufficient. The opening is how "sufficient" is established and governed over time.

### Portkey

**Sources:**

- https://portkey.ai/docs/product/ai-gateway
- https://portkey.ai/docs/product/ai-gateway/fallbacks
- https://portkey.ai/docs/product/ai-gateway/load-balancing

Portkey provides gateway-level routing, conditional routing, fallbacks, retries, circuit breakers, load balancing, canary testing, budgets, and tracing.

**Why it matters:**

This is infrastructure AECC should not attempt to duplicate without a compelling qualification-specific reason.

**Potential future relationship:**

AECC could theoretically provide a qualified candidate set or policy output to a gateway/router such as Portkey rather than becoming the gateway itself.

---

## 5. Competitive matrix

| System / research | Primary layer | Real task execution | Multiple harnesses/models | Preserved traces/artifacts | Repeated-run statistics | Cost tracking | Qualification / earned authority | Routing |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **AECC** | Qualification/control | Yes, current OpenCode path | Model variation; one execution harness today | Yes | Early / incomplete | Yes | **Core direction** | Planned |
| Claw-SWE-Bench | Research benchmark | Yes | Yes | Benchmark evidence | Benchmark-level analysis | Yes | No | No |
| Harness-Bench | Research benchmark | Yes | Yes | Yes | Large trajectory corpus | Usage stats | No | No |
| CoEval | Custom evaluation | Synthetic/domain tasks | Yes | Evaluation outputs | Large generated evals | Yes | No | No |
| Coder Eval | Execution/eval harness | Yes | **Yes** | **Yes** | Experiment-oriented | **Yes** | No explicit earned-authority model found | No |
| aau-harness | Execution/eval harness | Yes | Provider/backend support | Provenance/receipts | **Yes, confidence intervals** | **Yes** | No explicit qualification state machine found | No |
| Promptfoo | General eval/security | Yes, depending on task/provider | Yes | Results/reports | Configurable | Yes | Quality gates, not earned work authority | No |
| LangSmith | Eval/observability | Yes via application/agent | Yes | **Yes** | **Repetitions supported** | Trace-level | No explicit earned-authority layer found | No |
| Braintrust | Eval/observability | Yes via evaluated app | Yes | **Immutable experiments** | Experiment support | **Yes** | No explicit earned-authority layer found | No / adjacent |
| RouteLLM | Routing | No execution harness focus | Yes | Router evaluation data | Benchmark evaluation | Cost-quality threshold | No | **Core** |
| Not Diamond | Routing | No execution harness focus | Yes | User evaluation data | Depends on supplied data | Cost/latency aware | No explicit stateful qualification layer found | **Core** |
| Microsoft Foundry Model Router | Routing | No | Managed model pool | Router telemetry | Workload evaluation guidance | **Yes** | Policy-gated candidate pool, not task qualification | **Core** |
| TrueFoundry | Gateway/routing | No | Yes | Gateway observability | Published benchmark studies | **Yes** | Quality thresholds, not persistent earned authority | **Core** |
| Portkey | Gateway/routing | No | Yes | **Tracing** | Operational rather than qualification-focused | **Yes** | Policy/config gates | **Core** |

**Important:** "No explicit qualification state machine found" means this research did not find a directly comparable public mechanism. It is not proof that no such feature exists.

---

## 6. What appears genuinely differentiating for AECC

The research weakens several possible positioning claims:

- "We evaluate real work." — not unique.
- "We preserve traces and artifacts." — not unique.
- "We measure cost." — not unique.
- "We compare cheap and expensive models." — not unique.
- "We route to cheaper capable models." — heavily crowded.
- "Harness choice matters." — now academically established, but not unique.

The stronger differentiation is the combination of:

1. **Exact evaluated-worker identity** rather than model name alone.
2. **UNKNOWN as a first-class result** rather than treating missing evidence as failure or success.
3. **Persistent qualification state** derived from accumulated evidence.
4. **Intervention burden as evidence.**
5. **Escalation history as evidence.**
6. **Infra failure separated from model-quality failure.**
7. **Demo/synthetic evidence prevented from silently qualifying production workers.**
8. **Earned authority:** a worker is eligible for a task because its exact setup has met an evidence threshold.
9. **Routing only after qualification:** cost/latency optimization occurs among already-qualified candidates.

A concise positioning statement is:

> **AECC is the qualification and evidence-control layer between AI evaluation and AI routing.**

Or, more operationally:

> **Evaluation tells you what happened. AECC is being built to decide what an AI worker has earned the right to do next.**

---

## 7. Architectural implication: make execution pluggable

The research strongly suggests that AECC should not assume its own execution worker must eventually become the best generic harness in the market.

A better boundary may be an **Evidence Producer Adapter** contract.

A compatible producer should be able to supply or preserve at least:

- exact harness identity and version;
- provider and exact model identifier;
- configuration identity;
- test/task identity and version;
- source/fixture/workspace identity;
- raw output;
- final artifacts;
- execution trace or equivalent event record;
- elapsed time;
- token and cost accounting when available;
- retries/attempts;
- permission/tool failures;
- infrastructure failures distinctly from model failures;
- human intervention markers;
- provenance hashes or immutable artifact references.

AECC should remain responsible for translating this evidence into comparison, qualification, readiness, and recommendation state.

This boundary would allow the project to test integrations with Coder Eval, aau-harness, or future execution systems without surrendering AECC's evidence semantics.

---

## 8. Backlog candidates surfaced by this research

These are research-derived backlog candidates, not all immediate commitments.

### High priority

#### A. Define an Evidence Producer Adapter specification

Create a formal schema/contract for external execution systems to submit evidence without controlling AECC qualification semantics.

**Why:** avoids rebuilding commodity execution infrastructure and allows Coder Eval/aau-harness feasibility testing.

#### B. Run a paid frontier model through the sealed Phase 3 benchmark

Use the same harness, task, containment, rubric, and evidence policy as the existing free-model runs.

**Why:** produces a measured free-vs-frontier cost/performance artifact instead of relying on theoretical savings claims.

#### C. Add repeated-run support with uncertainty reporting

At minimum preserve repeated runs per exact setup/test and report distribution or confidence information where statistically appropriate.

**Why:** aau-harness already demonstrates this pattern, and Microsoft recommends much larger workload samples before drawing reliable routing conclusions.

#### D. Define qualification evidence thresholds explicitly

Document the minimum evidence required to move from UNKNOWN to a qualified/readiness state for each class of capability.

**Why:** the recommendation layer becomes dangerous if thin evidence can create apparent authority.

### Medium priority

#### E. Evaluate Coder Eval as an external evidence producer

Perform a bounded architecture spike. Do not adopt it automatically.

Questions:

- Can AECC preserve exact harness/model/config identity?
- Can it obtain raw artifacts/traces?
- Can infra failures stay separate?
- Can AECC own retry policy or at least observe it precisely?
- Can human intervention be represented?
- Can AECC ignore Coder Eval's scoring semantics when necessary and apply its own qualification policy?

#### F. Evaluate aau-harness statistical/provenance design

Study whether its repeated-run/confidence/provenance machinery can be integrated, adapted, or reproduced minimally.

#### G. Cross-harness same-model experiment

Run the same model/task through two harnesses when a second harness is available.

**Why:** directly tests the setup-identity thesis inside AECC rather than citing external research only.

#### H. Qualification confidence and evidence sufficiency model

Separate:

- run score;
- evidence volume;
- repeatability;
- evaluator/rubric reliability;
- intervention burden;
- qualification decision.

Avoid collapsing these into one synthetic "confidence" number without a transparent policy.

### Later / strategic

#### I. Router output contract

Define a future interface where AECC outputs an eligible candidate set plus qualification evidence, while a gateway/router performs runtime optimization.

This keeps AECC out of commodity gateway concerns such as provider failover, load balancing, caching, and circuit breaking.

#### J. Production-outcome feedback loop

Investigate how downstream failures, human corrections, incidents, or support tickets should feed back into qualification state.

**Why:** request-time evaluation can miss failures that only appear after real use.

#### K. Public reproducible fixture pack

Ship at least one complete public fixture/task pack so a fresh clone can reproduce a real evaluation path rather than only run unit tests and inspect historical artifacts.

---

## 9. Positioning guidance

### Claims AECC can make carefully

- Harness/setup identity materially affects measured agent capability; recent academic work supports that premise.
- AECC treats the exact setup, not merely the model family, as the evaluated worker identity.
- AECC is designed to preserve UNKNOWN rather than manufacture readiness from missing evidence.
- AECC records intervention and escalation as evidence rather than hiding them.
- AECC's long-term routing concept is qualification-gated: optimize only among workers that have already met an evidence bar.

### Claims AECC should avoid

- "No other system evaluates real-world tasks."
- "No router uses evaluation data."
- "AECC is the only system that preserves evidence or provenance."
- "A low-cost model is proven better than a frontier model" without comparable controlled runs.
- "A model is qualified" based on a single benchmark run unless the qualification policy explicitly supports that narrow scope.

---

## 10. Research sources

### Academic

- Claw-SWE-Bench — https://arxiv.org/abs/2606.12344
- Harness-Bench — https://arxiv.org/abs/2605.27922
- CoEval — https://arxiv.org/abs/2606.03650

### Evaluation / execution

- Coder Eval — https://github.com/UiPath/coder_eval
- Coder Eval docs — https://coder-eval.com/docs
- aau-harness — https://pypi.org/project/aau-harness/
- Promptfoo — https://www.promptfoo.dev/docs/getting-started/
- LangSmith Evaluation — https://docs.langchain.com/langsmith/evaluation
- Braintrust Evaluation — https://www.braintrust.dev/docs/evaluate

### Routing / gateways

- RouteLLM — https://github.com/lm-sys/RouteLLM
- Not Diamond routing — https://docs.notdiamond.ai/docs/what-is-model-routing
- Not Diamond custom router — https://docs.notdiamond.ai/docs/router-training-quickstart
- Microsoft Foundry Model Router — https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/model-router
- Microsoft model-router evaluation guidance — https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/model-router
- TrueFoundry cost/quality routing — https://www.truefoundry.com/blog/llm-routing-cost-quality-aware-model-selection
- TrueFoundry measured routing benchmark — https://www.truefoundry.com/blog/engineering/llm-cost-routing-benchmark/
- Portkey AI Gateway — https://portkey.ai/docs/product/ai-gateway

---

## Bottom line

The research does not invalidate AECC. It narrows the valuable part of the project.

Execution harnesses are becoming sophisticated. Evaluation platforms already preserve experiments and traces. Routing is crowded.

The less crowded problem is the one AECC has been moving toward:

> **How does an organization convert messy, repeated, real-world AI performance evidence into a defensible decision about what an exact AI worker is allowed to do?**

That is where AECC should concentrate its product identity and engineering discipline.

---

## 11. Selected university research relevant to AECC

This section adds research from MIT, Stanford, UCLA, and Texas A&M that is directly useful to AECC's qualification, evaluation, and routing design. These are not included because of institutional prestige alone; each item is here because it changes or strengthens a concrete AECC design decision.

### MIT

#### 2025 AI Agent Index

**Sources:**

- https://aiagentindex.mit.edu/
- https://arxiv.org/abs/2602.17753
- https://doi.org/10.1145/3805689.3806728

The 2025 AI Agent Index, with MIT-affiliated coauthors Stephen Casper and A. Pinar Ozisik, documents 30 prominent deployed agents across technical capabilities, autonomy, ecosystem interaction, safety, evaluation, and impact. One of its most relevant conclusions for AECC is that model-level evaluation is insufficient for agentic systems because downstream tools, scaffolding, autonomy, and deployment context materially shape system behavior. It also identifies a large transparency gap: many highly autonomous agents disclose little or no agent-specific safety evaluation.

**AECC implication:**

AECC's exact-worker identity should continue to include the surrounding agent system, not only the base model. Qualification should eventually capture autonomy level, tool permissions, and safety evidence as part of readiness, especially when authority increases.

**Backlog candidate:**

Add an **authority-risk dimension** to qualification policy so higher-autonomy workers require stronger evidence and safety checks before being granted broader execution authority.

#### ABxLab / AI agents are sensitive to nudges

**Sources:**

- https://abxlab.media.mit.edu/
- https://www.media.mit.edu/publications/ai-agents-are-sensitive-to-nudges/

MIT Media Lab's ABxLab uses controlled modifications to the environment presented to an AI agent and measures how those changes alter decisions. The work shows that agent behavior can shift substantially when seemingly small environmental cues change.

**AECC implication:**

Qualification based only on one frozen task presentation may overstate robustness. Some capabilities should include perturbation testing: alternate wording, UI state, ordering, defaults, or environmental cues while preserving the underlying task.

**Backlog candidate:**

Add **robustness/perturbation variants** to selected qualification suites and distinguish ordinary repeated runs from controlled environment-variation runs.

#### Science of scaling agent systems

**Source:** https://www.media.mit.edu/projects/towards-a-science-of-scaling-agent-systems-when-and-why-agent-systems-work/overview/

MIT Media Lab reports controlled evaluation across 180 agent configurations and finds that multi-agent coordination can improve performance on parallelizable tasks while degrading it on sequential tasks. The broader lesson is that system architecture itself is task-dependent.

**AECC implication:**

The future "AI team" recommendation layer should not assume that adding more agents or specialists is always beneficial. Team topology itself should become an evaluated configuration.

**Backlog candidate:**

Treat **agent-team architecture** as part of exact setup identity for multi-agent evaluations and require evidence before recommending multi-agent orchestration for a capability.

### Stanford

#### HELM and HELM Capabilities

**Sources:**

- https://crfm.stanford.edu/helm/
- https://crfm.stanford.edu/helm/capabilities/

Stanford CRFM's HELM emphasizes reproducible, transparent evaluation across scenarios, metrics, and models, with prompt-level transparency and reproducible results.

**AECC implication:**

AECC's public research path should expose enough item-level evidence that outsiders can inspect not only aggregate conclusions but the underlying evaluation instances, subject to privacy and safety constraints.

#### Reliable and Efficient Amortized Model-Based Evaluation

**Source:** https://crfm.stanford.edu/2025/06/04/reliable-and-efficient-evaluation.html

Stanford researchers integrated Item Response Theory-based adaptive testing into HELM. Their work shows that model evaluation can be made substantially cheaper by selecting the most informative test items while preserving reliability.

**AECC implication:**

Qualification does not necessarily require running every test on every worker forever. Once AECC has enough calibration data, it may be possible to select tests adaptively while keeping evidence quality explicit.

**Backlog candidate:**

Investigate **adaptive qualification testing** and stopping rules after the basic repeated-run/evidence-sufficiency model is mature. Do not implement adaptive shortcuts before the full-test baseline is trustworthy.

#### Deployment Decision Reliability

**Sources:**

- https://aimslab.stanford.edu/cs321m
- https://arxiv.org/abs/2608.11323

A Stanford AIMS project applies Generalizability Theory to long-horizon agent benchmarks and reports that the agent main effect accounts for less than 3% of variance in the analyzed datasets while agent-by-task interaction accounts for substantially more. Its central warning is that aggregate leaderboards can look like measures of universal capability when they are often measuring specialization and task interaction.

**AECC implication:**

This strongly supports capability-specific qualification rather than a single global model rank. It also argues for reporting evidence sufficiency and reliability at the capability/task-family level.

**Backlog candidate:**

When AECC has enough repeated data, evaluate whether a **variance-decomposition / generalizability analysis** can inform the number and diversity of tasks required before a qualification claim is defensible.

#### Measurement Data Bank

**Source:** https://aimslab.stanford.edu/measurement-db

Stanford's Measurement Data Bank focuses on item-level AI measurement data: what a system was tested on, how it responded, and how each response was scored.

**AECC implication:**

This is relevant to the Evidence Producer Adapter. AECC should prefer item-level evidence exchange over importing only final aggregate scores.

### UCLA

#### PM-Bench: Evaluating Prospective Memory in LLM Agents

**Sources:**

- https://arxiv.org/abs/2607.12385
- https://samueli.ucla.edu/people/67993/

PM-Bench, by UCLA researchers Genglin Liu and Saadia Gabriel, evaluates prospective memory: whether an agent can preserve and execute delayed intentions while other work continues. It evaluates eight models under eight agent configurations; even the strongest reported setup reaches only 65.1% F1.

**AECC implication:**

Long-horizon reliability is not captured by ordinary one-shot coding tasks. A worker can be strong at immediate implementation while weak at remembering deferred obligations or responding correctly to later state changes.

**Backlog candidate:**

Create a future **long-horizon / deferred-obligation capability family** for agents expected to maintain commitments across multi-step workflows.

#### Preference Leakage in LLM-as-a-Judge

**Sources:**

- https://arxiv.org/abs/2502.01534
- https://llm-as-a-judge.github.io/

This ICLR 2026 work, which includes UCLA affiliation, finds that LLM judges can systematically favor outputs from related model families, including the same model, inherited models, or related families. That creates a contamination channel in automated evaluation.

**AECC implication:**

If AECC adds LLM-based scoring, evaluator identity must include model family/provenance, and judge independence should be part of the evaluation policy rather than an implementation afterthought.

**Backlog candidate:**

Define an **LLM-judge independence policy** before automated scoring is introduced: record judge model identity, prohibit or flag same-family judge/subject pairings where appropriate, and preserve human or deterministic verification paths for consequential qualification decisions.

#### Rethinking Creativity Evaluation

**Source:** https://aclanthology.org/2026.eacl-long.297/

UCLA-affiliated authors show that common creativity metrics, including LLM-as-a-Judge, can disagree across domains and can be sensitive to small prompt variations and label biases.

**AECC implication:**

Evaluation instruments should be capability-specific. A metric that works for one kind of task should not silently become the scoring standard for another.

**Backlog candidate:**

Require each capability family to declare its **evaluation instrument and validity assumptions**, rather than relying on a universal scoring mechanism.

#### UCLA uncertainty and distribution-shift work

**Source:** https://dts.ucla.edu/initiatives/ai/pilot-projects

A UCLA AI pilot describes using conformal prediction and real-time monitoring to quantify uncertainty and detect distribution shift in VLM-based robot motion planning, with human feedback after execution.

**AECC implication:**

Qualification should not be treated as permanent if the operating environment changes materially. The evidence that justified authority can go stale.

**Backlog candidate:**

Design a future **qualification freshness / drift policy** that can lower confidence, trigger re-evaluation, or suspend authority when the deployment distribution or worker configuration changes materially.

### Texas A&M

#### AgentFlow — Stanford + Texas A&M

**Source:** https://agentflow.stanford.edu/

AgentFlow is a Stanford/Texas A&M collaboration accepted as an ICLR 2026 Oral. It studies in-the-flow optimization of agentic systems across diverse benchmarks, reinforcing that agent-system configuration and orchestration can matter as much as base-model choice.

**AECC implication:**

Evidence identity should eventually extend naturally from a single harness/model setup to richer agentic system configurations. Qualification should be attached to the system actually used, not retroactively attributed to the underlying model.

**Backlog candidate:**

Extend the future Evidence Producer Adapter schema so it can represent **multi-component agent systems** without flattening them into one model identifier.

#### Grounded engineering agents and benchmark development

**Source:** https://news.engineering.tamu.edu/news/2026/09/07/texas-am-researchers-develop-ai-tools-for-a-changing-power-grid/

Texas A&M researchers describe Grid Agent and Circuit AI as systems that combine LLM reasoning with trusted engineering software, validated calculations, and specialized data rather than accepting model-generated answers by themselves. The team is also developing standardized benchmark tasks for evaluating such systems.

**AECC implication:**

For verifiable engineering domains, deterministic or domain-tool verification should outrank LLM opinion whenever possible. This aligns directly with AECC's principle that exit code 0 is not task success and that machine-checkable evidence should be preferred over unsupported model judgment.

**Backlog candidate:**

Create a verifier hierarchy for test definitions: **deterministic/domain-tool checks first, attributed human judgment second when needed, LLM judge only where appropriate and explicitly identified.**

#### LLM-as-a-judge bias study

**Source:** https://ugr.tamu.edu/_files/_documents/2526urssymposiumabstractbook.pdf

A 2026 Texas A&M undergraduate research project tested prompt-based bias mechanisms in LLM-as-a-Judge evaluation using more than 540 objective and 20 semi-objective pairwise evaluations. It found generally high accuracy but still observed answer flips, mechanism-specific weaknesses, and early evidence of order sensitivity.

**AECC implication:**

This is weaker evidence than a peer-reviewed publication, but it points in the same direction as the stronger UCLA preference-leakage and evaluation-robustness work: automated judges should be treated as measurement instruments with failure modes, not as ground truth.

### Cross-university synthesis

Taken together, these university results strengthen AECC in six specific ways:

1. **System identity over model identity.** MIT, Stanford, UCLA, and Texas A&M work all provide examples where agent configuration, task interaction, orchestration, or environment changes measured behavior.
2. **Capability-specific qualification over global ranking.** Stanford's reliability work and UCLA's domain-sensitive evaluation results argue strongly against collapsing performance into one universal model score.
3. **Measurement instruments need qualification too.** UCLA and Texas A&M work on LLM judges reinforces AECC's decision to preserve evaluator identity and measure rubric/judge reliability.
4. **Authority should scale with evidence and risk.** MIT's Agent Index highlights increasing autonomy and weak safety disclosure, supporting stronger qualification bars for higher-authority workers.
5. **Qualification can decay.** UCLA's distribution-shift work suggests that evidence sufficiency should eventually include freshness and deployment drift.
6. **Execution architecture itself can be a capability variable.** MIT's multi-agent scaling work and Stanford/Texas A&M's AgentFlow both support evaluating the full system configuration rather than assigning success to a base model alone.

### New backlog candidates from the university review

These are additions to the backlog candidates above, not commitments to build immediately:

#### L. Authority-risk tiers

Require stronger evidence, safety verification, and intervention history before granting workers higher-autonomy or higher-impact authority.

#### M. Robustness / perturbation test variants

Add controlled environment, wording, ordering, or UI-state perturbations to selected qualification suites.

#### N. Adaptive qualification testing research

After a trustworthy full-suite baseline exists, study IRT/adaptive-testing methods to reduce evaluation cost without hiding evidence loss.

#### O. LLM-judge independence policy

Record judge provenance and explicitly manage same-model/same-family contamination risk.

#### P. Long-horizon / prospective-memory capability pack

Add tests for deferred obligations, latent state changes, and commitments that must survive intervening work.

#### Q. Qualification freshness and drift

Define when previously earned authority should be revalidated because the worker, harness, tools, environment, or workload distribution changed.

#### R. Verification hierarchy

Prefer deterministic and domain-tool verification where available; preserve human judgment explicitly; use LLM judges only as attributed instruments with known limitations.

#### S. Multi-agent setup identity

Represent team topology, component models, roles, coordination mechanism, and configuration as part of the evaluated worker identity when AECC begins qualifying AI teams.

### University research sources

- MIT AI Agent Index — https://aiagentindex.mit.edu/
- MIT 2025 AI Agent Index paper — https://arxiv.org/abs/2602.17753
- MIT ABxLab — https://abxlab.media.mit.edu/
- MIT agent-systems scaling project — https://www.media.mit.edu/projects/towards-a-science-of-scaling-agent-systems-when-and-why-agent-systems-work/overview/
- Stanford HELM — https://crfm.stanford.edu/helm/
- Stanford reliable/efficient evaluation — https://crfm.stanford.edu/2025/06/04/reliable-and-efficient-evaluation.html
- Stanford Deployment Decision Reliability — https://arxiv.org/abs/2608.11323
- Stanford Measurement Data Bank — https://aimslab.stanford.edu/measurement-db
- UCLA PM-Bench — https://arxiv.org/abs/2607.12385
- UCLA-affiliated Preference Leakage — https://arxiv.org/abs/2502.01534
- UCLA-affiliated creativity-evaluation study — https://aclanthology.org/2026.eacl-long.297/
- UCLA uncertainty/distribution-shift pilot — https://dts.ucla.edu/initiatives/ai/pilot-projects
- Stanford/Texas A&M AgentFlow — https://agentflow.stanford.edu/
- Texas A&M grounded engineering agents — https://news.engineering.tamu.edu/news/2026/09/07/texas-am-researchers-develop-ai-tools-for-a-changing-power-grid/
- Texas A&M LLM-judge bias study — https://ugr.tamu.edu/_files/_documents/2526urssymposiumabstractbook.pdf
