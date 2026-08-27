# Runbook: model provider outage

## Trigger

- Provider timeout/error rate exceeds 10% for five minutes.
- Campaigns enter failed_retryable or queue age breaches the service objective.
- Spend or rate limit blocks new calls.

## Contain

1. Disable the affected model alias at the model gateway.
2. Stop new image-generation fan-out; preserve current campaign state.
3. Use the configured fallback only if its evaluation is within approved thresholds.
4. Otherwise keep campaigns pending and tell reviewers generation is delayed.
5. Never retry a charged external action without the provider request/idempotency identifier.

## Diagnose

- Correlate campaign trace, provider request, agent, model, attempt, and cost reservation.
- Separate provider failures from invalid structured output, network, quota, and application bugs.
- Check whether any returned image was stored before the timeout.

## Recover

Resume from the failed activity. Do not regenerate approved prior steps. Run one synthetic campaign,
then drain the oldest queued campaign first while enforcing tenant concurrency limits.

## Close

Reconcile charged calls, annotate affected campaign manifests, write a failure example into the
golden set, and update timeout/retry policy only after evaluating cost and duplicate risk.
