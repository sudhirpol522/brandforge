# Deployment guide

## Local modes

| Mode | Command | Provider | Persistence |
|---|---|---|---|
| Verified smoke demo | make demo | Deterministic | SQLite/local objects |
| Product stack | docker compose up --build | Deterministic or OpenAI | PostgreSQL/MinIO |
| Full platform | Docker Compose with observability and temporal profiles | Deterministic or OpenAI | PostgreSQL/MinIO/Temporal |
| Multimodal retrieval | Docker Compose `multimodal` profile | Remote OpenCLIP/SigLIP | PostgreSQL/pgvector + MinIO |

To use OpenAI locally, export OPENAI_API_KEY or place it in the ignored .env file, then set
MODEL_PROVIDER=openai. The Docker environment uses deterministic mode when no provider is selected.

## AWS sequence

1. Create separate OpenAI projects for staging and production and configure provider spend limits.
2. Put each key in Secrets Manager; pass only its ARN to Terraform.
3. Build and scan API/worker images, publish an SBOM, and use immutable digests.
4. Run the Terraform module with enable_public_demo=false.
5. Create separate brandforge_app and brandforge_worker database roles. Apply both RLS migrations,
   selecting the retrieval model's fixed vector dimension before applying migration 002.
6. Put an OIDC-aware HTTPS gateway and WAF in front of the internal ALB.
7. Run migrations as a one-off task, then deploy API before workers.
8. Run a synthetic tenant-isolation and OpenAI smoke campaign.
9. Enable alarms for error rate, queue age, cost, provider timeout, and brand violations.
10. Test restore from RDS backup and S3 object versions.

Run Torch/OpenCLIP only in the isolated multimodal inference and indexing images. Configure the API
with the remote embedding provider so the FastAPI image remains usable without multimodal wheels.
Restrict worker traffic to the service network and use a server-only worker token.

## Secrets

Never put the OpenAI key in Terraform variables, tfvars, container images, NEXT_PUBLIC variables,
logs, or client requests. ECS reads it from Secrets Manager at task start. Rotate by creating a new
secret version and forcing a new deployment. A compromised key should be revoked at the provider
before investigating logs.

## Release strategy

Prompt, model, weight, and workflow changes are release artifacts. CI reruns the 120-scenario set.
A real deployment should also run the held-out OpenAI evaluation, then use:

1. Shadow comparison against the current version.
2. One-tenant canary with strict cost and quality thresholds.
3. Gradual API/worker rollout.
4. Automatic ECS rollback on health failure.
5. Manual rollback when reviewer rejection or brand-violation rate breaches threshold.

## Production gaps

The Terraform module is a safe scaffold, not a one-command production certification. Add TLS,
WAF, OIDC, alerts, a remote Terraform backend with locking, VPC endpoints, database connection
pooling/proxy, and environment-specific backup/retention policy before real use.
