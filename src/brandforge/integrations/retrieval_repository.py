from __future__ import annotations

import builtins
import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

from ..exceptions import NotFoundError
from ..retrieval import (
    ApprovalStatus,
    AssetKind,
    IndexedMultimodalRecord,
    Modality,
    PolicyStatus,
    RetrievalStatus,
    SearchRequest,
    SearchResult,
    cosine_similarity,
)


class SQLiteRetrievalRepository:
    """Bounded local vector store with SQL-side tenant and policy filtering."""

    def __init__(self, database_path: str | Path, *, max_candidates: int = 10_000) -> None:
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not 1 <= max_candidates <= 10_000:
            raise ValueError("max_candidates must be between 1 and 10000")
        self.max_candidates = max_candidates
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS retrieval_records (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    modality TEXT NOT NULL,
                    embedding TEXT NOT NULL,
                    embedding_model TEXT NOT NULL,
                    embedding_model_version TEXT NOT NULL,
                    embedding_dimension INTEGER NOT NULL,
                    content TEXT,
                    source_uri TEXT,
                    metadata TEXT NOT NULL,
                    status TEXT NOT NULL,
                    campaign_id TEXT,
                    asset_id TEXT,
                    object_key TEXT,
                    asset_kind TEXT,
                    media_type TEXT,
                    brand TEXT,
                    campaign_category TEXT,
                    approval_status TEXT NOT NULL,
                    policy_status TEXT NOT NULL,
                    source_hash TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    indexed_at TEXT,
                    UNIQUE (
                        tenant_id, embedding_model, embedding_model_version,
                        source_type, source_id, source_hash
                    )
                );
                CREATE INDEX IF NOT EXISTS idx_retrieval_lookup
                    ON retrieval_records (
                        tenant_id, embedding_model, embedding_model_version,
                        embedding_dimension, status, approval_status, policy_status
                    );
                CREATE INDEX IF NOT EXISTS idx_retrieval_campaign
                    ON retrieval_records (tenant_id, campaign_id, asset_kind);
                """
            )

    def upsert(self, record: IndexedMultimodalRecord) -> IndexedMultimodalRecord:
        values = _record_values(record)
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO retrieval_records (
                    id, tenant_id, source_type, source_id, modality, embedding,
                    embedding_model, embedding_model_version, embedding_dimension,
                    content, source_uri, metadata, status, campaign_id, asset_id,
                    object_key, asset_kind, media_type, brand, campaign_category,
                    approval_status, policy_status, source_hash, created_at, updated_at,
                    indexed_at
                ) VALUES (
                    :id, :tenant_id, :source_type, :source_id, :modality, :embedding,
                    :embedding_model, :embedding_model_version, :embedding_dimension,
                    :content, :source_uri, :metadata, :status, :campaign_id, :asset_id,
                    :object_key, :asset_kind, :media_type, :brand, :campaign_category,
                    :approval_status, :policy_status, :source_hash, :created_at, :updated_at,
                    :indexed_at
                )
                ON CONFLICT (
                    tenant_id, embedding_model, embedding_model_version,
                    source_type, source_id, source_hash
                ) DO UPDATE SET
                    modality = excluded.modality,
                    embedding = excluded.embedding,
                    embedding_dimension = excluded.embedding_dimension,
                    content = excluded.content,
                    source_uri = excluded.source_uri,
                    metadata = excluded.metadata,
                    status = excluded.status,
                    campaign_id = excluded.campaign_id,
                    asset_id = excluded.asset_id,
                    object_key = excluded.object_key,
                    asset_kind = excluded.asset_kind,
                    media_type = excluded.media_type,
                    brand = excluded.brand,
                    campaign_category = excluded.campaign_category,
                    approval_status = excluded.approval_status,
                    policy_status = excluded.policy_status,
                    updated_at = excluded.updated_at,
                    indexed_at = excluded.indexed_at
                """,
                values,
            )
            row = connection.execute(
                """
                SELECT * FROM retrieval_records
                WHERE tenant_id = ? AND embedding_model = ?
                  AND embedding_model_version = ? AND source_type = ?
                  AND source_id = ? AND source_hash IS ?
                """,
                (
                    record.tenant_id,
                    record.embedding_model,
                    record.embedding_model_version,
                    record.source_type,
                    record.source_id,
                    record.source_hash,
                ),
            ).fetchone()
        assert row is not None
        return _row_to_record(row)

    def get(self, tenant_id: str, record_id: str) -> IndexedMultimodalRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM retrieval_records WHERE tenant_id = ? AND id = ?",
                (tenant_id, record_id),
            ).fetchone()
        if row is None:
            raise NotFoundError(f"retrieval record {record_id} not found")
        return _row_to_record(row)

    def list(
        self,
        tenant_id: str,
        *,
        status: RetrievalStatus | None = None,
        limit: int = 100,
        campaign_id: str | None = None,
        embedding_model: str | None = None,
        embedding_model_version: str | None = None,
    ) -> list[IndexedMultimodalRecord]:
        clauses = ["tenant_id = ?"]
        parameters: list[object] = [tenant_id]
        for column, value in (
            ("status", status.value if status else None),
            ("campaign_id", campaign_id),
            ("embedding_model", embedding_model),
            ("embedding_model_version", embedding_model_version),
        ):
            if value is not None:
                clauses.append(f"{column} = ?")
                parameters.append(value)
        parameters.append(max(1, min(limit, self.max_candidates)))
        query = (
            "SELECT * FROM retrieval_records WHERE "
            + " AND ".join(clauses)
            + " ORDER BY indexed_at DESC, id LIMIT ?"
        )
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [_row_to_record(row) for row in rows]

    def search(self, request: SearchRequest) -> builtins.list[SearchResult]:
        clauses = [
            "tenant_id = ?",
            "embedding_model = ?",
            "embedding_model_version = ?",
            "embedding_dimension = ?",
            "status = ?",
        ]
        parameters: list[object] = [
            request.tenant_id,
            request.embedding_model,
            request.embedding_model_version,
            request.embedding_dimension,
            RetrievalStatus.READY.value,
        ]
        if request.approved_only:
            clauses.extend(["approval_status = ?", "policy_status = ?"])
            parameters.extend([ApprovalStatus.APPROVED.value, PolicyStatus.ALLOWED.value])
        if request.allowed_kinds:
            placeholders = ",".join("?" for _ in request.allowed_kinds)
            clauses.append(f"asset_kind IN ({placeholders})")
            parameters.extend(kind.value for kind in request.allowed_kinds)
        if request.campaign_id is not None:
            clauses.append("campaign_id = ?")
            parameters.append(request.campaign_id)
        if request.exclude_campaign_id is not None:
            clauses.append("(campaign_id IS NULL OR campaign_id != ?)")
            parameters.append(request.exclude_campaign_id)
        explicit_columns = {
            "source_type",
            "modality",
            "asset_kind",
            "media_type",
            "brand",
            "campaign_category",
            "approval_status",
            "policy_status",
            "campaign_id",
        }
        for key, value in request.filters.items():
            if key in explicit_columns:
                clauses.append(f"{key} IS ?")
                parameters.append(value)
            else:
                clauses.append("json_extract(metadata, ?) IS ?")
                parameters.extend([f'$."{key}"', value])
        limit = min(request.candidate_limit, self.max_candidates)
        parameters.append(limit)
        query = (
            "SELECT * FROM retrieval_records WHERE "
            + " AND ".join(clauses)
            + " ORDER BY indexed_at DESC, id LIMIT ?"
        )
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        scored = [
            SearchResult(
                record=record,
                similarity=cosine_similarity(request.query_embedding, record.embedding),
            )
            for record in (_row_to_record(row) for row in rows)
        ]
        return sorted(
            (item for item in scored if item.similarity >= request.min_similarity),
            key=lambda item: (-item.similarity, item.record.id),
        )[: request.top_k]

    def set_status(
        self,
        tenant_id: str,
        record_id: str,
        status: RetrievalStatus,
    ) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE retrieval_records SET status = ? WHERE tenant_id = ? AND id = ?",
                (status.value, tenant_id, record_id),
            )
        if cursor.rowcount == 0:
            raise NotFoundError(f"retrieval record {record_id} not found")

    def delete(self, tenant_id: str, record_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM retrieval_records WHERE tenant_id = ? AND id = ?",
                (tenant_id, record_id),
            )
        return cursor.rowcount > 0


class PostgreSQLRetrievalRepository:
    """Tenant-scoped pgvector repository using HNSW cosine search."""

    def __init__(self, database_url: str, *, dimension: int = 512) -> None:
        if not 2 <= dimension <= 4096:
            raise ValueError("dimension must be between 2 and 4096")
        self.dimension = dimension
        self.engine = create_engine(database_url, pool_pre_ping=True, pool_recycle=300)
        self._initialize()

    def _initialize(self) -> None:
        statements = [
            "CREATE EXTENSION IF NOT EXISTS vector",
            f"""
            CREATE TABLE IF NOT EXISTS retrieval_records (
                id VARCHAR(64) PRIMARY KEY,
                tenant_id VARCHAR(160) NOT NULL,
                source_type VARCHAR(80) NOT NULL,
                source_id VARCHAR(160) NOT NULL,
                modality VARCHAR(16) NOT NULL,
                embedding vector({self.dimension}) NOT NULL,
                embedding_model VARCHAR(160) NOT NULL,
                embedding_model_version VARCHAR(160) NOT NULL,
                embedding_dimension INTEGER NOT NULL,
                content TEXT,
                source_uri TEXT,
                metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                status VARCHAR(24) NOT NULL,
                campaign_id VARCHAR(64),
                asset_id VARCHAR(64),
                object_key TEXT,
                asset_kind VARCHAR(40),
                media_type VARCHAR(120),
                brand VARCHAR(160),
                campaign_category VARCHAR(160),
                approval_status VARCHAR(24) NOT NULL,
                policy_status VARCHAR(24) NOT NULL,
                source_hash CHAR(64),
                created_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ,
                indexed_at TIMESTAMPTZ,
                UNIQUE (
                    tenant_id, embedding_model, embedding_model_version,
                    source_type, source_id, source_hash
                )
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_retrieval_records_hnsw
            ON retrieval_records USING hnsw (embedding vector_cosine_ops)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_retrieval_records_filters
            ON retrieval_records (
                tenant_id, embedding_model, embedding_model_version,
                status, approval_status, policy_status, asset_kind
            )
            """,
        ]
        with self.engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))

    @staticmethod
    def _set_tenant(connection: Any, tenant_id: str) -> None:
        connection.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": tenant_id},
        )

    def upsert(self, record: IndexedMultimodalRecord) -> IndexedMultimodalRecord:
        if record.embedding_dimension != self.dimension:
            raise ValueError(
                f"record dimension {record.embedding_dimension} does not match {self.dimension}"
            )
        values = _record_values(record)
        values["embedding"] = _vector_literal(record.embedding)
        query = text(
            """
            INSERT INTO retrieval_records (
                id, tenant_id, source_type, source_id, modality, embedding,
                embedding_model, embedding_model_version, embedding_dimension,
                content, source_uri, metadata, status, campaign_id, asset_id,
                object_key, asset_kind, media_type, brand, campaign_category,
                approval_status, policy_status, source_hash, created_at, updated_at,
                indexed_at
            ) VALUES (
                :id, :tenant_id, :source_type, :source_id, :modality,
                CAST(:embedding AS vector), :embedding_model, :embedding_model_version,
                :embedding_dimension, :content, :source_uri, CAST(:metadata AS jsonb),
                :status, :campaign_id, :asset_id, :object_key, :asset_kind, :media_type,
                :brand, :campaign_category, :approval_status, :policy_status, :source_hash,
                :created_at, :updated_at, :indexed_at
            )
            ON CONFLICT (
                tenant_id, embedding_model, embedding_model_version,
                source_type, source_id, source_hash
            ) DO UPDATE SET
                modality = excluded.modality,
                embedding = excluded.embedding,
                embedding_dimension = excluded.embedding_dimension,
                content = excluded.content,
                source_uri = excluded.source_uri,
                metadata = excluded.metadata,
                status = excluded.status,
                campaign_id = excluded.campaign_id,
                asset_id = excluded.asset_id,
                object_key = excluded.object_key,
                asset_kind = excluded.asset_kind,
                media_type = excluded.media_type,
                brand = excluded.brand,
                campaign_category = excluded.campaign_category,
                approval_status = excluded.approval_status,
                policy_status = excluded.policy_status,
                updated_at = excluded.updated_at,
                indexed_at = excluded.indexed_at
            RETURNING *, embedding::text AS embedding_text
            """
        )
        with self.engine.begin() as connection:
            self._set_tenant(connection, record.tenant_id)
            row = connection.execute(query, values).mappings().one()
        return _mapping_to_record(row)

    def get(self, tenant_id: str, record_id: str) -> IndexedMultimodalRecord:
        with self.engine.connect() as connection:
            self._set_tenant(connection, tenant_id)
            row = connection.execute(
                text(
                    "SELECT *, embedding::text AS embedding_text FROM retrieval_records "
                    "WHERE tenant_id = :tenant_id AND id = :record_id"
                ),
                {"tenant_id": tenant_id, "record_id": record_id},
            ).mappings().first()
        if row is None:
            raise NotFoundError(f"retrieval record {record_id} not found")
        return _mapping_to_record(row)

    def list(
        self,
        tenant_id: str,
        *,
        status: RetrievalStatus | None = None,
        limit: int = 100,
        campaign_id: str | None = None,
        embedding_model: str | None = None,
        embedding_model_version: str | None = None,
    ) -> list[IndexedMultimodalRecord]:
        clauses = ["tenant_id = :tenant_id"]
        parameters: dict[str, object] = {
            "tenant_id": tenant_id,
            "limit": min(10_000, max(1, limit)),
        }
        for column, value in (
            ("status", status.value if status else None),
            ("campaign_id", campaign_id),
            ("embedding_model", embedding_model),
            ("embedding_model_version", embedding_model_version),
        ):
            if value is not None:
                clauses.append(f"{column} = :{column}")
                parameters[column] = value
        query = text(
            "SELECT *, embedding::text AS embedding_text FROM retrieval_records WHERE "
            + " AND ".join(clauses)
            + " ORDER BY indexed_at DESC, id LIMIT :limit"
        )
        with self.engine.connect() as connection:
            self._set_tenant(connection, tenant_id)
            rows = connection.execute(query, parameters).mappings().all()
        return [_mapping_to_record(row) for row in rows]

    def search(self, request: SearchRequest) -> builtins.list[SearchResult]:
        if request.embedding_dimension != self.dimension:
            raise ValueError(
                f"query dimension {request.embedding_dimension} does not match {self.dimension}"
            )
        clauses = [
            "tenant_id = :tenant_id",
            "embedding_model = :embedding_model",
            "embedding_model_version = :embedding_model_version",
            "embedding_dimension = :embedding_dimension",
            "status = 'ready'",
        ]
        parameters: dict[str, object] = {
            "tenant_id": request.tenant_id,
            "embedding_model": request.embedding_model,
            "embedding_model_version": request.embedding_model_version,
            "embedding_dimension": request.embedding_dimension,
            "query_embedding": _vector_literal(request.query_embedding),
            "candidate_limit": request.candidate_limit,
            "top_k": request.top_k,
            "min_similarity": request.min_similarity,
        }
        if request.approved_only:
            clauses.extend(["approval_status = 'approved'", "policy_status = 'allowed'"])
        if request.allowed_kinds:
            clauses.append("asset_kind = ANY(CAST(:allowed_kinds AS text[]))")
            parameters["allowed_kinds"] = (
                "{" + ",".join(kind.value for kind in request.allowed_kinds) + "}"
            )
        if request.campaign_id is not None:
            clauses.append("campaign_id = :campaign_id")
            parameters["campaign_id"] = request.campaign_id
        if request.exclude_campaign_id is not None:
            clauses.append("(campaign_id IS NULL OR campaign_id != :exclude_campaign_id)")
            parameters["exclude_campaign_id"] = request.exclude_campaign_id
        explicit_columns = {
            "source_type",
            "modality",
            "asset_kind",
            "media_type",
            "brand",
            "campaign_category",
            "approval_status",
            "policy_status",
            "campaign_id",
        }
        for index, (key, value) in enumerate(request.filters.items()):
            parameter = f"filter_{index}"
            if key in explicit_columns:
                clauses.append(f"{key} IS NOT DISTINCT FROM :{parameter}")
            else:
                key_parameter = f"filter_key_{index}"
                clauses.append(f"metadata ->> :{key_parameter} = CAST(:{parameter} AS text)")
                parameters[key_parameter] = key
            parameters[parameter] = value
        query = text(
            """
            WITH candidates AS (
                SELECT *, 1 - (embedding <=> CAST(:query_embedding AS vector)) AS similarity
                FROM retrieval_records
                WHERE """
            + " AND ".join(clauses)
            + """
                ORDER BY embedding <=> CAST(:query_embedding AS vector)
                LIMIT :candidate_limit
            )
            SELECT *, embedding::text AS embedding_text FROM candidates
            WHERE similarity >= :min_similarity
            ORDER BY similarity DESC, id
            LIMIT :top_k
            """
        )
        with self.engine.connect() as connection:
            self._set_tenant(connection, request.tenant_id)
            rows = connection.execute(query, parameters).mappings().all()
        return [
            SearchResult(record=_mapping_to_record(row), similarity=float(row["similarity"]))
            for row in rows
        ]

    def set_status(
        self,
        tenant_id: str,
        record_id: str,
        status: RetrievalStatus,
    ) -> None:
        with self.engine.begin() as connection:
            self._set_tenant(connection, tenant_id)
            result = connection.execute(
                text(
                    "UPDATE retrieval_records SET status = :status "
                    "WHERE tenant_id = :tenant_id AND id = :record_id"
                ),
                {"status": status.value, "tenant_id": tenant_id, "record_id": record_id},
            )
        if result.rowcount == 0:
            raise NotFoundError(f"retrieval record {record_id} not found")

    def delete(self, tenant_id: str, record_id: str) -> bool:
        with self.engine.begin() as connection:
            self._set_tenant(connection, tenant_id)
            result = connection.execute(
                text(
                    "DELETE FROM retrieval_records "
                    "WHERE tenant_id = :tenant_id AND id = :record_id"
                ),
                {"tenant_id": tenant_id, "record_id": record_id},
            )
        return result.rowcount > 0


def _record_values(record: IndexedMultimodalRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "tenant_id": record.tenant_id,
        "source_type": record.source_type,
        "source_id": record.source_id,
        "modality": record.modality.value,
        "embedding": json.dumps(record.embedding, separators=(",", ":")),
        "embedding_model": record.embedding_model,
        "embedding_model_version": record.embedding_model_version,
        "embedding_dimension": record.embedding_dimension,
        "content": record.content,
        "source_uri": record.source_uri,
        "metadata": json.dumps(dict(record.metadata), separators=(",", ":"), sort_keys=True),
        "status": record.status.value,
        "campaign_id": record.campaign_id,
        "asset_id": record.asset_id,
        "object_key": record.object_key,
        "asset_kind": record.asset_kind.value if isinstance(record.asset_kind, AssetKind) else None,
        "media_type": record.media_type,
        "brand": record.brand,
        "campaign_category": record.campaign_category,
        "approval_status": record.approval_status.value,
        "policy_status": record.policy_status.value,
        "source_hash": record.source_hash,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        "indexed_at": record.indexed_at.isoformat() if record.indexed_at else None,
    }


def _row_to_record(row: sqlite3.Row) -> IndexedMultimodalRecord:
    return _values_to_record(dict(row), embedding=json.loads(row["embedding"]))


def _mapping_to_record(row: Any) -> IndexedMultimodalRecord:
    raw = dict(row)
    embedding_text = str(raw.pop("embedding_text"))
    raw.pop("similarity", None)
    return _values_to_record(raw, embedding=json.loads(embedding_text))


def _values_to_record(
    values: dict[str, object], *, embedding: list[float]
) -> IndexedMultimodalRecord:
    raw_metadata = values.get("metadata")
    if isinstance(raw_metadata, str):
        metadata = json.loads(raw_metadata)
    else:
        metadata = raw_metadata or {}
    return IndexedMultimodalRecord(
        id=str(values["id"]),
        tenant_id=str(values["tenant_id"]),
        source_type=str(values["source_type"]),
        source_id=str(values["source_id"]),
        modality=Modality(str(values["modality"])),
        embedding=tuple(float(value) for value in embedding),
        embedding_model=str(values["embedding_model"]),
        embedding_model_version=str(values["embedding_model_version"]),
        embedding_dimension=int(str(values["embedding_dimension"])),
        content=str(values["content"]) if values.get("content") is not None else None,
        source_uri=(str(values["source_uri"]) if values.get("source_uri") is not None else None),
        metadata=metadata,
        status=RetrievalStatus(str(values["status"])),
        campaign_id=(str(values["campaign_id"]) if values.get("campaign_id") else None),
        asset_id=str(values["asset_id"]) if values.get("asset_id") else None,
        object_key=str(values["object_key"]) if values.get("object_key") else None,
        asset_kind=str(values["asset_kind"]) if values.get("asset_kind") else None,
        media_type=str(values["media_type"]) if values.get("media_type") else None,
        brand=str(values["brand"]) if values.get("brand") else None,
        campaign_category=(
            str(values["campaign_category"]) if values.get("campaign_category") else None
        ),
        approval_status=ApprovalStatus(str(values["approval_status"])),
        policy_status=PolicyStatus(str(values["policy_status"])),
        source_hash=str(values["source_hash"]) if values.get("source_hash") else None,
        created_at=_datetime(values.get("created_at")),
        updated_at=_datetime(values.get("updated_at")),
        indexed_at=_datetime(values.get("indexed_at")),
    )


def _datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _vector_literal(vector: tuple[float, ...]) -> str:
    return "[" + ",".join(format(value, ".17g") for value in vector) + "]"
