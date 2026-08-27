import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from brandforge.exceptions import NotFoundError
from brandforge.integrations.clip_scorer import DeterministicEmbeddingProvider
from brandforge.integrations.retrieval_repository import SQLiteRetrievalRepository
from brandforge.retrieval import (
    ApprovalStatus,
    AssetKind,
    IndexedMultimodalRecord,
    Modality,
    PolicyStatus,
    SearchRequest,
    normalize_embedding,
    validate_normalized_embedding,
)


class RetrievalFoundationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.repository = SQLiteRetrievalRepository(
            Path(self.directory.name) / "brandforge.db"
        )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def record(
        self,
        record_id: str,
        *,
        tenant_id: str = "tenant-a",
        vector: tuple[float, ...] = (1.0, 0.0, 0.0),
        source_hash: str = "a" * 64,
        approval_status: ApprovalStatus = ApprovalStatus.APPROVED,
        policy_status: PolicyStatus = PolicyStatus.ALLOWED,
        source_id: str | None = None,
    ) -> IndexedMultimodalRecord:
        now = datetime.now(UTC)
        return IndexedMultimodalRecord(
            id=record_id,
            tenant_id=tenant_id,
            source_type="asset",
            source_id=source_id or f"source-{record_id}",
            modality=Modality.IMAGE,
            embedding=vector,
            embedding_model="test-model",
            embedding_model_version="v1",
            embedding_dimension=3,
            campaign_id="campaign-source",
            object_key=f"approved/{record_id}.png",
            asset_kind=AssetKind.APPROVED_IMAGE,
            media_type="image/png",
            approval_status=approval_status,
            policy_status=policy_status,
            source_hash=source_hash,
            created_at=now,
            updated_at=now,
            indexed_at=now,
        )

    def test_vectors_are_finite_normalized_and_dimension_checked(self) -> None:
        self.assertAlmostEqual(sum(value * value for value in normalize_embedding((3.0, 4.0))), 1)
        with self.assertRaises(ValueError):
            validate_normalized_embedding((1.0, 1.0))
        with self.assertRaises(ValueError):
            validate_normalized_embedding((float("nan"), 0.0))

    def test_upsert_is_idempotent_for_model_source_hash(self) -> None:
        first = self.repository.upsert(self.record("ret_first", source_id="same-source"))
        second = self.repository.upsert(self.record("ret_second", source_id="same-source"))
        self.assertEqual(first.id, second.id)
        self.assertEqual(len(self.repository.list("tenant-a")), 1)

    def test_search_filters_tenant_approval_and_policy_before_scoring(self) -> None:
        self.repository.upsert(self.record("ret_allowed"))
        self.repository.upsert(
            self.record(
                "ret_blocked",
                vector=(0.0, 1.0, 0.0),
                source_hash="b" * 64,
                policy_status=PolicyStatus.BLOCKED,
            )
        )
        self.repository.upsert(
            self.record(
                "ret_other_tenant",
                tenant_id="tenant-b",
                source_hash="c" * 64,
            )
        )
        results = self.repository.search(
            SearchRequest(
                tenant_id="tenant-a",
                query_embedding=(1.0, 0.0, 0.0),
                embedding_model="test-model",
                embedding_model_version="v1",
                embedding_dimension=3,
                top_k=10,
                candidate_limit=20,
            )
        )
        self.assertEqual([result.record.id for result in results], ["ret_allowed"])
        with self.assertRaises(NotFoundError):
            self.repository.get("tenant-a", "ret_other_tenant")

    def test_deterministic_provider_is_stable_and_labeled_synthetic(self) -> None:
        provider = DeterministicEmbeddingProvider(dimension=8)
        first = provider.embed_text("same input")
        second = provider.embed_text("same input")
        self.assertEqual(first.vector, second.vector)
        self.assertTrue(first.synthetic)
        self.assertIn("non-production", first.model)


if __name__ == "__main__":
    unittest.main()
