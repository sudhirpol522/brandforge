-- Reference production migration. Run as a database administrator after creating:
--   brandforge_app    (NOINHERIT, no BYPASSRLS)
--   brandforge_worker (NOINHERIT, BYPASSRLS, used only for the outbox publisher)

CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE campaigns ENABLE ROW LEVEL SECURITY;
ALTER TABLE campaigns FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS campaigns_tenant_isolation ON campaigns;
CREATE POLICY campaigns_tenant_isolation ON campaigns
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

ALTER TABLE outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE outbox FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS outbox_tenant_isolation ON outbox;
CREATE POLICY outbox_tenant_isolation ON outbox
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

ALTER TABLE idempotency ENABLE ROW LEVEL SECURITY;
ALTER TABLE idempotency FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS idempotency_tenant_isolation ON idempotency;
CREATE POLICY idempotency_tenant_isolation ON idempotency
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

REVOKE ALL ON campaigns, outbox, idempotency FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE ON campaigns, outbox, idempotency TO brandforge_app;
GRANT SELECT, UPDATE ON outbox TO brandforge_worker;
