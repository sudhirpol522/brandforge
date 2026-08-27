# BrandForge offline evaluation

- Scenarios: 120
- Dataset: brandforge-benchmark-v1
- Provider: deterministic-fixture
- Measured wall time in the packaged workspace: 0.6478 seconds
- Scope: reproducibility and failure-injection smoke benchmark

| System | Success | Final | Brand | Visual | A11y | Claim violations | Calls/task | p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| single_output | 61.7% | 0.836 | 0.869 | 0.845 | 0.863 | 17.5% | 2.0 | 1.3 |
| multi_agent_first | 61.7% | 0.836 | 0.869 | 0.845 | 0.863 | 17.5% | 16.0 | 1.3 |
| multi_agent_reranked | 100.0% | 0.893 | 1.000 | 0.841 | 0.990 | 0.0% | 16.0 | 1.3 |
| vision_reranked_review_ready | 100.0% | 0.877 | 0.967 | 0.862 | 0.990 | 0.0% | 22.0 | 6.4 |

Success requires final score at least 0.65, brand at least 0.70, accessibility at least 0.60,
and no unsupported-claim violation.

## Interpretation

The first-candidate baselines fail when the seeded fixture inserts a non-brand palette or a risky
claim. Generating more candidates without selecting them intelligently provides no quality lift
and increases calls from 2 to 16. Deterministic reranking rejects the injected failures. The final
stage adds a rendered-image critic and increases visual alignment, but its additional conservative
brand judgment lowers the aggregate score slightly.

This is an offline fixture test. Image, cost, and latency values do not represent OpenAI traffic.
Run scripts/run_evaluation.py to reproduce it. A real result requires held-out assets, actual
OpenAI calls, calibrated human judgments, repeated trials, and confidence intervals.
