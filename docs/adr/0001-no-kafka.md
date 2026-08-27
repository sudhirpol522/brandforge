# ADR 0001: Start with a PostgreSQL outbox, not Kafka

Status: accepted

## Context

BrandForge has low-to-moderate event volume and long, human-paused workflows. The first consumers
are audit/analytics and a future feedback pipeline. Kafka would add brokers, partitions, retention,
schema governance, consumer lag, and a second retry model before those needs exist.

## Decision

PostgreSQL is the campaign source of truth. State mutations produce stable outbox events. A worker
publishes them at least once and marks them after success. Temporal may coordinate long waits, but
it does not replace domain events.

## Add Kafka when

- Several independent teams consume the same events.
- Long retention and replay are product requirements.
- Sustained event volume exceeds the database worker design.
- Streaming billing, training, CDC, or lake ingestion requires partition ordering.

The Kafka producer should read the same outbox; agents and request handlers never publish directly.
