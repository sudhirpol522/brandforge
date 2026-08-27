from __future__ import annotations

import logging
import signal
import time

from brandforge.config import Settings
from brandforge.domain import utc_now
from brandforge.factory import build_repository
from brandforge.telemetry import configure_logging

logger = logging.getLogger("brandforge.outbox_worker")
running = True


def stop(*_: object) -> None:
    global running
    running = False


def main() -> None:
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    repository = build_repository(settings)
    if not hasattr(repository, "unpublished_events"):
        raise RuntimeError("configured repository does not support the outbox worker")
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    logger.info("outbox worker started")
    while running:
        events = repository.unpublished_events(limit=100)
        if not events:
            time.sleep(1)
            continue
        for event in events:
            # This reference consumer is an observable analytics/audit sink. Replace or extend
            # it with Kafka only when multiple independent consumers and replay are required.
            logger.info(
                "domain event published",
                extra={
                    "tenant_id": event.tenant_id,
                    "campaign_id": event.aggregate_id,
                    "event_type": event.event_type,
                },
            )
            repository.mark_published(event.id, utc_now())
    logger.info("outbox worker stopped")


if __name__ == "__main__":
    main()
