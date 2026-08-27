# BrandForge work breakdown

This is the implementation ledger for the project. Checked items are present in this repository;
credentialed checks stay open until they run in the owner's accounts.

## 1. Product and domain

- [x] Define campaign, brief, rules, plan, variants, approvals, feedback, assets, and export models.
- [x] Implement explicit workflow states, terminal states, and legal transitions.
- [x] Add optimistic concurrency and reproducibility metadata.
- [x] Make campaign state and its outbox event one atomic database transaction.

## 2. Agent system

- [x] Implement structured agent contracts with tools, budgets, timeouts, and escalation rules.
- [x] Implement brand compiler, planner, creative studio, critics, and reranker.
- [x] Keep policy-sensitive state transitions in deterministic application code.
- [x] Record observable decisions and tool calls without storing hidden model reasoning.

## 3. OpenAI and multimodal path

- [x] Route server-side text generation through the OpenAI Responses API.
- [x] Generate only the three shortlisted images through GPT Image.
- [x] Run image-to-brief scoring through a vision-capable Responses model.
- [x] Add per-campaign call and estimated-cost limits.
- [x] Keep a deterministic no-key provider for CI and demonstrations.
- [ ] Run the held-out benchmark with the owner's OpenAI project, billing, and model access.

## 4. Human review

- [x] Add brand-rule, strategy, variant-selection, and final-approval gates.
- [x] Store reviewer identity, role, artifact version, comments, and reason codes.
- [x] Store pairwise preference examples without automatically training on raw clicks.
- [x] Regenerate new variant IDs after requested final changes.

## 5. Product interfaces

- [x] Build a typed FastAPI API with health, campaign, upload, review, image, event, and cancel routes.
- [x] Build and production-compile a responsive Next.js review control room.
- [x] Add idempotency keys, trace IDs, structured errors, and tenant-scoped lookups.
- [x] Export editable Instagram, email, web, and presentation SVGs plus a provenance manifest.
- [ ] Verify the feature-flagged Adobe Express handoff with an approved Adobe client ID/domain.

## 6. Security and storage

- [x] Validate upload sizes, magic bytes, MIME types, filenames, and object keys.
- [x] Detect instruction-like text in untrusted brand documents.
- [x] Validate human-supplied palette corrections before SVG rendering.
- [x] Add SQLite, PostgreSQL, local object storage, S3, and tenant RLS boundaries.
- [x] Keep OpenAI and Firefly secrets out of browser-visible variables.
- [ ] Add malware scanning, isolated document rendering, OIDC, and real role provisioning before launch.

## 7. Evaluation and release engineering

- [x] Ship 120 reproducible scenarios and four system ablations.
- [x] Report quality, safety, calls, and latency with an explicit synthetic-fixture disclaimer.
- [x] Add 90 tests, provider-independent core coverage, Ruff, mypy, and dependency audits.
- [x] Add container builds, locked web dependencies, CI, Dependabot, SBOMs, and provenance attestations.
- [ ] Collect human judgments and repeat live-model runs before claiming portfolio lift.

## 8. Local and cloud operations

- [x] Add Docker Compose for API, UI, PostgreSQL/pgvector, MinIO, and the outbox worker.
- [x] Add optional Temporal and OTel/Tempo/Prometheus/Grafana profiles.
- [x] Add AWS Terraform for private networking, ECS, RDS, S3, IAM, autoscaling, and secrets.
- [x] Document failure modes, threat boundaries, provider outage response, and deployment sequence.
- [ ] Add TLS, WAF, OIDC, alarms, remote Terraform state, and restore drills for production.

## 9. Multimodal retrieval and curated preferences

- [x] Add normalized embedding contracts and deterministic/OpenCLIP/remote providers.
- [x] Add bounded SQLite and pgvector/HNSW repositories with tenant and policy filtering.
- [x] Index approved images, document chunks, campaign copy, and selected completed visuals.
- [x] Add campaign-scoped text/image search, status, backfill, reranking, and trace provenance.
- [x] Add versioned relevance judgments and synthetic retrieval metric reports.
- [x] Freeze selection features and add explicit reviewer curation plus tenant-safe datasets.
- [x] Add grouped and brand-held-out splits, versioned Bradley-Terry artifacts, and evaluation.
- [x] Add isolated multimodal services, configuration, commands, tests, and documentation.
- [ ] Replace synthetic fixtures with held-out, human-reviewed relevance and preference datasets.
