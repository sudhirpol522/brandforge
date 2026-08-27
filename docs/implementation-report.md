# BrandForge Implementation Report

## Purpose

This document records the BrandForge work completed during the current implementation session.
It distinguishes verified behavior from optional integrations, local-development configuration,
and planned work that has not yet been implemented.

No credentials or secret values are included. The OpenAI API key remains server-side in the local
environment file and must never be copied into source code, documentation, browser variables, or
version control.

## Executive summary

BrandForge is now a working human-governed campaign creation application with:

- A FastAPI backend and Next.js review interface.
- A multi-stage campaign workflow with attributable human approval gates.
- OpenAI Responses API copy generation, image generation, and vision scoring.
- Deterministic offline providers for repeatable tests and evaluation.
- Diversity-aware multimodal reranking and preference-feedback capture.
- A native Fabric.js editor for completed campaign layouts.
- Versioned editable design persistence with optimistic concurrency.
- Automatic final-approval invalidation after a design changes.
- Editable SVG, PNG, JSON, and provenance exports.
- An optional Adobe Express handoff.
- SQLite/local object storage for direct local execution and PostgreSQL/S3-compatible adapters for
  production-oriented deployments.

The currently verified automated backend suite contains 90 passing tests. Strict TypeScript checks,
the Next.js production build, Ruff, provider-independent mypy checks, and IDE diagnostics also pass.

## System architecture

The primary application flow is:

```text
Brand guide and campaign brief
  -> Brand compiler
  -> Human brand-rule approval
  -> Campaign planner
  -> Human plan approval
  -> Eight text directions
  -> Deterministic critic scoring and diversity reranking
  -> Three generated visuals
  -> Vision scoring and final reranking
  -> Human variant selection
  -> Human final approval
  -> Editable campaign package
  -> Optional native editing
  -> Renewed final approval after edits
```

The API owns validation, state transitions, approvals, persistence, and authorization boundaries.
Agents propose content but cannot approve or publish it. Export remains the highest-authority action;
BrandForge does not contain an automatic publishing connector.

Important source areas:

- `src/brandforge/domain.py`: campaign, approval, design, and export domain models.
- `src/brandforge/workflow.py`: campaign orchestration and approval behavior.
- `src/brandforge/state_machine.py`: allowed campaign-state transitions.
- `src/brandforge/agents/`: brand, planning, creative, critic, reranking, and preference logic.
- `src/brandforge/integrations/`: OpenAI, Firefly, S3, PostgreSQL, Temporal, and OpenCLIP adapters.
- `apps/api/`: FastAPI routes and request/response contracts.
- `apps/web/`: Next.js control room and native editor.
- `tests/`: domain, workflow, persistence, security, API, provider, and editor verification.

## Local environment and execution

Docker was unavailable in the active development environment, so the application was also made
usable through direct local processes:

- Python virtual environment for the FastAPI application.
- Uvicorn development server for the API.
- Next.js development server for the web application.
- Caddy as the local HTTPS reverse proxy for integrations requiring a secure origin.

The normal direct endpoints are:

```text
Web:   http://localhost:3000
API:   http://localhost:8000
HTTPS: https://localhost:3443
```

The Caddy configuration proxies API paths to port 8000 and all remaining requests to port 3000.
The local Caddy certificate must be trusted on the development machine before browser requests to
the HTTPS origin will work normally.

The `.env` file contains local runtime configuration. It is excluded from source control and
contains:

- Server-only OpenAI configuration.
- Model aliases and response token budgets.
- Allowed browser origins.
- Browser-safe Adobe Express client configuration.
- The public API origin used by the Next.js build.

`NEXT_PUBLIC_*` values are embedded into the frontend build. Changes to those variables require a
frontend rebuild or development-server restart.

## OpenAI provider implementation and reliability fixes

The OpenAI integration uses:

- Responses API for campaign copy.
- Responses API with image input for vision scoring.
- Image API for generated campaign visuals.
- `store=false` for Responses calls.
- Server-side environment credentials only.

The initial provider failed when `OPENAI_BASE_URL` was blank. The runtime configuration now uses a
fully qualified API URL.

The provider also previously returned `OpenAI returned no campaign copy` when a response consumed
its output budget before returning visible text. The implementation now:

- Uses configurable text and vision output-token limits.
- Supports configurable reasoning effort.
- Detects incomplete responses.
- Retries once with a larger bounded token budget when the incomplete reason is
  `max_output_tokens`.
- Extracts visible output defensively.
- Returns sanitized status and reason details without exposing credentials or request contents.

Relevant files:

- `src/brandforge/integrations/openai_provider.py`
- `src/brandforge/config.py`
- `src/brandforge/factory.py`
- `.env.example`
- `docker-compose.yml`
- `tests/test_openai_provider.py`
- `tests/test_config_factory.py`

## Campaign control-room redesign

The frontend was redesigned as a campaign control room while preserving the existing workflow.
The interface now includes:

- A BrandForge identity bar and local-environment indicator.
- A clear campaign launch surface.
- A workflow progress rail.
- Dedicated human-review gates.
- Ranked variant cards and compliance information.
- Run cost, approval, trace, and event summaries.
- Responsive layouts and reduced-motion behavior.
- Accessible labels and visible status states.

Primary files:

- `apps/web/app/page.tsx`
- `apps/web/app/globals.css`
- `apps/web/app/layout.tsx`
- `apps/web/components/ProgressRail.tsx`

## Adobe Express integration

Adobe Express remains an optional secondary destination rather than the default editor.

The SDK integration was corrected to:

- Load the Adobe script only once.
- Cache SDK initialization in a browser-global promise.
- Clear the cached promise after initialization errors.
- Prevent concurrent button activations.
- Fetch the selected visual as a Blob.
- Pass the expected `dataType: "blob"` and `data` payload to `createWithAsset`.
- Display opening and error states.

Adobe Express still depends on:

- A valid browser client ID.
- An allowed HTTPS domain.
- Adobe review or business approval for production behavior without development restrictions.

The native BrandForge editor does not depend on Adobe approval.

Primary file:

- `apps/web/components/AdobeExpressButton.tsx`

## Native Fabric.js editor

Fabric.js 7.4 is installed in the Next.js application and loaded only on the client.

The editor supports:

- Selection, movement, scaling, and rotation.
- Editable textboxes.
- Text creation and deletion.
- Fill, font-family, font-size, and canvas-background controls.
- Layer ordering.
- Undo and redo with bounded history.
- Responsive fit-to-viewport behavior without changing document coordinates.
- SVG, PNG, and vendor-neutral JSON downloads.
- Draft persistence.
- Layer selection, visibility, locking, and inline renaming.
- Image Fit, Fill, Crop, Replace, and Reset controls.
- Text overflow warnings against a five-percent safe area.
- Strict cleanup under React development remounting.

Primary files:

- `apps/web/components/editor/CampaignEditor.tsx`
- `apps/web/components/editor/EditorToolbar.tsx`
- `apps/web/components/editor/LayersPanel.tsx`
- `apps/web/components/editor/editor-types.ts`
- `apps/web/components/editor/fabric-utils.ts`
- `apps/web/app/globals.css`

### Editor source of truth

The permanent design source is a vendor-neutral layer document. Fabric JSON is a rendering cache,
not the canonical business format. SVG is the interoperable approved artifact.

Supported canonical layer types are:

```text
text
image
rect
ellipse
path
group
```

Canonical layers preserve:

- Stable ID and editable name.
- Semantic role.
- Geometry and transforms.
- Fill, stroke, opacity, visibility, and shadow.
- Text content and typography.
- Image source, crop data, and filters.
- Image fit mode.
- Asset identity.
- Brand-lock metadata.
- Group children.

Unsupported Fabric object types are rejected rather than silently omitted from persisted designs.

### Generated campaign visual handoff

The completed-campaign preview and the original editable SVG initially used separate artifacts:

```text
Campaign preview -> generated visual
Editor bootstrap -> gradient-and-copy SVG
```

That caused the editor to open without the generated visual. The editor now receives the selected
variant image URL and inserts it as the bottom `Campaign visual` image layer.

The generated image defaults to Fit scaling:

- Fit uses the smaller width/height ratio and keeps the whole composition visible.
- Fill uses the larger ratio and intentionally crops overflow.
- Crop uses fill scaling and allows the user to reposition the image inside the canvas.
- Reset restores the campaign visual to centered Fit behavior.
- Replace accepts a local image up to 10 MiB and preserves the layer's semantic identity and stack
  position.

Image-mode changes remain local until the user selects `Save draft`. They do not silently
invalidate final approval.

Generated collages remain one flattened image layer. Individual people, products, or sub-images
cannot be edited separately unless the generation pipeline produces separate source assets.

### Overlay and layer-label corrections

The original full-canvas gradient hid the generated image even after the image layer was inserted.
It is now a 30-percent translucent overlay.

Generated layouts include semantic IDs and names:

```text
Campaign visual
Gradient overlay
Content panel
Concept label
Headline
Body copy
CTA background
CTA label
```

Older exported campaigns are normalized during import so they receive equivalent names and overlay
behavior without requiring campaign regeneration.

The Layers panel now uses explicit `Show`, `Hide`, `Lock`, and `Unlock` controls instead of ambiguous
circle and diamond symbols. Names can be edited inline and are bounded before persistence.

### Editable imported text and overflow protection

Imported SVG text objects are converted into Fabric `Textbox` objects. Existing headlines and body
copy can therefore be edited directly instead of behaving as non-editable SVG text.

Headline and body-copy widths are constrained to the canvas safe area. Body copy uses an increased
line height for readability. A non-blocking warning identifies text layers that move outside the
five-percent content boundary.

### Safe SVG serialization

Fabric normally includes an SVG 1.1 DOCTYPE in `Canvas.toSVG()`. The backend correctly rejects DTD
and entity declarations because they are unsafe to parse from untrusted requests.

Saved and downloaded Fabric SVGs now use `suppressPreamble: true`. This removes the XML/DOCTYPE
preamble while preserving normal Fabric groups, transforms, styles, and image elements.

The backend continues to reject:

- DOCTYPE and entity declarations.
- Script elements.
- JavaScript URLs.
- Event-handler attributes.
- Malformed XML.
- Non-SVG roots.
- Oversized documents.
- Mismatched channel dimensions.

SVG security was not disabled to work around Fabric output.

## Versioned design persistence

Editable designs are persisted as immutable revisions inside the existing campaign aggregate, so no
campaign-table migration is required.

Each channel maintains an independent revision sequence:

```text
designs/{tenant}/{campaign}/{channel}/v{revision}/layer-document.json
designs/{tenant}/{campaign}/{channel}/v{revision}/fabric.json
designs/{tenant}/{campaign}/{channel}/v{revision}/design.svg
designs/{tenant}/{campaign}/{channel}/v{revision}/preview.png
```

Each revision stores:

- Revision ID and number.
- Channel.
- Canonical layer-document key.
- Fabric-cache key.
- SVG key.
- Optional preview key.
- Editor name and version.
- Creating user and timestamp.
- SHA-256 hashes of persisted artifacts.

Writes enforce:

- Tenant ownership.
- Supported channels.
- Safe identifiers and generated object keys.
- Expected per-channel revision.
- Existing campaign optimistic concurrency.
- Document, layer, nesting, string, SVG, and preview bounds.
- Valid PNG signatures.
- Valid and restricted SVG content.

Stale editor writes return a conflict instead of overwriting newer work.

Relevant backend files:

- `src/brandforge/domain.py`
- `src/brandforge/editor.py`
- `src/brandforge/workflow.py`
- `src/brandforge/state_machine.py`
- `src/brandforge/exporter.py`
- `src/brandforge/factory.py`

## Design API

The tenant-scoped API exposes:

```text
GET /v1/campaigns/{campaign_id}/designs/{channel}
PUT /v1/campaigns/{campaign_id}/designs/{channel}
GET /v1/campaigns/{campaign_id}/designs/{channel}/preview
```

The GET route returns either:

- The latest persisted revision, canonical layer document, Fabric cache, and SVG.
- Or revision zero with the approved/exported channel SVG as bootstrap content.

The PUT route accepts:

- Canonical layer document.
- Fabric JSON rendering cache.
- SVG.
- Optional base64 PNG preview.
- Expected design revision.
- Editor version.

The preview route returns the latest PNG with private, no-store cache behavior.

Error behavior:

- Missing or cross-tenant campaigns return 404.
- Stale expected revisions return 409.
- Invalid channels, documents, base64 data, previews, or SVG return 422.
- CORS permits PUT for configured origins.

Relevant files:

- `apps/api/schemas.py`
- `apps/api/main.py`
- `apps/web/lib/api.ts`
- `apps/web/lib/types.ts`
- `tests/test_editor_api.py`

## Approval invalidation and re-export safety

Saving a design after final approval:

1. Creates a new immutable design revision.
2. Preserves the previous approval records as audit history.
3. Clears the stale export reference.
4. Emits a `design.edited` outbox event.
5. Transitions the campaign from `completed` to `final_approval`.
6. Requires a new attributable final approval.

The only new reverse transition is:

```text
completed -> final_approval
```

After renewed approval:

- Edited channels export the exact latest saved SVG.
- Untouched channels are rendered from the selected campaign variant.
- The export manifest records design revision IDs, canonical layer sources, and SVG sources.

This prevents an approved artifact and a subsequently edited artifact from being treated as the
same version.

## Storage and tenancy

Local development supports:

- SQLite campaign persistence.
- Filesystem object storage.

Production-oriented adapters support:

- PostgreSQL campaign persistence.
- PostgreSQL row-level-security setup.
- S3-compatible object storage.
- Transactional outbox delivery.

Images, PDFs, SVGs, design JSON, and previews are stored in object storage rather than database
binary columns. Database records retain metadata, ownership, object keys, hashes, workflow state,
and audit information.

Development identity headers are not production authentication. A production deployment requires a
trusted OIDC/JWT gateway or verified identity proxy.

## Automated verification

The latest completed verification includes:

```text
Python tests:             90 passed
Ruff:                     passed
Provider-independent mypy: passed
Python compile checks:    passed
TypeScript:               passed
Next.js production build: passed
IDE diagnostics:          no errors
```

The Python suite covers:

- Configuration and provider construction.
- OpenAI incomplete-response retry behavior.
- Campaign state transitions.
- Human approvals.
- Tenant isolation.
- Optimistic concurrency.
- Persistence round trips.
- Upload validation.
- Reranking.
- Design revision immutability.
- Stale editor writes.
- Design API validation.
- Preview behavior.
- Approval invalidation.
- Exact edited-SVG re-export.

Known non-blocking warnings:

- Starlette reports a TestClient/httpx deprecation warning.
- Next.js warns that multiple lockfiles cause workspace-root inference.
- Adobe's SDK reports a deprecated Lit entrypoint from Adobe-hosted code.

These warnings do not currently fail tests or builds.

## Operational use

For direct local development:

```bash
# API
source .venv/bin/activate
uvicorn apps.api.main:app --reload --host 127.0.0.1 --port 8000

# Web
npm --prefix apps/web run dev

# HTTPS proxy
caddy run --config Caddyfile
```

Use the HTTPS origin when testing Adobe Express:

```text
https://localhost:3443
```

When only native BrandForge editing is required, the ordinary local web origin is sufficient if
the configured API origin and CORS settings match it.

For the Compose deployment:

```bash
docker compose up --build
```

## Security properties

Implemented controls include:

- Server-only model-provider credentials.
- Browser-safe public configuration separation.
- Tenant-scoped campaign and design lookups.
- Generated, validated object-store paths.
- Upload size, MIME, and magic-byte checks.
- SVG active-content restrictions.
- PNG signature checks.
- Bounded JSON depth, array sizes, object sizes, and string lengths.
- Optimistic concurrency for campaigns and design revisions.
- Human approval before export.
- Approval invalidation after edits.
- Provenance manifests and artifact hashes.
- No automatic campaign publishing.

Production still requires:

- Real authentication and authorization.
- Malware scanning.
- Isolated document rendering and OCR.
- Secret-manager integration.
- Separate database roles with enforced RLS.
- Credentialed S3/PostgreSQL/Temporal integration tests.
- WAF, TLS, rate limiting, monitoring, and backup validation.

## Implemented multimodal retrieval and preference evaluation

The six-phase multimodal retrieval and curated preference-evaluation roadmap is implemented. The
included datasets remain synthetic smoke fixtures; human relevance and preference results are
still pending reviewed data collection.

The implemented scope is:

- CLIP/SigLIP embeddings for approved images, PDF chunks, and previous campaigns.
- PostgreSQL/pgvector vector search.
- A bounded SQLite brute-force fallback for local development.
- Text-to-image and image-to-image retrieval.
- Cross-modal reranking and policy filtering.
- Recall@10 and Recall@50.
- NDCG@10.
- MRR.
- Pairwise retrieval-reranker accuracy.
- Search-latency reporting.
- Brand-policy violation rate.
- Curated Bradley-Terry comparison datasets.
- Leakage-safe campaign/brief/brand splits.
- Pairwise preference accuracy.
- NDCG@3.
- Calibration error.
- Human top-choice selection rate.
- Brand and campaign-category slices.

Because no curated human comparison dataset currently exists, the approved approach is to:

- Build a curation and import pipeline.
- Include deterministic synthetic data only for smoke testing.
- Label synthetic metrics explicitly.
- Never present synthetic results as human-study evidence.
- Keep real human metrics pending until reviewed data is collected.

### Implemented architecture

```text
Approved images, PDFs, and completed campaigns
  -> Normalization and policy filtering
  -> CLIP or SigLIP embedding worker
  -> PostgreSQL/pgvector index
     or bounded SQLite fallback
  -> Text or image query embedding
  -> Cosine retrieval to top 50
  -> Cross-modal and policy reranking
  -> Top approved references with provenance
  -> Creative-agent context and retrieval evaluation

Human variant comparisons
  -> Frozen feature and display-rank snapshot
  -> Reviewer curation
  -> Versioned comparison dataset
  -> Campaign/brief/brand grouped split
  -> Bradley-Terry training
  -> Calibration and ranking evaluation
  -> Versioned production model artifact
```

### Phase 1: retrieval foundation

Add a new retrieval domain module and extend the existing ports with:

- Indexed multimodal record metadata.
- Embedding-model identity and dimensions.
- Text and image embedding provider contracts.
- Tenant-scoped retrieval repository contracts.
- Relevance judgments and scored-result types.
- Strict finite, normalized, dimension-checked vectors.
- Safe source IDs, hashes, and object keys.

Refactor the optional OpenCLIP adapter so it can:

- Lazily import Torch, Pillow, and OpenCLIP.
- Encode text and image inputs into the same normalized vector space.
- Select either CLIP or SigLIP through configuration.
- Report a clear configuration error when optional dependencies are unavailable.
- Preserve its direct text-image scoring compatibility.

Add a deterministic embedding provider for tests and synthetic evaluation only. Its output must be
stable across processes and explicitly labeled synthetic.

Storage implementation:

- PostgreSQL stores vectors using pgvector.
- An HNSW cosine index serves production similarity queries.
- Unique model/source hashes make indexing idempotent.
- RLS policies enforce tenant isolation.
- SQLite stores vectors as bounded JSON and performs in-process cosine search for local use.
- SQLite queries must apply tenant, model, approval, kind, and campaign filters before loading
  candidate vectors into memory.

Primary files:

- `src/brandforge/retrieval.py`
- `src/brandforge/ports.py`
- `src/brandforge/integrations/clip_scorer.py`
- `src/brandforge/integrations/retrieval_repository.py`
- `infra/sql/002_multimodal_retrieval.sql`

### Phase 2: asset indexing and search

Create an indexing service for:

- Approved PNG and JPEG assets.
- Approved-example and product assets.
- Extracted PDF text chunks.
- Completed campaign copy.
- Selected completed-campaign visuals.

Every indexed record should retain:

- Tenant and source campaign.
- Asset ID and object key.
- Asset kind and media type.
- Brand and campaign category.
- Approval and policy status.
- Source hash.
- Embedding model/version.
- Creation and indexing timestamps.

Unapproved, quarantined, unsupported, or cross-tenant assets must never appear in normal search
results.

Indexing should be idempotent and support a safe backfill for existing campaigns. Local development
may execute bounded indexing directly. Production should use a separate multimodal worker so the
FastAPI process does not load Torch or block on media inference.

Add strict API operations for:

```text
POST /v1/campaigns/{campaign_id}/retrieval/text
POST /v1/campaigns/{campaign_id}/retrieval/image
GET  /v1/campaigns/{campaign_id}/retrieval/status
POST /v1/campaigns/{campaign_id}/retrieval/backfill
```

Text requests contain a bounded query and result limit. Image requests use validated multipart
uploads and never accept an arbitrary client-provided object-store key.

Two-stage search:

1. Retrieve up to 50 candidates using vector cosine similarity.
2. Rerank using exact cross-modal similarity, brand/category alignment, approval state, policy
   status, provenance quality, and result diversity.

The creative workflow should receive only approved top references. Retrieval IDs, scores, model
versions, and object keys must be recorded in the agent trace for reproducibility.

Primary files:

- `src/brandforge/retrieval.py`
- `src/brandforge/workflow.py`
- `src/brandforge/factory.py`
- `apps/api/schemas.py`
- `apps/api/main.py`
- `apps/worker/`

### Phase 3: retrieval evaluation

Create a versioned JSONL relevance-judgment format containing:

- Query ID and modality.
- Query text or image fixture.
- Tenant-safe candidate IDs.
- Graded relevance judgments.
- Brand/category labels.
- Policy-violation labels.
- Dataset source and version.

Evaluation compares vector retrieval with the cross-modal reranked output and reports:

- Recall@10.
- Recall@50.
- NDCG@10.
- Mean reciprocal rank.
- Pairwise reranker accuracy.
- p50 and p95 search latency.
- Brand-policy violation rate.
- Query and judgment counts.
- Embedding and reranker versions.

The CLI should emit:

- Machine-readable JSON.
- A concise Markdown report.
- Baseline-versus-reranked metrics.
- Clearly labeled synthetic or human dataset provenance.

The included synthetic dataset exists only to verify calculation, report generation, and regression
detection. It must not be described as measured Adobe, OpenAI, or human search quality.

Primary files:

- `src/brandforge/retrieval_evaluation.py`
- `evals/retrieval_judgments.synthetic.jsonl`
- `reports/retrieval-evaluation.synthetic.json`
- `reports/retrieval-evaluation.synthetic.md`
- `tests/test_retrieval_evaluation.py`

### Phase 4: curated preference dataset

Extend preference feedback so selection-time data is frozen before variants can be regenerated:

- Preferred variant ID.
- Rejected variant IDs.
- Preferred and rejected critic-feature snapshots.
- Display ranks and presentation order.
- Brand and category.
- Brief fingerprint.
- Curation status.
- Curating reviewer and timestamp.
- Dataset/source version.

Raw selections remain audit feedback but are not automatically eligible for training.

Add reviewer-authorized curation and tenant-scoped import/export operations. Dataset construction
expands one selected winner against each rejected candidate into explicit pairwise rows.

Splits must be grouped:

- All comparisons from one campaign stay in one split.
- Held-out briefs do not appear in training.
- Brand-held-out evaluation measures generalization.
- Duplicate brief fingerprints are kept together.

This prevents campaign-level and near-duplicate leakage.

Primary files:

- `src/brandforge/domain.py`
- `src/brandforge/workflow.py`
- `src/brandforge/preference_dataset.py`
- `apps/api/schemas.py`
- `apps/api/main.py`
- `tests/test_preference_dataset.py`

### Phase 5: preference training and evaluation

Upgrade the Bradley-Terry implementation with:

- Pairwise win-probability prediction.
- Versioned model metadata.
- Dataset and split fingerprints.
- Training hyperparameters.
- Save/load validation.
- Optional configured production artifact loading.

Training uses only frozen critic features from curated rows. Preference score, final rank, and
diversity-adjusted output must not be reused as input features because that would create circular
training.

The training/evaluation CLI should report:

- Pairwise held-out accuracy.
- NDCG@3.
- Expected calibration error.
- Human top-choice selection rate.
- Metrics by brand.
- Metrics by campaign category.
- Train, validation, and test sample counts.
- Warnings or suppression for undersized slices.

Synthetic comparison data will verify the pipeline. Human results remain pending until curated
review data exists.

The model is loaded through configuration and passed into the existing multimodal reranker. Raw
clicks never update production weights automatically.

Primary files:

- `src/brandforge/agents/preferences.py`
- `src/brandforge/preference_dataset.py`
- `src/brandforge/preference_evaluation.py`
- `src/brandforge/config.py`
- `src/brandforge/factory.py`
- `evals/preference_comparisons.synthetic.jsonl`
- `tests/test_preference_evaluation.py`

### Phase 6: runtime, documentation, and verification

Runtime work includes:

- Add the pgvector Python dependency.
- Preserve the optional multimodal dependency group.
- Add CLIP/SigLIP and retrieval configuration variables.
- Add a separate multimodal worker image/service.
- Keep the API functional when Torch is not installed.
- Document PostgreSQL extension bootstrap and RDS requirements.
- Add Makefile and CLI commands for indexing, retrieval evaluation, preference training, and
  preference evaluation.

Required verification:

- Vector validation and normalization tests.
- SQLite and PostgreSQL repository contract tests.
- Tenant and model isolation tests.
- Idempotent indexing tests.
- Policy-filter tests.
- Text-to-image and image-to-image query tests.
- Retrieval metric formula tests.
- Pairwise metric and calibration tests.
- Dataset split-leakage tests.
- API validation and authorization tests.
- Workflow retrieval-trace tests.
- Synthetic report-schema tests.
- Optional real OpenCLIP/SigLIP smoke test when dependencies are installed.
- Full Python suite.
- Ruff.
- Mypy for changed backend modules.
- Dependency and configuration validation.

### Completed implementation order

1. [x] Add embedding abstractions, retrieval models, pgvector migration, and SQLite/PostgreSQL
   repositories.
2. [x] Index approved images, PDF chunks, and completed campaigns; add tenant-safe text/image search and
   cross-modal reranking.
3. [x] Add relevance datasets, retrieval metrics, benchmark CLI, and a labeled synthetic report.
4. [x] Snapshot and curate reviewed comparisons with leakage-safe dataset import/export and grouped
   splits.
5. [x] Train and load versioned Bradley-Terry models and report global plus brand/category metrics.
6. [x] Wire configuration and runtimes, document workflows, add tests, and run complete verification.

## Current limitations

- Generated campaign collages are flattened image layers.
- The native editor cannot independently manipulate subjects inside a flattened generated image.
- The API still executes the main creative funnel synchronously.
- PDF extraction does not include OCR.
- Adobe Express production behavior depends on Adobe approval.
- OpenCLIP/SigLIP inference remains optional and requires the multimodal dependency image.
- The Bradley-Terry model has no real human-curated training dataset.
- OpenAI vision scores are not calibrated against a human reviewer study.
- Offline benchmark percentages are deterministic fixture results, not production quality claims.

## Recommended next steps

1. Collect reviewer comparisons with explicit curation metadata.
2. Run held-out human retrieval evaluation across brands and campaign categories.
3. Train the preference model only from the newly curated human comparisons.
4. Report confidence intervals, reviewer agreement, cost, and latency before using quantified
   portfolio claims.

## Claim-safety note

The deterministic benchmark proves that evaluation plumbing can identify deliberately injected
failures. It does not prove real-world model quality or human preference lift.

Do not claim retrieval improvements, preference-model accuracy, or human-selection gains until the
implemented pipelines are evaluated on versioned, held-out, human-reviewed datasets.
