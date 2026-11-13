-- KnowledgeForge AI — Optional PostgreSQL Row-Level Security (RLS) Defense-in-Depth Migration
-- Enable in production after creating a non-superuser application DB role (e.g., kf_app).
-- Remember: table owners bypass RLS unless FORCE ROW LEVEL SECURITY is set.
-- When ENABLE_POSTGRES_RLS=true in .env, app.db.session.apply_postgres_rls_context()
-- executes: SELECT set_config('app.current_organization_id', :org_id, true);

DO $$
DECLARE
    tbl TEXT;
    tenant_tables TEXT[] := ARRAY[
        'organization_members',
        'teams',
        'team_members',
        'invitations',
        'api_keys',
        'audit_logs',
        'knowledge_bases',
        'knowledge_base_access',
        'documents',
        'document_versions',
        'document_chunks',
        'ingestion_jobs',
        'chat_sessions',
        'chat_messages',
        'message_citations',
        'feedback',
        'subscriptions',
        'usage_records',
        'provider_configs'
    ];
BEGIN
    FOREACH tbl IN ARRAY tenant_tables LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY;', tbl);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY;', tbl);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation_policy ON %I;', tbl);
        EXECUTE format(
            'CREATE POLICY tenant_isolation_policy ON %I
             USING (organization_id = NULLIF(current_setting(''app.current_organization_id'', true), '''')::uuid)
             WITH CHECK (organization_id = NULLIF(current_setting(''app.current_organization_id'', true), '''')::uuid);',
            tbl
        );
    END LOOP;
END $$;
