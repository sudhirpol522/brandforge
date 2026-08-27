from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .agents.preferences import FEATURES
from .domain import Campaign


@dataclass(frozen=True, slots=True)
class CuratedComparison:
    comparison_id: str
    tenant_id: str
    campaign_id: str
    feedback_id: str
    preferred_variant_id: str
    rejected_variant_id: str
    preferred_features: dict[str, float]
    rejected_features: dict[str, float]
    preferred_display_rank: int
    rejected_display_rank: int
    presentation_order: tuple[str, ...]
    reviewer_id: str
    curator_id: str
    curated_at: str
    brand: str
    campaign_category: str
    brief_fingerprint: str
    dataset_version: str
    source_version: str
    dataset_source: str = "human_curated"
    synthetic: bool = False

    def __post_init__(self) -> None:
        for name in (
            "comparison_id",
            "tenant_id",
            "campaign_id",
            "feedback_id",
            "preferred_variant_id",
            "rejected_variant_id",
            "reviewer_id",
            "curator_id",
            "curated_at",
            "brand",
            "campaign_category",
            "brief_fingerprint",
            "dataset_version",
            "source_version",
            "dataset_source",
        ):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required")
        if self.preferred_variant_id == self.rejected_variant_id:
            raise ValueError("preferred and rejected variants must differ")
        _validate_features(self.preferred_features, "preferred_features")
        _validate_features(self.rejected_features, "rejected_features")
        if min(self.preferred_display_rank, self.rejected_display_rank) < 1:
            raise ValueError("display ranks must be positive")
        if len(self.presentation_order) != len(set(self.presentation_order)):
            raise ValueError("presentation order must contain unique variant IDs")
        if self.preferred_variant_id not in self.presentation_order:
            raise ValueError("presentation order omits the preferred variant")
        if self.rejected_variant_id not in self.presentation_order:
            raise ValueError("presentation order omits the rejected variant")
        if len(self.brief_fingerprint) != 64:
            raise ValueError("brief_fingerprint must be a SHA-256 digest")

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> CuratedComparison:
        return cls(
            **{
                **dict(raw),
                "preferred_features": {
                    str(key): float(value)
                    for key, value in dict(raw["preferred_features"]).items()
                },
                "rejected_features": {
                    str(key): float(value)
                    for key, value in dict(raw["rejected_features"]).items()
                },
                "presentation_order": tuple(raw["presentation_order"]),
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DatasetSplits:
    train: tuple[CuratedComparison, ...]
    validation: tuple[CuratedComparison, ...]
    test: tuple[CuratedComparison, ...]
    fingerprint: str
    strategy: str

    def assert_no_leakage(self) -> None:
        split_rows = {
            "train": self.train,
            "validation": self.validation,
            "test": self.test,
        }
        campaign_owners: dict[str, str] = {}
        brief_owners: dict[str, str] = {}
        for split, rows in split_rows.items():
            for row in rows:
                previous_campaign = campaign_owners.setdefault(row.campaign_id, split)
                if previous_campaign != split:
                    raise ValueError("campaign leakage detected between dataset splits")
                previous_brief = brief_owners.setdefault(row.brief_fingerprint, split)
                if previous_brief != split:
                    raise ValueError("brief fingerprint leakage detected between dataset splits")


def build_comparisons(campaign: Campaign) -> list[CuratedComparison]:
    rows: list[CuratedComparison] = []
    for feedback in campaign.feedback:
        if not feedback.curated or feedback.curation_status != "curated":
            continue
        if not feedback.curated_by or not feedback.curated_at or not feedback.dataset_version:
            raise ValueError("curated feedback is missing curator metadata")
        _validate_features(feedback.preferred_features, "preferred_features")
        for rejected_id in feedback.rejected_variant_ids:
            rejected_features = feedback.rejected_features.get(rejected_id)
            if rejected_features is None:
                raise ValueError(f"feedback omits frozen features for {rejected_id}")
            identity = f"{campaign.id}:{feedback.id}:{rejected_id}:{feedback.dataset_version}"
            rows.append(
                CuratedComparison(
                    comparison_id=f"cmpref_{hashlib.sha256(identity.encode()).hexdigest()[:16]}",
                    tenant_id=campaign.tenant_id,
                    campaign_id=campaign.id,
                    feedback_id=feedback.id,
                    preferred_variant_id=feedback.preferred_variant_id,
                    rejected_variant_id=rejected_id,
                    preferred_features=dict(feedback.preferred_features),
                    rejected_features=dict(rejected_features),
                    preferred_display_rank=feedback.display_ranks[feedback.preferred_variant_id],
                    rejected_display_rank=feedback.display_ranks[rejected_id],
                    presentation_order=tuple(feedback.presentation_order),
                    reviewer_id=feedback.reviewer_id,
                    curator_id=feedback.curated_by,
                    curated_at=feedback.curated_at,
                    brand=feedback.brand,
                    campaign_category=feedback.campaign_category,
                    brief_fingerprint=feedback.brief_fingerprint,
                    dataset_version=feedback.dataset_version,
                    source_version=feedback.source_version,
                )
            )
    return rows


def export_jsonl(
    rows: Sequence[CuratedComparison],
    path: str | Path,
    *,
    tenant_id: str,
) -> None:
    _validate_tenant(rows, tenant_id)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "".join(json.dumps(row.to_dict(), sort_keys=True) + "\n" for row in rows)
    )


def import_jsonl(
    path: str | Path,
    *,
    tenant_id: str,
    dataset_version: str | None = None,
) -> list[CuratedComparison]:
    rows: list[CuratedComparison] = []
    for line_number, line in enumerate(Path(path).read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = CuratedComparison.from_dict(json.loads(line))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError(f"invalid preference row on line {line_number}: {error}") from error
        if row.tenant_id != tenant_id:
            raise ValueError("preference import contains a cross-tenant row")
        if dataset_version is not None and row.dataset_version != dataset_version:
            raise ValueError("preference import contains a different dataset version")
        rows.append(row)
    if not rows:
        raise ValueError("preference dataset is empty")
    if len({row.comparison_id for row in rows}) != len(rows):
        raise ValueError("preference dataset contains duplicate comparison IDs")
    return rows


def grouped_split(
    rows: Sequence[CuratedComparison],
    *,
    train_ratio: float = 0.70,
    validation_ratio: float = 0.15,
    seed: str = "brandforge-preference-split-v1",
) -> DatasetSplits:
    if not rows:
        raise ValueError("preference rows are required")
    if not 0 < train_ratio < 1 or not 0 <= validation_ratio < 1:
        raise ValueError("split ratios are invalid")
    if train_ratio + validation_ratio >= 1:
        raise ValueError("train and validation ratios must leave a test split")
    groups: dict[str, list[CuratedComparison]] = {}
    for row in rows:
        groups.setdefault(row.brief_fingerprint, []).append(row)
    buckets: dict[str, list[CuratedComparison]] = {
        "train": [],
        "validation": [],
        "test": [],
    }
    for fingerprint, group in sorted(groups.items()):
        digest = hashlib.sha256(f"{seed}:{fingerprint}".encode()).digest()
        value = int.from_bytes(digest[:8], "big") / (2**64 - 1)
        split = (
            "train"
            if value < train_ratio
            else "validation"
            if value < train_ratio + validation_ratio
            else "test"
        )
        buckets[split].extend(group)
    if len(groups) >= 3:
        for empty_split in (
            split for split, values in buckets.items() if not values
        ):
            donor = max(buckets, key=lambda split: len(buckets[split]))
            donor_fingerprints = sorted(
                {row.brief_fingerprint for row in buckets[donor]}
            )
            moved_fingerprint = donor_fingerprints[-1]
            moved = [
                row
                for row in buckets[donor]
                if row.brief_fingerprint == moved_fingerprint
            ]
            buckets[donor] = [
                row
                for row in buckets[donor]
                if row.brief_fingerprint != moved_fingerprint
            ]
            buckets[empty_split].extend(moved)
    result = DatasetSplits(
        train=tuple(buckets["train"]),
        validation=tuple(buckets["validation"]),
        test=tuple(buckets["test"]),
        fingerprint=_split_fingerprint(buckets),
        strategy="brief-grouped-hash-v1",
    )
    result.assert_no_leakage()
    return result


def brand_held_out_split(
    rows: Sequence[CuratedComparison],
    *,
    held_out_brands: set[str],
    validation_brands: set[str] | None = None,
) -> DatasetSplits:
    if not held_out_brands:
        raise ValueError("at least one held-out brand is required")
    validation_brands = validation_brands or set()
    if held_out_brands.intersection(validation_brands):
        raise ValueError("test and validation brands must be disjoint")
    train = tuple(
        row
        for row in rows
        if row.brand not in held_out_brands and row.brand not in validation_brands
    )
    validation = tuple(row for row in rows if row.brand in validation_brands)
    test = tuple(row for row in rows if row.brand in held_out_brands)
    result = DatasetSplits(
        train=train,
        validation=validation,
        test=test,
        fingerprint=_split_fingerprint(
            {"train": list(train), "validation": list(validation), "test": list(test)}
        ),
        strategy="brand-held-out-v1",
    )
    result.assert_no_leakage()
    return result


def dataset_fingerprint(rows: Iterable[CuratedComparison]) -> str:
    payload = "\n".join(
        json.dumps(row.to_dict(), sort_keys=True, separators=(",", ":"))
        for row in sorted(rows, key=lambda value: value.comparison_id)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _validate_features(values: Mapping[str, float], name: str) -> None:
    if set(values) != set(FEATURES):
        raise ValueError(f"{name} must contain exactly the frozen critic features")
    for feature, value in values.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name}.{feature} must be numeric")
        if not math.isfinite(float(value)) or not 0.0 <= float(value) <= 1.0:
            raise ValueError(f"{name}.{feature} must be finite and between 0 and 1")


def _validate_tenant(rows: Sequence[CuratedComparison], tenant_id: str) -> None:
    if any(row.tenant_id != tenant_id for row in rows):
        raise ValueError("preference export contains a cross-tenant row")


def _split_fingerprint(splits: Mapping[str, Sequence[CuratedComparison]]) -> str:
    payload = {
        split: sorted(row.comparison_id for row in rows)
        for split, rows in sorted(splits.items())
    }
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
