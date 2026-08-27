# Failure analysis

## Failures the current system catches

| Failure | Control | Test/evaluation evidence |
|---|---|---|
| Off-brand palette | Deterministic palette critic | Seeded first-output benchmark failures |
| Unsupported guarantee | Claims critic and final approval | 17.5% baseline violation rate falls to zero after rerank |
| Prompt injection in guide | Untrusted-instruction detector and strict rule schema | Security and compiler tests |
| Cross-tenant campaign read | Repository tenant guard; RLS migration for production | Persistence test |
| Stale concurrent update | Optimistic version check | Persistence test |
| Invalid gate skip | Explicit state-transition table | State-machine and workflow tests |
| Duplicate outbox delivery | Stable event ID and idempotent insert | Persistence test |
| Crash between state and event writes | Aggregate and outbox event share one transaction | Atomic-outbox tests |
| Model-call explosion | Per-campaign call and cost budgets | Gateway tests |
| Path traversal | Leaf filename and object-key validation | Security tests |
| Approval after modification | Revised plan/variant IDs and versions | Final-revision workflow test |

## Known breakpoints

### Visual-only brand guides

The compiler extracts embedded PDF text and simple text signals. A scanned PDF, logo-clear-space
diagram, custom font specimen, or color shown only as pixels can be missed. The system warns when
structured signals are absent but needs OCR, layout extraction, and logo/color vision models.

### Judge calibration

An OpenAI vision score can be consistent and still disagree with a creative director. The judge
needs a calibration set with reviewer labels, inter-rater agreement, per-brand thresholds, and
drift checks. Brand policy must remain deterministic where it can be measured.

### External provider partial failure

Core state and successful prior steps persist, but the default HTTP endpoint still performs the
funnel synchronously. A request timeout can leave the campaign in retryable-failure state without
an automatic retry. Temporal activities, resumable step IDs, and a status-polling UI are the next
production change.

### Image URL lifetime

Firefly can return short-lived URLs. The current Firefly adapter exposes the returned URL but does
not ingest it immediately into private object storage. Production must download from an allowlisted
Adobe host, verify content, hash it, and store it before the URL expires.

### Preference bias

Click and selection feedback is not automatically training data. Misclicks, experiment exposure,
reviewer seniority, exceptional legal overrides, and position bias can corrupt a preference model.
Only curated feedback is eligible for training.

### Authentication boundary

Header auth is convenient locally and unsafe on a public endpoint. The infrastructure defaults to
private access, but a real deployment still needs validated OIDC claims, authorization tests, and
separate service roles.

## Failure-injection demo

Use the sample guide, then add an instruction-like line asking the system to reveal secrets. The
brand compiler should show a warning without executing it. In the deterministic benchmark, some
first candidates receive a magenta/cyan palette or a guarantee; the reranker should remove them
from first place. Request final changes and verify that new variant IDs are created and the old
approval is not reused.
