from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy


@dataclass(slots=True)
class CoordinatorInput:
    tenant_id: str
    campaign_id: str


@dataclass(slots=True)
class ReviewSignal:
    decision: str
    reviewer_id: str
    artifact_version: int


@activity.defn
async def checkpoint_activity(payload: dict[str, str]) -> dict[str, str]:
    return payload


@workflow.defn
class HumanApprovalCoordinator:
    """Temporal control plane for multi-day pauses; policy stays in core workflow code."""

    def __init__(self) -> None:
        self.state = "created"
        self.pending_signal: ReviewSignal | None = None
        self.history: list[str] = []

    @workflow.run
    async def run(self, request: CoordinatorInput) -> dict[str, object]:
        for gate, waiting_state in (
            ("brand_rules", "brand_rules_pending_approval"),
            ("plan", "plan_pending_approval"),
            ("variant", "variants_pending_approval"),
            ("final", "final_approval"),
        ):
            self.state = waiting_state
            self.pending_signal = None
            await workflow.execute_activity(
                checkpoint_activity,
                {
                    "tenant_id": request.tenant_id,
                    "campaign_id": request.campaign_id,
                    "state": waiting_state,
                },
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=5),
            )
            await workflow.wait_condition(lambda: self.pending_signal is not None)
            assert self.pending_signal is not None
            self.history.append(
                f"{gate}:{self.pending_signal.decision}:v{self.pending_signal.artifact_version}"
            )
            if self.pending_signal.decision == "cancelled":
                self.state = "cancelled"
                return {"state": self.state, "history": self.history}
            while self.pending_signal.decision != "approved":
                self.pending_signal = None
                await workflow.wait_condition(lambda: self.pending_signal is not None)
                assert self.pending_signal is not None
                self.history.append(
                    f"{gate}:{self.pending_signal.decision}:v{self.pending_signal.artifact_version}"
                )
        self.state = "completed"
        return {"state": self.state, "history": self.history}

    @workflow.signal
    async def review(self, signal: ReviewSignal) -> None:
        self.pending_signal = signal

    @workflow.query
    def current_state(self) -> str:
        return self.state
