# Security policy

Do not report vulnerabilities in a public issue. Use the repository owner's private security
advisory channel. Include the affected version, reproduction steps, tenant-isolation impact,
and whether customer assets or credentials could be exposed.

BrandForge treats uploaded files and retrieved brand-guide text as untrusted data. Agents can
propose actions, but deterministic policy code authorizes uploads, state transitions, exports,
and future publishing actions. The sample does not publish to external channels.

Production deployments must replace development-header authentication with OIDC/JWT validation,
keep buckets private, rotate secrets, enable database row-level security, scan uploads, and
configure retention/deletion policies. See `docs/threat-model.md`.
