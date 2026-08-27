# BrandForge

BrandForge is a human-guided, multi-agent creative campaign studio. It compiles a brand guide
into reviewable rules, plans a cross-channel campaign, creates eight directions, reranks them
twice, pauses for attributable human decisions, and exports editable SVG layouts with a complete
provenance manifest.

The real provider path uses OpenAI Responses for copy and vision scoring and GPT Image for visual
generation. A deterministic provider makes the entire workflow, tests, and benchmark runnable
without a key.

## What is implemented

- Brand compiler with structured rules, evidence, confidence, and prompt-injection warnings.
- Campaign planner, creative specialist, deterministic critics, diversity-aware reranker, and
  a pairwise preference model.
- Cost funnel: 8 text concepts → first-pass rerank → 3 images → vision rerank → human choice.
- Four durable human gates: brand rules, plan, variant selection, and final approval.
- Versioned campaign state, optimistic concurrency, tenant guards, audit approvals, agent traces,
  model manifest, and transactional-outbox seam.
- FastAPI service and a responsive Next.js review control room.
- OpenAI, Adobe Firefly, local/S3, SQLite/PostgreSQL, optional OpenCLIP, and optional Temporal
  adapters.
- Tenant-safe text-to-image and image-to-image retrieval with SQLite and pgvector repositories,
  approved-source policy filtering, traceable reranking, and isolated OpenCLIP inference.
- Curated, leakage-safe pairwise preference datasets plus versioned Bradley-Terry training and
  evaluation artifacts.
- Four editable channel exports: Instagram, email, web hero, and presentation slide.
- 120-scenario benchmark, 90 automated tests, provider-independent core coverage, deterministic demo, failure
  analysis, Docker
  Compose, Grafana dashboard, CI, release workflow, and AWS Terraform.
- Kafka is intentionally omitted. PostgreSQL outbox events provide a safe later migration seam.

## Fastest verified demo — no key required

The deterministic demo itself requires only Python 3.11 or newer:

~~~bash
make demo
~~~

Install the development dependencies for the complete API/unit test suite:

~~~bash
python -m pip install -e ".[dev]"
make test
make eval
make retrieval-eval
make preference-eval
~~~

The demo completes every human gate with deterministic approvals, generates three stored visual
fixtures, and writes four editable exports under .brandforge/demo. That directory is ignored by
Git.

## Run with your OpenAI API key

1. Copy .env.example to .env.
2. Set OPENAI_API_KEY in .env. Never put the value in source code or a browser variable.
3. Keep MODEL_PROVIDER=openai.
4. Start the stack:

~~~bash
docker compose up --build
~~~

Open:

- Review UI: http://localhost:3000
- API documentation: http://localhost:8000/docs
- MinIO console: http://localhost:9001

The server uses:

- OPENAI_TEXT_MODEL=gpt-5.6 for copy.
- OPENAI_VISION_MODEL=gpt-5.6 for image-to-brief scoring.
- OPENAI_IMAGE_MODEL=gpt-image-2 for the three shortlisted visuals.

All names are configuration, so models can be changed without editing agents. BrandForge calls
OpenAI only from the API/worker container and sets store=false for Responses requests. The key is
read from the environment locally and should come from a secret manager in deployment.

The implementation follows the current official guidance to use the Responses API for new text
applications and the Image API for one-shot image generation:
[Responses API](https://developers.openai.com/api/docs/guides/migrate-to-responses),
[image generation](https://developers.openai.com/api/docs/guides/image-generation), and
[production key safety](https://developers.openai.com/api/docs/guides/production-best-practices).

## Full local platform

The base Compose stack includes web, API, PostgreSQL/pgvector, MinIO, and the outbox worker.
Optional profiles add observability and the Temporal approval coordinator:

~~~bash
OTEL_SDK_DISABLED=false docker compose --profile observability --profile temporal up --build
~~~

The `multimodal` profile adds isolated OpenCLIP inference and indexing. Configure the API to use
the remote provider and the same fixed embedding dimension before starting it; see
`docs/multimodal-retrieval.md`.

Additional endpoints:

- Grafana: http://localhost:3001
- Prometheus: http://localhost:9090
- Tempo: http://localhost:3200
- Temporal UI: http://localhost:8080

Local passwords in docker-compose.yml are deliberately labeled local-only. They are not
production defaults.

## Workflow

~~~mermaid
flowchart TD
    A["Brief + brand guide"] --> B["Brand compiler"]
    B --> C{"Brand review"}
    C --> D["Campaign planner"]
    D --> E{"Plan review"}
    E --> F["8 text directions"]
    F --> G["Policy + relevance rerank"]
    G --> H["3 generated images"]
    H --> I["Vision + diversity rerank"]
    I --> J{"Human selection"}
    J --> K{"Final approval"}
    K --> L["Editable SVG + manifest"]
~~~

Agents propose creative work. State transitions, upload rules, budgets, ranking math, approvals,
and export authorization are deterministic application code.

## Offline evaluation snapshot

These are measured fixture results from the included 120-scenario benchmark, not OpenAI quality
claims and not human-study results:

| System | Task success | Mean final | Brand | Visual | Claim violations | Calls/task |
|---|---:|---:|---:|---:|---:|---:|
| Single output | 61.7% | 0.836 | 0.869 | 0.845 | 17.5% | 2 |
| Multi-agent, first candidate | 61.7% | 0.836 | 0.869 | 0.845 | 17.5% | 16 |
| Multi-agent + reranker | 100.0% | 0.893 | 1.000 | 0.841 | 0.0% | 16 |
| Vision rerank, review-ready | 100.0% | 0.877 | 0.967 | 0.862 | 0.0% | 22 |

The fixture deliberately injects off-brand palettes and unsupported claims into some first
candidates. It proves the evaluation plumbing catches known failures; it does not prove production
lift. See reports/offline-evaluation.md and docs/failure-analysis.md.

## Repository map

| Path | Responsibility |
|---|---|
| src/brandforge | Domain, agents, ranking, workflow, persistence, security, integrations |
| apps/api | FastAPI routes, auth boundary, uploads, approvals, metrics |
| apps/web | Next.js human review interface and optional Adobe Express handoff |
| apps/worker | Outbox publisher and optional Temporal worker |
| evals | Versioned 10 × 12 benchmark definition |
| tests | Unit, API, security, persistence, and end-to-end workflow tests |
| infra/observability | OTel, Tempo, Prometheus, Grafana |
| infra/terraform | Safe-by-default AWS ECS/RDS/S3 deployment scaffold |
| docs | Architecture, threat model, runbooks, decisions, and limitations |

See PROJECT_TASKS.md for the completed workstream ledger and the credential-dependent launch
tasks that intentionally remain open.

## Adobe integration

Adobe Firefly remains an alternative image provider through ADOBE_FIREFLY_ENABLED. Adobe Express
handoff is feature-flagged in the web app. Express credentials, an HTTPS allowed domain, and
Adobe business approval are required; BrandForge never exposes the OpenAI or Firefly server
secret to the browser. See docs/adobe-integration.md.

## Production boundary

The local UI uses development identity headers. Do not expose that mode to real users. The
Terraform module defaults to an internal load balancer and development auth off; place an OIDC
identity-aware gateway in front of it, apply the row-level-security migration with distinct
application/worker roles, and configure TLS/WAF before storing customer assets.

Read docs/implementation-status.md before presenting or deploying the project. It distinguishes
working code from credential-dependent adapters and explicit production follow-up work.

Coverage measures the provider-independent core. Credentialed OpenAI, Adobe, S3, PostgreSQL, and
Temporal adapters are intentionally excluded from that percentage and must pass their separate
contract/integration suites in the target environment.

## Résumé bullet

Do not use the offline percentages as a résumé claim. After running the OpenAI benchmark and a
reviewer study, replace the blanks with measured confidence intervals:

> Improved brand-safe campaign task completion by __% over a single-output baseline while
> reducing human review time by __% at $__ per approved campaign across __ held-out briefs.

## License

MIT
