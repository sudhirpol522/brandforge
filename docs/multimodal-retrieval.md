# Multimodal retrieval

BrandForge indexes only approved, policy-allowed sources. The supported sources are approved PNG
and JPEG assets, extracted PDF or text chunks, completed campaign copy, and the selected visual
from a completed campaign. Every record preserves tenant, campaign, asset, model, source hash,
approval, policy, brand, category, and object-store provenance.

## Local mode

The default local configuration uses deterministic normalized hash embeddings. This mode verifies
storage, filtering, API, trace, and evaluation behavior but has no semantic quality claim.

~~~bash
make retrieval-index TENANT=demo-studio
make retrieval-eval
~~~

SQLite applies tenant, model, approval, policy, kind, and campaign filters in SQL before loading a
bounded candidate set. Cosine scoring and cross-modal policy reranking then run in process.

## PostgreSQL and pgvector

Apply `infra/sql/002_multimodal_retrieval.sql` as an administrator after choosing the fixed vector
dimension for the configured embedding model. The migration creates the pgvector extension, an
HNSW cosine index, filter indexes, forced row-level security, and the application-role grant.

Before applying it to RDS, verify that the selected engine version exposes the `vector` extension
and that the migration role may create it. The application role must not have `BYPASSRLS`.

## Isolated inference

The ordinary API image does not install Torch, Pillow, or OpenCLIP. Production can run the
`multimodal-worker` service and configure the API with:

~~~text
RETRIEVAL_EMBEDDING_PROVIDER=remote
RETRIEVAL_REMOTE_URL=http://multimodal-worker:8010
RETRIEVAL_EMBEDDING_DIMENSION=512
RETRIEVAL_WORKER_TOKEN=<server-only shared token>
~~~

The `multimodal-indexer` service reads approved material from the database/object store and writes
idempotent pgvector records. Neither service is exposed on a host port by the Compose definition.
Use a network policy and distinct database roles in production.

## API

Campaign-scoped operations are:

~~~text
POST /v1/campaigns/{campaign_id}/retrieval/text
POST /v1/campaigns/{campaign_id}/retrieval/image
GET  /v1/campaigns/{campaign_id}/retrieval/status
POST /v1/campaigns/{campaign_id}/retrieval/backfill
~~~

Image queries accept validated multipart PNG or JPEG uploads. Clients cannot submit object-store
keys. Normal search always requires approved and policy-allowed records from the requesting tenant
and configured embedding-model identity.

The creative trace records the retrieval IDs, scores, object keys, and model versions supplied to
the creative agent. This makes a generated run reproducible without recording hidden reasoning.

## Evaluation boundary

`evals/retrieval_judgments.synthetic.jsonl` is deliberately synthetic. Its generated JSON and
Markdown reports verify Recall@10/50, NDCG@10, MRR, pairwise ordering, latency percentiles, and
policy-violation calculations. Replace it with a versioned human relevance dataset before making
quality claims.
