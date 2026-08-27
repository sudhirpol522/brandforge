from __future__ import annotations

import logging
import os
import signal
import time

from brandforge.config import Settings
from brandforge.factory import build_workflow
from brandforge.telemetry import configure_logging

logger = logging.getLogger("brandforge.multimodal_indexer")
running = True


def stop(*_: object) -> None:
    global running
    running = False


def main() -> None:
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    workflow = build_workflow(settings)
    tenants = tuple(
        value.strip()
        for value in os.getenv("RETRIEVAL_TENANTS", settings.default_tenant).split(",")
        if value.strip()
    )
    interval = max(5, min(int(os.getenv("RETRIEVAL_INDEX_INTERVAL_SECONDS", "60")), 3600))
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    logger.info("multimodal indexer started")
    while running:
        for tenant_id in tenants:
            summaries = workflow.backfill_retrieval(tenant_id)
            logger.info(
                "retrieval backfill completed",
                extra={
                    "tenant_id": tenant_id,
                    "campaigns": len(summaries),
                    "indexed": sum(summary.indexed for summary in summaries),
                    "failed": sum(summary.failed for summary in summaries),
                },
            )
        if os.getenv("RETRIEVAL_INDEX_ONCE", "").lower() in {"1", "true", "yes"}:
            break
        deadline = time.monotonic() + interval
        while running and time.monotonic() < deadline:
            time.sleep(1)
    logger.info("multimodal indexer stopped")


if __name__ == "__main__":
    main()
