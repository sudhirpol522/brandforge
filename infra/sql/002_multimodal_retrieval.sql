-- Multimodal retrieval schema. Replace vector(512) before applying when a configured
-- embedding model uses a different fixed dimension.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS retrieval_records (
  id VARCHAR(64) PRIMARY KEY,
  tenant_id VARCHAR(160) NOT NULL,
  source_type VARCHAR(80) NOT NULL,
  source_id VARCHAR(160) NOT NULL,
  modality VARCHAR(16) NOT NULL CHECK (modality IN ('text', 'image')),
  embedding vector(512) NOT NULL,
  embedding_model VARCHAR(160) NOT NULL,
  embedding_model_version VARCHAR(160) NOT NULL,
  embedding_dimension INTEGER NOT NULL CHECK (embedding_dimension = 512),
  content TEXT,
  source_uri TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  status VARCHAR(24) NOT NULL CHECK (
    status IN ('pending', 'ready', 'failed', 'quarantined')
  ),
  campaign_id VARCHAR(64),
  asset_id VARCHAR(64),
  object_key TEXT,
  asset_kind VARCHAR(40),
  media_type VARCHAR(120),
  brand VARCHAR(160),
  campaign_category VARCHAR(160),
  approval_status VARCHAR(24) NOT NULL CHECK (
    approval_status IN ('approved', 'unapproved')
  ),
  policy_status VARCHAR(24) NOT NULL CHECK (
    policy_status IN ('allowed', 'blocked', 'quarantined')
  ),
  source_hash CHAR(64) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  indexed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (
    tenant_id,
    embedding_model,
    embedding_model_version,
    source_type,
    source_id,
    source_hash
  )
);

CREATE INDEX IF NOT EXISTS idx_retrieval_records_hnsw
  ON retrieval_records USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_retrieval_records_filters
  ON retrieval_records (
    tenant_id,
    embedding_model,
    embedding_model_version,
    status,
    approval_status,
    policy_status,
    asset_kind
  );
CREATE INDEX IF NOT EXISTS idx_retrieval_records_campaign
  ON retrieval_records (tenant_id, campaign_id);

ALTER TABLE retrieval_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE retrieval_records FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS retrieval_records_tenant_isolation ON retrieval_records;
CREATE POLICY retrieval_records_tenant_isolation ON retrieval_records
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

REVOKE ALL ON retrieval_records FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON retrieval_records TO brandforge_app;
