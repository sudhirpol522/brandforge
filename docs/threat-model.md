# Threat model

## Assets

- Unreleased brand guides, product images, logos, and campaign briefs.
- OpenAI, Adobe, database, and storage credentials.
- Human approvals and legal-review history.
- Generated assets, preference feedback, and model/evaluation manifests.
- Tenant identity and authorization boundaries.

## Trust boundaries

~~~mermaid
flowchart TD
    U["Authenticated reviewer"] --> EDGE["OIDC gateway"]
    EDGE --> API["BrandForge API"]
    API --> DB["Tenant-scoped database"]
    API --> STORE["Private object storage"]
    API --> MODEL["Model gateway"]
    MODEL --> PROVIDER["OpenAI / Adobe"]
    DB --> WORKER["Restricted workers"]
~~~

The browser is untrusted. Uploaded documents are untrusted. Retrieved brand text is data, not
instructions. Model output is an untrusted proposal. Only deterministic executors mutate durable
state or export an approved artifact.

## Threats and mitigations

| Threat | Mitigation in repo | Production requirement |
|---|---|---|
| Cross-tenant object access | Tenant check before object-key lookup; tenant in key | RLS, distinct roles, S3 access points/prefix policy tests |
| Prompt injection | Pattern warnings, strict output fields, no model tool authority | Adversarial corpus and document provenance |
| Malicious upload | Size, magic-byte, MIME allowlist | Malware scan and isolated parser/render farm |
| Secret leakage | Environment/secret manager only, redacted logs, server-side SDK | Rotation, scoped project keys, egress policy |
| SSRF | No user-controlled URL fetch in core | Allowlisted provider download service |
| Excessive spend | Call count and estimated-cost reservation before every call | Provider spend limits and invoice reconciliation |
| Replay/duplicate action | Idempotency key table and outbox IDs | TTL cleanup and distributed integration tests |
| Approval forgery | Attributed, version-bound approval records | Cryptographically validated identity claims |
| Stale approval | New revisions and variant IDs | Explicit invalidation table for manual edits |
| Public export leak | Private object store; no publishing connector | Short-lived signed URLs and download audit |
| Supply-chain compromise | Dependency audit, image scan, SBOM/provenance workflow | Digest pinning, signature verification, patch SLA |

## Data minimization

Responses calls set store=false. Logs contain observable summaries, IDs, timing, and costs, not
hidden reasoning or raw brand-guide text. Provider responses are not copied wholesale into traces.
Production must configure retention per tenant and implement a verified cascade delete across
database rows, outbox records, object versions, caches, and derived evaluation data.

## Abuse cases to test before launch

- Tenant A guesses Tenant B campaign and object IDs.
- A PDF contains scripts, recursive objects, decompression bombs, and injected instructions.
- A model returns HTML/JavaScript inside generated copy.
- A reviewer modifies an asset after legal approval.
- OpenAI times out after charging but before the response reaches BrandForge.
- The same approval request is replayed concurrently.
- A provider URL redirects to an internal address.
- A user attempts 1,000-candidate fan-out or an oversized image.
- An outbox event is delivered twice and out of order.
- A deleted tenant appears in vector search, backups, or old S3 versions.
