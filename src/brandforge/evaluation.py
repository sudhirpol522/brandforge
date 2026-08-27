from __future__ import annotations

import argparse
import copy
import json
import math
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .agents.brand_compiler import BrandCompilerAgent
from .agents.creative import CreativeAgent
from .agents.planner import CampaignPlannerAgent
from .agents.reranker import MultimodalReranker
from .domain import CampaignBrief
from .model_gateway import DeterministicModelProvider, ModelGateway


@dataclass(frozen=True, slots=True)
class BenchmarkScenario:
    id: str
    brand_id: str
    brief_id: str
    guide_text: str
    brief: CampaignBrief


@dataclass(slots=True)
class SystemMetrics:
    name: str
    scenarios: int = 0
    task_successes: int = 0
    final_scores: list[float] = field(default_factory=list)
    brand_scores: list[float] = field(default_factory=list)
    visual_scores: list[float] = field(default_factory=list)
    accessibility_scores: list[float] = field(default_factory=list)
    claim_violation_count: int = 0
    latency_ms: list[float] = field(default_factory=list)
    estimated_calls: int = 0

    def summarize(self) -> dict[str, float | int | str]:
        return {
            "system": self.name,
            "scenarios": self.scenarios,
            "task_success_rate": _mean_rate(self.task_successes, self.scenarios),
            "mean_final_score": _mean(self.final_scores),
            "mean_brand_score": _mean(self.brand_scores),
            "mean_visual_score": _mean(self.visual_scores),
            "mean_accessibility_score": _mean(self.accessibility_scores),
            "claim_violation_rate": _mean_rate(self.claim_violation_count, self.scenarios),
            "p50_latency_ms": _percentile(self.latency_ms, 0.50),
            "p95_latency_ms": _percentile(self.latency_ms, 0.95),
            "estimated_model_calls_per_task": round(
                self.estimated_calls / max(1, self.scenarios), 2
            ),
        }


def load_scenarios(path: str | Path) -> list[BenchmarkScenario]:
    raw = json.loads(Path(path).read_text())
    scenarios: list[BenchmarkScenario] = []
    for brand in raw["brands"]:
        guide = _brand_guide(brand)
        for brief_raw in raw["briefs"]:
            scenario_id = f"{brand['id']}__{brief_raw['id']}"
            scenarios.append(
                BenchmarkScenario(
                    id=scenario_id,
                    brand_id=brand["id"],
                    brief_id=brief_raw["id"],
                    guide_text=guide,
                    brief=CampaignBrief(
                        product_name=f"{brand['name']} {brief_raw['product']}",
                        objective=brief_raw["objective"],
                        audience=brief_raw["audience"],
                        call_to_action=brief_raw["cta"],
                    ),
                )
            )
    return scenarios


def run_benchmark(scenarios: list[BenchmarkScenario]) -> dict[str, Any]:
    metrics = {
        "single_output": SystemMetrics("single_output"),
        "multi_agent_first": SystemMetrics("multi_agent_first"),
        "multi_agent_reranked": SystemMetrics("multi_agent_reranked"),
        "vision_reranked_review_ready": SystemMetrics("vision_reranked_review_ready"),
    }
    compiler = BrandCompilerAgent()
    planner = CampaignPlannerAgent()
    benchmark_started = time.perf_counter()

    for scenario in scenarios:
        scenario_started = time.perf_counter()
        rules, _ = compiler.run(scenario.guide_text)
        plan, _ = planner.run(scenario.brief, rules)
        gateway = ModelGateway(
            DeterministicModelProvider(),
            max_calls_per_campaign=50,
            max_cost_per_campaign_usd=5,
        )
        creative = CreativeAgent(gateway)
        reranker = MultimodalReranker()
        variants, _ = creative.run(scenario.id, scenario.brief, rules, plan, count=8)

        single_ranked, _ = reranker.run(
            scenario.brief, rules, [copy.deepcopy(variants[0])], top_k=1
        )
        elapsed = (time.perf_counter() - scenario_started) * 1000
        _record(metrics["single_output"], single_ranked[0], elapsed, calls=2)

        first_ranked, _ = reranker.run(scenario.brief, rules, [copy.deepcopy(variants[0])], top_k=1)
        _record(metrics["multi_agent_first"], first_ranked[0], elapsed, calls=16)

        ranked, _ = reranker.run(scenario.brief, rules, copy.deepcopy(variants), top_k=3)
        _record(metrics["multi_agent_reranked"], ranked[0], elapsed, calls=16)

        external_scores: dict[str, dict[str, float]] = {}
        for variant in ranked:
            _, vision, _ = creative.render_and_score(scenario.id, scenario.brief, rules, variant)
            if vision:
                external_scores[variant.id] = vision
        final, _ = reranker.run(
            scenario.brief,
            rules,
            ranked,
            top_k=3,
            external_visual_scores=external_scores,
        )
        final_elapsed = (time.perf_counter() - scenario_started) * 1000
        _record(
            metrics["vision_reranked_review_ready"],
            final[0],
            final_elapsed,
            calls=22,
        )

    return {
        "benchmark": "brandforge-benchmark-v1",
        "scenario_count": len(scenarios),
        "provider": "deterministic-fixture",
        "disclaimer": (
            "Offline reproducibility benchmark. Vision and cost values are fixture estimates, "
            "not production OpenAI or human preference results."
        ),
        "wall_time_seconds": round(time.perf_counter() - benchmark_started, 4),
        "systems": [value.summarize() for value in metrics.values()],
    }


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# BrandForge offline evaluation",
        "",
        f"- Scenarios: {result['scenario_count']}",
        f"- Provider: {result['provider']}",
        f"- Wall time: {result['wall_time_seconds']} seconds",
        f"- Note: {result['disclaimer']}",
        "",
        (
            "| System | Success | Final | Brand | Visual | A11y | "
            "Claim violations | Calls/task | p95 ms |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in result["systems"]:
        lines.append(
            "| {system} | {task_success_rate:.1%} | {mean_final_score:.3f} | "
            "{mean_brand_score:.3f} | {mean_visual_score:.3f} | "
            "{mean_accessibility_score:.3f} | {claim_violation_rate:.1%} | "
            "{estimated_model_calls_per_task:.1f} | {p95_latency_ms:.1f} |".format(**row)
        )
    lines.extend(
        [
            "",
            "Success requires final score >= 0.65, brand >= 0.70, accessibility >= 0.60, "
            "and zero unsupported-claim violations. Run a real OpenAI and human-review "
            "benchmark before placing improvement percentages on a resume.",
        ]
    )
    return "\n".join(lines)


def _record(metrics: SystemMetrics, variant: Any, latency_ms: float, calls: int) -> None:
    scores = variant.scores
    claim_violations = sum(
        1 for violation in variant.violations if violation.startswith("claim requires")
    )
    success = (
        scores.final >= 0.65
        and scores.brand_compliance >= 0.70
        and scores.accessibility >= 0.60
        and claim_violations == 0
    )
    metrics.scenarios += 1
    metrics.task_successes += int(success)
    metrics.final_scores.append(scores.final)
    metrics.brand_scores.append(scores.brand_compliance)
    metrics.visual_scores.append(scores.visual_alignment)
    metrics.accessibility_scores.append(scores.accessibility)
    metrics.claim_violation_count += int(claim_violations > 0)
    metrics.latency_ms.append(latency_ms)
    metrics.estimated_calls += calls


def _brand_guide(brand: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"{brand['name']} Brand Guide",
            f"Primary colors: {', '.join(brand['colors'])}",
            f"Typography: {', '.join(brand['fonts'])}",
            f"Voice: {', '.join(brand['tone'])}",
            "Logo clear space: 24px. Use only approved brand-color backgrounds.",
            f"Do not use: {', '.join(brand['prohibited'])}",
            "Required legal disclaimer: Terms and eligibility may apply.",
        ]
    )


def _mean(values: list[float]) -> float:
    return round(statistics.fmean(values), 4) if values else 0.0


def _mean_rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
    return round(ordered[index], 3)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the BrandForge offline benchmark")
    parser.add_argument(
        "--spec",
        default=str(Path(__file__).parents[2] / "evals" / "benchmark.json"),
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = run_benchmark(load_scenarios(args.spec))
    print(json.dumps(result, indent=2) if args.json else render_markdown(result))


if __name__ == "__main__":
    main()
