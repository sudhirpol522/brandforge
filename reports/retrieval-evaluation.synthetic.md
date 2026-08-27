# BrandForge retrieval evaluation

Dataset: `synthetic` version `retrieval-synthetic-v1`.

> Synthetic smoke-test results. These are not human or production quality claims.

| Metric | Baseline | Reranked | Delta |
|---|---:|---:|---:|
| recall_at_10 | 1.0000 | 1.0000 | +0.0000 |
| recall_at_50 | 1.0000 | 1.0000 | +0.0000 |
| ndcg_at_10 | 0.5981 | 1.0000 | +0.4019 |
| mrr | 0.8333 | 1.0000 | +0.1667 |
| pairwise_accuracy | 0.2222 | 1.0000 | +0.7778 |
| policy_violation_rate | 0.2500 | 0.0000 | -0.2500 |

Queries: 3; judgments: 12.

Baseline latency p50/p95: 4.20/5.01 ms.

Reranked latency p50/p95: 6.80/7.34 ms.

Synthetic fixture metrics verify evaluation plumbing only and are not human-study or production retrieval evidence.
