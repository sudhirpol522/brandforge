# ADR 0002: Agents propose; deterministic code authorizes

Status: accepted

## Context

Model output is probabilistic and can be influenced by uploaded content. BrandForge handles
unreleased assets, legal claims, budget, and final exports.

## Decision

Each agent has a versioned contract, tool allowlist, step/time/cost limit, typed input/output, and
escalation conditions. Agents can propose copy, visual prompts, plans, and scores. They cannot
change campaign state, approve work, fetch arbitrary URLs, access raw credentials, or publish.

The workflow service validates transitions. Critics use deterministic code whenever a property is
measurable. Human approvals bind to artifact versions. Observable summaries and tool calls are
stored; hidden model reasoning is not.

## Consequence

There is more application code than in a prompt-only demo, but failures are testable, permissions
are legible, and provider replacement does not rewrite the domain.
