# Architecture

BrandForge starts as a modular monolith with separate process types. The API owns authorization
and deterministic transitions; workers own long-running or asynchronous activities; providers
are replaceable adapters.

~~~mermaid
flowchart TD
    UI["Next.js review UI"] --> API["FastAPI boundary"]
    API --> WF["Versioned workflow service"]
    WF --> DB["PostgreSQL + outbox"]
    WF --> OBJ["Private object storage"]
    WF --> AG["Specialist agents"]
    AG --> GW["Budgeted model gateway"]
    GW --> OA["OpenAI Responses + Images"]
    WF --> EV["Critics + reranker"]
    DB --> OW["Outbox worker"]
    API --> OBS["Metrics + traces"]
~~~

## Process responsibilities

| Process | Owns | Does not own |
|---|---|---|
| Web | Brief form, side-by-side review, reason-coded decisions | Provider keys, authorization policy |
| API | Tenant boundary, uploads, idempotency, state transitions, approvals | Long-lived browser state |
| Workflow core | Contracts, gates, retries/failure states, versioning | HTTP, provider-specific SDKs |
| Outbox worker | At-least-once domain-event forwarding | Campaign source of truth |
| Temporal worker | Optional multi-day pause coordinator | Creative policy or hidden agent reasoning |
| Media worker path | Image generation, embeddings, normalization | Approval authority |

## State model

~~~mermaid
stateDiagram-v2
    [*] --> Created
    Created --> BrandReview: compile guide
    BrandReview --> PlanReview: approve rules
    PlanReview --> Generating: approve plan
    Generating --> Evaluating
    Evaluating --> VariantReview
    VariantReview --> FinalReview: select
    FinalReview --> Revising: request changes
    Revising --> Generating
    FinalReview --> Exporting: approve
    Exporting --> Completed
    Generating --> RetryableFailure: provider error
    RetryableFailure --> Generating: retry
~~~

Every mutation uses optimistic concurrency. Human approval records bind reviewer, role, artifact
version, decision, reason code, comments, and time. A later revision receives a new artifact
version and cannot silently inherit approval.

## Generation funnel

1. The creative agent produces eight inexpensive coordinated text and visual directions.
2. Deterministic critics measure brief overlap, palette adherence, risky claims, contrast,
   alt-text quality, and copy-image consistency.
3. A learned preference score and maximal-marginal-relevance penalty produce three distinct
   candidates.
4. The model gateway generates only those three images.
5. A vision model scores brief alignment, brand alignment, and composition quality.
6. The final reranker combines model and deterministic scores, and a human chooses.

The default fixture labels its score mode clearly. It never pretends a prompt/tag score came from
image pixels.

## Data placement

PostgreSQL stores campaigns, structured rules, plans, approvals, feedback, model manifests,
object keys, and outbox events. Object storage holds original uploads, normalized assets,
generated visuals, SVG exports, and manifests. Large binary data never enters campaign JSON.

Tenant ID appears in every row and object key. Production SQL adds row-level security. S3 is
private, encrypted, versioned, and accessed through the ECS task role.

## Why no Kafka

The core requirement is durable, human-paused orchestration, not high-throughput event streaming.
PostgreSQL outbox events support a single audit/analytics worker today. Kafka becomes justified
when billing, analytics, notifications, training, and data-lake teams need independent retention,
replay, ordering, and consumer scaling. See ADR 0001.
