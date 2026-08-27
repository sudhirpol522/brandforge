from __future__ import annotations

import asyncio

from temporalio.client import Client
from temporalio.worker import Worker

from brandforge.config import Settings
from brandforge.integrations.temporal_workflow import (
    HumanApprovalCoordinator,
    checkpoint_activity,
)


async def run() -> None:
    settings = Settings.from_env()
    client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[HumanApprovalCoordinator],
        activities=[checkpoint_activity],
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(run())
