# Phase 3 Foundation Implementation — Results

**Benchmark:** `phase3-foundation-implementation-v1`  
**Subject source commit:** `af395e4d65fa377b62f04402d499dc93f6ca8cf5`  
**Evaluator commit:** `302e3ee6e94b7787f391348f69e00e7cbbd148b6`  
**Harness:** OpenCode 1.18.30  
**Benchmark image ID:** `21e9d92c42355e04aa5d5b9542bcaad5eeadb9991b47d9988a069b237e90bdae`  
**Execution policy:** rootless Podman containment, restricted egress through allowlisted proxy, no automatic retries, no human implementation assistance.

## Decision

Muse Spark 1.3 Contributor Free is selected as the implementation baseline for the database/evidence foundation. This is an implementation-selection decision, not a blanket qualification of the model for all work. Both models remain benchmark evidence.

| Model | Rubric score | Band | Elapsed | First output | Independent verification | Cost |
| --- | ---: | --- | ---: | ---: | --- | ---: |
| `opencode/muse-spark-1.3-contributor-free` | **99/100** | EXCELLENT | 190.617 s | 3.150 s | 21 passed | $0.0000 |
| `opencode/mimo-v2.5-free` | **90/100** | EXCELLENT | 245.134 s | 3.076 s | 38 passed | $0.0000 |

Approximate provider usage observed during the runs was ~1.418M total tokens for Muse and ~1.007M for MiMo. These totals include repeated/growing agent context and should not be interpreted as unique source tokens read.

## Muse findings

Muse produced the stronger relational evidence model. In particular, qualification decisions use explicit relational evidence links to runs and/or attempts, capability identity supports `(capability_key, version)`, and historical evidence records have strong provenance. No hard-fail rubric finding was identified. The sealed workspace archive SHA-256 was:

`d11ec053594afea05327ed021a900a63439b1828e426403e0c82b8dc892e29cb`

During execution Muse encountered tool-level failures/denials and recovered without human assistance. The raw response remains the source of truth. The evaluator's derived `permission_denial_detected` boolean may under-detect OpenCode's wording and must not override the preserved raw response.

## MiMo findings

MiMo produced a sound implementation with strong behavioral testing and autonomous debugging. Its qualification evidence representation was weaker because supporting run IDs were stored as text rather than enforced relational links, and its capability-key uniqueness made capability versioning less natural. Several historical records also allowed weaker provenance anchoring. No hard-fail rubric finding was identified. The sealed workspace archive SHA-256 was:

`69bc04f77767d268368b9bec3e5833d4897a81b85bb163da4eb54f29b901438f`

MiMo initially had one failing test because the assertion expected SQLite to include a symbolic constraint name in the exception text. The database constraint itself worked. MiMo corrected the assertion, reran the suite, and independent verification passed.

## Standing interpretation

For `backend_database_engineering`, Muse is the leading standing candidate and MiMo is the secondary candidate. This benchmark alone does not establish permanent qualification. Qualification remains an evidence-based decision over accumulated runs for the exact harness + model + capability combination.
