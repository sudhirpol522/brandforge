from __future__ import annotations

import argparse
import json
import math
import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class RetrievalEvaluationQuery:
    query_id: str
    modality: str
    tenant_id: str
    judgments: dict[str, int]
    baseline_ranking: tuple[str, ...]
    reranked_ranking: tuple[str, ...]
    policy_violations: frozenset[str]
    brand: str
    campaign_category: str
    dataset_source: str
    dataset_version: str
    query_text: str | None = None
    image_fixture: str | None = None
    baseline_latency_ms: float = 0.0
    reranked_latency_ms: float = 0.0

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> RetrievalEvaluationQuery:
        judgments = {
            str(item["candidate_id"]): int(item["relevance"])
            for item in raw["judgments"]
        }
        violations = frozenset(
            str(item["candidate_id"])
            for item in raw["judgments"]
            if bool(item.get("policy_violation", False))
        )
        query = cls(
            query_id=str(raw["query_id"]),
            modality=str(raw["modality"]),
            tenant_id=str(raw["tenant_id"]),
            judgments=judgments,
            baseline_ranking=tuple(str(value) for value in raw["baseline_ranking"]),
            reranked_ranking=tuple(str(value) for value in raw["reranked_ranking"]),
            policy_violations=violations,
            brand=str(raw["brand"]),
            campaign_category=str(raw["campaign_category"]),
            dataset_source=str(raw["dataset_source"]),
            dataset_version=str(raw["dataset_version"]),
            query_text=str(raw["query_text"]) if raw.get("query_text") else None,
            image_fixture=(
                str(raw["image_fixture"]) if raw.get("image_fixture") else None
            ),
            baseline_latency_ms=float(raw.get("baseline_latency_ms", 0.0)),
            reranked_latency_ms=float(raw.get("reranked_latency_ms", 0.0)),
        )
        query.validate()
        return query

    def validate(self) -> None:
        if self.modality not in {"text", "image"}:
            raise ValueError("query modality must be text or image")
        if self.modality == "text" and not self.query_text:
            raise ValueError("text queries require query_text")
        if self.modality == "image" and not self.image_fixture:
            raise ValueError("image queries require image_fixture")
        if not self.query_id or not self.tenant_id or not self.judgments:
            raise ValueError("query_id, tenant_id, and judgments are required")
        if any(grade < 0 or grade > 3 for grade in self.judgments.values()):
            raise ValueError("relevance grades must be between 0 and 3")
        for ranking in (self.baseline_ranking, self.reranked_ranking):
            if len(ranking) != len(set(ranking)):
                raise ValueError("rankings must not contain duplicate candidate IDs")
            if any(candidate not in self.judgments for candidate in ranking):
                raise ValueError("rankings contain a candidate without a judgment")
        if min(self.baseline_latency_ms, self.reranked_latency_ms) < 0:
            raise ValueError("latency cannot be negative")


def load_jsonl(path: str | Path) -> list[RetrievalEvaluationQuery]:
    queries: list[RetrievalEvaluationQuery] = []
    for line_number, line in enumerate(Path(path).read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
            queries.append(RetrievalEvaluationQuery.from_dict(raw))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError(
                f"invalid retrieval judgment on line {line_number}: {error}"
            ) from error
    if not queries:
        raise ValueError("retrieval judgment dataset is empty")
    versions = {(query.dataset_source, query.dataset_version) for query in queries}
    if len(versions) != 1:
        raise ValueError("one evaluation run must use one dataset source and version")
    return queries


def recall_at(ranking: Sequence[str], judgments: dict[str, int], k: int) -> float:
    relevant = {candidate for candidate, grade in judgments.items() if grade > 0}
    if not relevant:
        return 0.0
    return len(relevant.intersection(ranking[:k])) / len(relevant)


def ndcg_at(ranking: Sequence[str], judgments: dict[str, int], k: int) -> float:
    actual = _dcg([judgments.get(candidate, 0) for candidate in ranking[:k]])
    ideal = _dcg(sorted(judgments.values(), reverse=True)[:k])
    return actual / ideal if ideal else 0.0


def reciprocal_rank(ranking: Sequence[str], judgments: dict[str, int]) -> float:
    for index, candidate in enumerate(ranking, 1):
        if judgments.get(candidate, 0) > 0:
            return 1.0 / index
    return 0.0


def pairwise_ranking_accuracy(
    ranking: Sequence[str], judgments: dict[str, int]
) -> float:
    positions = {candidate: index for index, candidate in enumerate(ranking)}
    correct = 0
    total = 0
    candidates = list(judgments)
    for left_index, left in enumerate(candidates):
        for right in candidates[left_index + 1 :]:
            if judgments[left] == judgments[right]:
                continue
            if left not in positions or right not in positions:
                continue
            total += 1
            preferred = left if judgments[left] > judgments[right] else right
            rejected = right if preferred == left else left
            correct += positions[preferred] < positions[rejected]
    return correct / total if total else 0.0


def policy_violation_rate(
    ranking: Sequence[str], policy_violations: set[str] | frozenset[str], k: int
) -> float:
    shown = ranking[:k]
    if not shown:
        return 0.0
    return sum(candidate in policy_violations for candidate in shown) / len(shown)


def evaluate(queries: Sequence[RetrievalEvaluationQuery]) -> dict[str, Any]:
    if not queries:
        raise ValueError("queries are required")
    baseline = _aggregate(queries, "baseline_ranking", "baseline_latency_ms")
    reranked = _aggregate(queries, "reranked_ranking", "reranked_latency_ms")
    source = queries[0].dataset_source
    provenance = "synthetic" if source.lower() == "synthetic" else "human"
    return {
        "schema_version": 1,
        "dataset": {
            "source": source,
            "version": queries[0].dataset_version,
            "provenance": provenance,
            "synthetic": provenance == "synthetic",
        },
        "query_count": len(queries),
        "judgment_count": sum(len(query.judgments) for query in queries),
        "embedding_version": "dataset-snapshot",
        "reranker_version": "cross-modal-policy-v1",
        "baseline": baseline,
        "reranked": reranked,
        "delta": {
            metric: round(float(reranked[metric]) - float(baseline[metric]), 6)
            for metric in (
                "recall_at_10",
                "recall_at_50",
                "ndcg_at_10",
                "mrr",
                "pairwise_accuracy",
                "policy_violation_rate",
            )
        },
        "disclaimer": (
            "Synthetic fixture metrics verify evaluation plumbing only and are not human-study "
            "or production retrieval evidence."
            if provenance == "synthetic"
            else "Human dataset metrics apply only to the versioned reviewed judgments supplied."
        ),
    }


def _aggregate(
    queries: Sequence[RetrievalEvaluationQuery],
    ranking_field: str,
    latency_field: str,
) -> dict[str, float | int]:
    rankings = [getattr(query, ranking_field) for query in queries]
    latencies = [float(getattr(query, latency_field)) for query in queries]
    return {
        "recall_at_10": _mean(
            recall_at(ranking, query.judgments, 10)
            for query, ranking in zip(queries, rankings, strict=True)
        ),
        "recall_at_50": _mean(
            recall_at(ranking, query.judgments, 50)
            for query, ranking in zip(queries, rankings, strict=True)
        ),
        "ndcg_at_10": _mean(
            ndcg_at(ranking, query.judgments, 10)
            for query, ranking in zip(queries, rankings, strict=True)
        ),
        "mrr": _mean(
            reciprocal_rank(ranking, query.judgments)
            for query, ranking in zip(queries, rankings, strict=True)
        ),
        "pairwise_accuracy": _mean(
            pairwise_ranking_accuracy(ranking, query.judgments)
            for query, ranking in zip(queries, rankings, strict=True)
        ),
        "policy_violation_rate": _mean(
            policy_violation_rate(ranking, query.policy_violations, 10)
            for query, ranking in zip(queries, rankings, strict=True)
        ),
        "latency_p50_ms": round(_percentile(latencies, 0.50), 6),
        "latency_p95_ms": round(_percentile(latencies, 0.95), 6),
    }


def markdown_report(report: dict[str, Any]) -> str:
    dataset = report["dataset"]
    rows = [
        "# BrandForge retrieval evaluation",
        "",
        f"Dataset: `{dataset['source']}` version `{dataset['version']}`.",
        "",
    ]
    if dataset["synthetic"]:
        rows.extend(
            [
                "> Synthetic smoke-test results. These are not human or production quality claims.",
                "",
            ]
        )
    rows.extend(
        [
            "| Metric | Baseline | Reranked | Delta |",
            "|---|---:|---:|---:|",
        ]
    )
    for metric in (
        "recall_at_10",
        "recall_at_50",
        "ndcg_at_10",
        "mrr",
        "pairwise_accuracy",
        "policy_violation_rate",
    ):
        rows.append(
            f"| {metric} | {report['baseline'][metric]:.4f} | "
            f"{report['reranked'][metric]:.4f} | {report['delta'][metric]:+.4f} |"
        )
    rows.extend(
        [
            "",
            f"Queries: {report['query_count']}; judgments: {report['judgment_count']}.",
            "",
            f"Baseline latency p50/p95: {report['baseline']['latency_p50_ms']:.2f}/"
            f"{report['baseline']['latency_p95_ms']:.2f} ms.",
            "",
            f"Reranked latency p50/p95: {report['reranked']['latency_p50_ms']:.2f}/"
            f"{report['reranked']['latency_p95_ms']:.2f} ms.",
            "",
            str(report["disclaimer"]),
            "",
        ]
    )
    return "\n".join(rows)


def write_report(
    report: dict[str, Any],
    *,
    json_path: str | Path,
    markdown_path: str | Path,
) -> None:
    json_target = Path(json_path)
    markdown_target = Path(markdown_path)
    json_target.parent.mkdir(parents=True, exist_ok=True)
    markdown_target.parent.mkdir(parents=True, exist_ok=True)
    json_target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    markdown_target.write_text(markdown_report(report))


def _dcg(grades: Sequence[int]) -> float:
    return float(
        sum(
            (2**grade - 1) / math.log2(index + 2)
            for index, grade in enumerate(grades)
        )
    )


def _mean(values: Iterable[float]) -> float:
    materialized = list(values)
    return round(statistics.fmean(materialized), 6) if materialized else 0.0


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate BrandForge multimodal retrieval")
    parser.add_argument(
        "--dataset",
        default="evals/retrieval_judgments.synthetic.jsonl",
    )
    parser.add_argument(
        "--json-output",
        default="reports/retrieval-evaluation.synthetic.json",
    )
    parser.add_argument(
        "--markdown-output",
        default="reports/retrieval-evaluation.synthetic.md",
    )
    arguments = parser.parse_args()
    report = evaluate(load_jsonl(arguments.dataset))
    write_report(
        report,
        json_path=arguments.json_output,
        markdown_path=arguments.markdown_output,
    )
    print(markdown_report(report))


if __name__ == "__main__":
    main()
