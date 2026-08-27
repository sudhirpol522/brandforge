from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .agents.preferences import PairwiseExample, PairwisePreferenceModel
from .domain import ScoreBreakdown
from .preference_dataset import (
    CuratedComparison,
    DatasetSplits,
    dataset_fingerprint,
    grouped_split,
    import_jsonl,
)


def score_breakdown(features: dict[str, float]) -> ScoreBreakdown:
    return ScoreBreakdown(
        brief_alignment=features["brief_alignment"],
        visual_alignment=features["visual_alignment"],
        copy_image_consistency=features["copy_image_consistency"],
        visual_quality=features["visual_quality"],
        brand_compliance=features["brand_compliance"],
        accessibility=features["accessibility"],
        claims_safety=features["claims_safety"],
    )


def pairwise_accuracy(
    model: PairwisePreferenceModel,
    rows: Sequence[CuratedComparison],
) -> float:
    if not rows:
        return 0.0
    correct = sum(
        model.predict_pair(
            score_breakdown(row.preferred_features),
            score_breakdown(row.rejected_features),
        )
        >= 0.5
        for row in rows
    )
    return correct / len(rows)


def expected_calibration_error(
    probabilities: Sequence[float],
    labels: Sequence[int],
    *,
    bins: int = 10,
) -> float:
    if len(probabilities) != len(labels) or not probabilities:
        return 0.0
    if bins < 1:
        raise ValueError("bins must be positive")
    total = len(probabilities)
    error = 0.0
    for index in range(bins):
        lower = index / bins
        upper = (index + 1) / bins
        members = [
            position
            for position, probability in enumerate(probabilities)
            if lower <= probability < upper or (index == bins - 1 and probability == 1.0)
        ]
        if not members:
            continue
        confidence = statistics.fmean(probabilities[position] for position in members)
        accuracy = statistics.fmean(labels[position] for position in members)
        error += len(members) / total * abs(accuracy - confidence)
    return error


def ndcg_at_3(
    model: PairwisePreferenceModel,
    rows: Sequence[CuratedComparison],
) -> float:
    campaigns = _campaign_candidates(rows)
    values: list[float] = []
    for candidates, winners in campaigns.values():
        ranking = sorted(
            candidates,
            key=lambda candidate: model.predict(score_breakdown(candidates[candidate])),
            reverse=True,
        )[:3]
        grades = [1 if candidate in winners else 0 for candidate in ranking]
        dcg = sum(grade / math.log2(index + 2) for index, grade in enumerate(grades))
        ideal_grades = sorted(
            (1 if candidate in winners else 0 for candidate in candidates),
            reverse=True,
        )[:3]
        ideal = sum(
            grade / math.log2(index + 2) for index, grade in enumerate(ideal_grades)
        )
        values.append(dcg / ideal if ideal else 0.0)
    return statistics.fmean(values) if values else 0.0


def human_top_choice_selection_rate(
    model: PairwisePreferenceModel,
    rows: Sequence[CuratedComparison],
) -> float:
    campaigns = _campaign_candidates(rows)
    if not campaigns:
        return 0.0
    correct = 0
    for candidates, winners in campaigns.values():
        selected = max(
            candidates,
            key=lambda candidate: model.predict(score_breakdown(candidates[candidate])),
        )
        correct += selected in winners
    return correct / len(campaigns)


def train_model(
    rows: Sequence[CuratedComparison],
    *,
    dataset_fingerprint_value: str,
    split_fingerprint: str,
    learning_rate: float = 0.08,
    epochs: int = 250,
    l2: float = 0.01,
) -> PairwisePreferenceModel:
    examples = [
        PairwiseExample(
            preferred=score_breakdown(row.preferred_features),
            rejected=score_breakdown(row.rejected_features),
        )
        for row in rows
    ]
    return PairwisePreferenceModel().fit(
        examples,
        learning_rate=learning_rate,
        epochs=epochs,
        l2=l2,
        dataset_fingerprint=dataset_fingerprint_value,
        split_fingerprint=split_fingerprint,
    )


def evaluate(
    model: PairwisePreferenceModel,
    splits: DatasetSplits,
    *,
    minimum_slice_size: int = 5,
) -> dict[str, Any]:
    test_rows = splits.test
    probabilities = [
        model.predict_pair(
            score_breakdown(row.preferred_features),
            score_breakdown(row.rejected_features),
        )
        for row in test_rows
    ]
    source = (
        "synthetic"
        if any(
            row.synthetic or row.dataset_source == "synthetic"
            for row in (*splits.train, *splits.validation, *splits.test)
        )
        else "human_curated"
    )
    all_rows = (*splits.train, *splits.validation, *splits.test)
    warnings: list[str] = []
    by_brand = _slices(
        model,
        test_rows,
        key=lambda row: row.brand,
        minimum_size=minimum_slice_size,
        warnings=warnings,
        label="brand",
    )
    by_category = _slices(
        model,
        test_rows,
        key=lambda row: row.campaign_category,
        minimum_size=minimum_slice_size,
        warnings=warnings,
        label="campaign_category",
    )
    return {
        "schema_version": 1,
        "dataset": {
            "source": source,
            "synthetic": source == "synthetic",
            "fingerprint": dataset_fingerprint(all_rows),
            "split_fingerprint": splits.fingerprint,
            "split_strategy": splits.strategy,
        },
        "model": {
            "version": model.model_version,
            "training_examples": model.training_examples,
            "features": list(model.weights),
            "hyperparameters": model.training_hyperparameters,
        },
        "counts": {
            "train": len(splits.train),
            "validation": len(splits.validation),
            "test": len(splits.test),
        },
        "metrics": {
            "pairwise_accuracy": round(pairwise_accuracy(model, test_rows), 6),
            "ndcg_at_3": round(ndcg_at_3(model, test_rows), 6),
            "expected_calibration_error": round(
                expected_calibration_error(probabilities, [1] * len(probabilities)), 6
            ),
            "human_top_choice_selection_rate": round(
                human_top_choice_selection_rate(model, test_rows), 6
            ),
        },
        "slices": {"brand": by_brand, "campaign_category": by_category},
        "warnings": warnings,
        "disclaimer": (
            "Synthetic comparison metrics verify training and evaluation plumbing only; they are "
            "not evidence of human preference lift."
            if source == "synthetic"
            else "Metrics describe only the supplied versioned, held-out curated comparisons."
        ),
    }


def markdown_report(report: dict[str, Any]) -> str:
    dataset = report["dataset"]
    rows = [
        "# BrandForge preference evaluation",
        "",
        f"Model: `{report['model']['version']}`.",
        "",
    ]
    if dataset["synthetic"]:
        rows.extend(
            [
                "> Synthetic smoke-test results. These are not human preference claims.",
                "",
            ]
        )
    rows.extend(
        [
            "| Metric | Value |",
            "|---|---:|",
            f"| Pairwise accuracy | {report['metrics']['pairwise_accuracy']:.4f} |",
            f"| NDCG@3 | {report['metrics']['ndcg_at_3']:.4f} |",
            f"| Expected calibration error | "
            f"{report['metrics']['expected_calibration_error']:.4f} |",
            f"| Human top-choice selection rate | "
            f"{report['metrics']['human_top_choice_selection_rate']:.4f} |",
            "",
            f"Train/validation/test rows: {report['counts']['train']}/"
            f"{report['counts']['validation']}/{report['counts']['test']}.",
            "",
            str(report["disclaimer"]),
            "",
        ]
    )
    if report["warnings"]:
        rows.extend(["Warnings:", ""])
        rows.extend(f"- {warning}" for warning in report["warnings"])
        rows.append("")
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


def _campaign_candidates(
    rows: Sequence[CuratedComparison],
) -> dict[str, tuple[dict[str, dict[str, float]], set[str]]]:
    candidates: dict[str, dict[str, dict[str, float]]] = defaultdict(dict)
    winners: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        candidates[row.campaign_id][row.preferred_variant_id] = row.preferred_features
        candidates[row.campaign_id][row.rejected_variant_id] = row.rejected_features
        winners[row.campaign_id].add(row.preferred_variant_id)
    return {
        campaign_id: (campaign_candidates, winners[campaign_id])
        for campaign_id, campaign_candidates in candidates.items()
    }


def _slices(
    model: PairwisePreferenceModel,
    rows: Sequence[CuratedComparison],
    *,
    key: Any,
    minimum_size: int,
    warnings: list[str],
    label: str,
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[CuratedComparison]] = defaultdict(list)
    for row in rows:
        grouped[str(key(row))].append(row)
    result: dict[str, dict[str, Any]] = {}
    for value, slice_rows in sorted(grouped.items()):
        if len(slice_rows) < minimum_size:
            result[value] = {"sample_count": len(slice_rows), "suppressed": True}
            warnings.append(
                f"{label} slice {value!r} suppressed below {minimum_size} comparisons"
            )
        else:
            result[value] = {
                "sample_count": len(slice_rows),
                "suppressed": False,
                "pairwise_accuracy": round(pairwise_accuracy(model, slice_rows), 6),
                "ndcg_at_3": round(ndcg_at_3(model, slice_rows), 6),
                "top_choice_rate": round(
                    human_top_choice_selection_rate(model, slice_rows), 6
                ),
            }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Train and evaluate BrandForge preferences")
    parser.add_argument(
        "--dataset",
        default="evals/preference_comparisons.synthetic.jsonl",
    )
    parser.add_argument("--tenant", default="synthetic-tenant")
    parser.add_argument("--dataset-version", default="preference-synthetic-v1")
    parser.add_argument("--model-output", default="reports/preference-model.synthetic.json")
    parser.add_argument(
        "--json-output", default="reports/preference-evaluation.synthetic.json"
    )
    parser.add_argument(
        "--markdown-output", default="reports/preference-evaluation.synthetic.md"
    )
    arguments = parser.parse_args()
    rows = import_jsonl(
        arguments.dataset,
        tenant_id=arguments.tenant,
        dataset_version=arguments.dataset_version,
    )
    splits = grouped_split(rows)
    model = train_model(
        splits.train,
        dataset_fingerprint_value=dataset_fingerprint(rows),
        split_fingerprint=splits.fingerprint,
    )
    Path(arguments.model_output).parent.mkdir(parents=True, exist_ok=True)
    model.save(arguments.model_output)
    report = evaluate(model, splits)
    write_report(
        report,
        json_path=arguments.json_output,
        markdown_path=arguments.markdown_output,
    )
    print(markdown_report(report))


if __name__ == "__main__":
    main()
