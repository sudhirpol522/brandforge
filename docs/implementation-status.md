# Implementation status

This document prevents the portfolio demo from overstating what the repository proves.

## Working and locally verified

- Dependency-free end-to-end campaign workflow with every human gate.
- SQLite and in-memory persistence, optimistic concurrency, outbox, and tenant rejection.
- Deterministic brand compiler, planner, creative generator, critics, reranker, preference model,
  stored visual fixtures, editable SVG export, and provenance manifest.
- 90 tests, provider-independent core coverage, and the full 120-scenario benchmark.
- FastAPI routes pass end-to-end API tests; the locked Next.js 16 production build and strict
  TypeScript check pass.
- OpenAI adapter uses the official SDK, Responses for text/vision, Images for rendering, store
  disabled for Responses, and server-only environment credentials.
- S3, PostgreSQL, Firefly, OpenCLIP, Temporal, OTel, and AWS adapters are isolated from core code.
- SQLite/pgvector multimodal retrieval, approved-source indexing, text/image query APIs, policy
  reranking, and explicitly synthetic retrieval evaluation reports.
- Frozen reviewer comparisons, explicit curation, leakage-safe splits, versioned Bradley-Terry
  artifacts, and explicitly synthetic preference evaluation reports.

## Credential or platform dependent

- Real OpenAI generations require account access, billing, model access, and OPENAI_API_KEY.
- GPT Image use may require organization verification.
- Adobe Firefly requires Firefly Services credentials.
- Adobe Express requires a browser client ID, HTTPS allowed domain, and Adobe business approval.
- Docker image pulls and dependency installation require network access.
- Terraform creates real billable AWS resources and was not applied while packaging this project.

## Intentionally incomplete production work

- The API executes the creative funnel synchronously. Move generation into Temporal activities or
  a job API before exposing it to slow providers or large traffic.
- The Temporal coordinator is feature-flagged and demonstrates durable approval signals; the
  default API still uses the database-backed state machine directly.
- Development authentication trusts headers. Production needs OIDC/JWT verification or a trusted
  identity proxy. Terraform therefore defaults to an internal load balancer.
- Upload validation checks size, magic bytes, and type. A ClamAV or managed malware scanner and
  isolated PDF/SVG renderer must run before real customer files are normalized.
- PDF text extraction does not perform OCR. Scanned guides need an isolated OCR worker.
- OpenAI vision judgments have not been calibrated against human brand reviewers.
- The curated preference pipeline works, but no real human-curated pairwise dataset ships with
  this repository.
- Cost guards use configured per-call estimates, not provider invoice reconciliation.
- Adobe Express handoff is feature-flagged and needs credentialed end-to-end verification.
- RLS SQL requires separate application and BYPASSRLS worker roles; do not run both with the RDS
  owner used by initial Terraform bootstrapping.
- No publishing connector exists. Export is the highest-authority action.

## Interview-ready next experiment

Collect at least 300 reviewer comparisons across 50 held-out briefs, train the pairwise model,
calibrate the vision judge, and repeat each OpenAI condition at least three times. Report bootstrap
confidence intervals, reviewer agreement, cost per approved campaign, p50/p95 latency, and failure
categories. Only then write a quantified résumé bullet.
