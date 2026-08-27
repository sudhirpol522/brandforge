# Contributing

1. Create a focused branch and include tests with every behavior change.
2. Run `make test`, `make eval`, and `make lint` before opening a pull request.
3. Never commit customer assets, model credentials, `.env`, or generated campaign data.
4. Changes to prompts, model routing, ranking weights, or workflow transitions require a
   benchmark comparison against the versioned 120-scenario evaluation set.
5. Security-sensitive changes require a threat-model note and tenant-isolation tests.

Commits should explain the user-visible outcome. Pull requests should include a failure-mode
analysis, rollback plan, and screenshots or traces for workflow changes.
