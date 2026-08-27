from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class AgentContract:
    name: str
    version: str
    allowed_tools: tuple[str, ...]
    timeout_seconds: int
    max_steps: int
    max_cost_usd: float
    input_schema: str
    output_schema: str
    escalation_conditions: tuple[str, ...]


@dataclass(slots=True)
class AgentTrace:
    agent: str
    version: str
    decision_summary: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    cost_usd: float = 0.0
    latency_ms: int = 0
