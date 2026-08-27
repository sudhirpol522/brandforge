from __future__ import annotations

import json
import logging
import threading
from collections import defaultdict
from contextvars import ContextVar
from time import perf_counter
from typing import Any

from .security import redact_secrets

trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": redact_secrets(record.getMessage()),
            "trace_id": trace_id_var.get(),
        }
        for key in ("campaign_id", "tenant_id", "event_type", "duration_ms"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())


class MetricsRegistry:
    def __init__(self) -> None:
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self._durations: dict[tuple[str, tuple[tuple[str, str], ...]], list[float]] = defaultdict(
            list
        )
        self._lock = threading.Lock()

    @staticmethod
    def _key(name: str, labels: dict[str, str]) -> tuple[str, tuple[tuple[str, str], ...]]:
        return name, tuple(sorted(labels.items()))

    def increment(self, name: str, amount: float = 1.0, **labels: str) -> None:
        with self._lock:
            self._counters[self._key(name, labels)] += amount

    def observe(self, name: str, value: float, **labels: str) -> None:
        with self._lock:
            self._durations[self._key(name, labels)].append(value)

    def render_prometheus(self) -> str:
        lines: list[str] = []
        with self._lock:
            for (name, labels), value in sorted(self._counters.items()):
                lines.append(f"{name}{_render_labels(labels)} {value}")
            for (name, labels), values in sorted(self._durations.items()):
                lines.append(f"{name}_count{_render_labels(labels)} {len(values)}")
                lines.append(f"{name}_sum{_render_labels(labels)} {sum(values)}")
        return "\n".join(lines) + "\n"


class Timer:
    def __init__(self, registry: MetricsRegistry, name: str, **labels: str) -> None:
        self.registry = registry
        self.name = name
        self.labels = labels
        self.started = 0.0

    def __enter__(self) -> Timer:
        self.started = perf_counter()
        return self

    def __exit__(self, *_: object) -> None:
        self.registry.observe(self.name, perf_counter() - self.started, **self.labels)


def _render_labels(labels: tuple[tuple[str, str], ...]) -> str:
    if not labels:
        return ""
    rendered = ",".join(f'{key}="{value}"' for key, value in labels)
    return "{" + rendered + "}"


metrics = MetricsRegistry()
