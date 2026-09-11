# Phase 3 Operator Dashboard V1 Closeout

**Rubric:** `docs/OPERATOR_DASHBOARD_V1_RUBRIC.md` v1.0
**Benchmark freeze:** `benchmarks/phase3-operator-dashboard-v1/FREEZE.json`
**Closeout state:** READY TO MERGE
**Selected implementation:** `phase3/operator-dashboard-muse`

## Candidate Comparison

| Candidate | Score | Band | Automated evidence | Decision |
| --- | ---: | --- | --- | --- |
| `opencode/muse-spark-1.3-contributor-free` | **97/100** | EXCELLENT | Preserved run: 41 passed, 2 warnings | Selected |
| `opencode/mimo-v2.5-free` | **92/100** | EXCELLENT | Preserved run: 43 passed, 2 warnings | Preserved benchmark evidence |

Both runs used OpenCode 1.18.30, the same frozen source commit, the same benchmark image, rootless containment, restricted provider egress, no automatic retries, and single-model attribution. Neither run had human implementation assistance. A score is not a qualification decision.

## Final Rubric Scores

| Rubric dimension | Max | Muse | MiMo |
| --- | ---: | ---: | ---: |
| Dashboard functionality and evidence drill-down | 20 | 20 | 20 |
| Evidence semantics and query correctness | 20 | 20 | 18 |
| Operator UX, visual hierarchy, accessibility | 15 | 14 | 13 |
| Automated verification quality | 15 | 15 | 15 |
| Web/database engineering quality | 10 | 9 | 8 |
| Tool, skill, and subagent judgment | 10 | 9 | 8 |
| Scope discipline | 5 | 5 | 5 |
| Demo/fixture quality and realism | 5 | 5 | 5 |
| **Total** | **100** | **97** | **92** |

### Scoring basis

- **Muse:** All required routes, persisted-evidence queries, deterministic latest/history handling, exact triple-key qualification, explicit UNKNOWN/missing-value semantics, HTTP tests, semantic HTML, responsive CSS, and edge-case fixtures are present. The one-point deductions are for minor operational debt: import-time database migration and dependency deprecation warnings, plus a deliberately horizontally scrollable wide evidence table on narrow screens.
- **MiMo:** Required routes and rendered verification passed, with strong HTTP coverage and realistic fixtures. Deductions reflect the weaker evidence-model implementation documented in the benchmark record, less maintainable dependency choices, and the same minor responsive/deprecation debt. Its initial fixture/test failures were corrected within the preserved single attempt and remain part of the evidence history.

No hard finding from rubric section 8 was observed. UNKNOWN is not PASS, process exit 0 is not task success, and historical score/qualification evidence remains visible.

## Selection

Muse is the selected Phase 3 implementation. It provides the cleaner, more maintainable dashboard integration on the adopted Phase 2 evidence foundation, while preserving exact harness/model/capability identity and evidence lineage. MiMo is not discarded, rewritten, or treated as a failed benchmark; its complete run artifacts remain preserved for comparison and future evaluation.

## Validation Evidence

- Fresh automated verification in the frozen benchmark image: `python -m pytest -q` -> **41 passed, 2 warnings, 0 failures**.
- Host verification status: `python -m pytest -q` could not start because this host has no `python` executable; `python3` has no pytest. This is an environment limitation, not a substitute result. The container verification above is the relevant fresh result.
- Fresh read-only browser sanity check against the Muse branch and seeded preview database:
  - `/operator` rendered 200 with semantic navigation/table structure and newest-first runs.
  - `/operator/qualifications` rendered 200 with exact harness/model/capability rows, current state, history, and evidence links.
  - `/operator/runs/3` rendered 200 with attempt, permission denial, intervention, failure classification, and evidence sections.
  - The existing automated suite separately verifies known detail 200 and unknown run 404.
- Browser review findings are non-blocking: wide evidence tables use horizontal overflow on narrow viewports; the runtime emits two Starlette/httpx deprecation warnings.

## Scope and Evidence Integrity

- Implementation changed paths are limited to `pyproject.toml`, dashboard source, templates/static assets, and dashboard tests. This closeout report is the only additive closeout path.
- Frozen rubric/spec/prompt/validator/freeze files are unchanged.
- No queue, worker, model launching, containment, authentication, Stakeholder/Public, charting, or Product Studio work was added; these remain out of scope.
- Preserved candidate evidence was not modified.
- `~/work/product-studio-ops` was not accessed.

## Preserved Evidence Locations

- Muse: `runs/evaluations/phase3-operator-dashboard-v1/muse-spark-1.3-contributor-free/attempt-001/`
- MiMo: `runs/evaluations/phase3-operator-dashboard-v1/mimo-v2.5-free/attempt-001/`
- Frozen methodology: `benchmarks/phase3-operator-dashboard-v1/FREEZE.json`, `docs/OPERATOR_DASHBOARD_V1_RUBRIC.md`, `docs/OPERATOR_DASHBOARD_V1_SPEC.md`
- Muse archive SHA-256: `a667747db0b7887d76cff6e5858cb561760387a4c7fe9925f8684a684b3b5e2c3`
- MiMo archive SHA-256: `dd660514dd9dc99309cc5c9abebef8a84d2282af810c8946b0d6200937d4aee3`

## Recommended Git Integration

Run from `/home/johnathan/work/opencode-eval`:

```bash
git fetch origin
git switch main
git pull --ff-only origin main
git merge --no-ff phase3/operator-dashboard-muse -m "Integrate Phase 3 Muse operator dashboard"
podman run --rm -v "$PWD:/workspace:Z" -w /workspace \
  localhost/aecc-dashboard-runner:v1 python -m pytest -q
git diff --check HEAD^ HEAD
git status --short
git push origin main
```

Do not merge the MiMo artifact into the product branch. Keep its ignored run directory and archive intact as benchmark evidence. Phase 3 is **ready to merge**, subject to the receiving maintainer running the commands above and confirming the final merge diff contains only the selected Muse implementation plus this closeout report.
