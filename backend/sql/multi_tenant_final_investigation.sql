-- Investigação final de multi-tenant / WhatsApp runtime.
--
-- Execute em produção com psql usando o DATABASE_URL correto:
--   psql "$DATABASE_URL" -f backend/sql/multi_tenant_final_investigation.sql
--
-- Observação de schema:
-- - O model SQLAlchemy usa a tabela tenant_whatsapp_providers, não whatsapp_providers.
-- - A seção "2b" abaixo também tenta consultar whatsapp_providers apenas se uma view/tabela
--   legada com esse nome existir no banco.

\pset pager off
\set ON_ERROR_STOP on

\echo '0. Parâmetros investigados'
WITH params AS (
    SELECT
        '5516994361408'::text AS target_phone,
        '50f7b54f-2ccd-4203-bb82-f946f4a9f078'::uuid AS target_flow_id,
        '876969468828520'::text AS target_phone_number_id,
        'b0c1a7d5-587b-476f-89d1-5596c02dad5d'::uuid AS runtime_tenant_id,
        'd89f177f-74dd-40e8-9496-7facaea76aaf'::uuid AS manual_config_tenant_id
)
SELECT * FROM params;

\echo '1. TODOS os tenants existentes'
SELECT
    id,
    name,
    slug,
    phone_number_id,
    webhook_url,
    webhook_status,
    plan,
    is_blocked
FROM tenants
ORDER BY id;

\echo '2. Todos os providers em tenant_whatsapp_providers'
SELECT
    id,
    tenant_id,
    COALESCE(display_name, provider_type) AS provider_name,
    provider_type,
    is_active,
    status,
    phone_number_id,
    waba_id,
    business_id,
    updated_at,
    created_at
FROM tenant_whatsapp_providers
ORDER BY tenant_id, is_active DESC, updated_at DESC NULLS LAST, created_at DESC NULLS LAST;

\echo '2b. Compatibilidade: whatsapp_providers, se existir como tabela/view'
DO $$
BEGIN
    IF to_regclass('public.whatsapp_providers') IS NOT NULL THEN
        RAISE NOTICE 'public.whatsapp_providers existe; execute manualmente: SELECT id, tenant_id, provider_name, is_active, status, phone_number_id, waba_id FROM whatsapp_providers;';
    ELSE
        RAISE NOTICE 'public.whatsapp_providers não existe; use public.tenant_whatsapp_providers.';
    END IF;
END $$;

\echo '3. Conversas do número 5516994361408 com tenant_id'
WITH params AS (SELECT '5516994361408'::text AS target_phone)
SELECT
    c.id,
    c.tenant_id,
    t.slug AS tenant_slug,
    c.phone_number,
    c.name,
    c.mode,
    c.current_flow AS current_flow_id,
    c.current_node_id,
    c.created_at,
    c.updated_at
FROM conversations c
LEFT JOIN tenants t ON t.id = c.tenant_id
JOIN params p ON c.phone_number = p.target_phone
ORDER BY c.updated_at DESC NULLS LAST, c.created_at DESC NULLS LAST;

\echo '4. Flow 50f7b54f-2ccd-4203-bb82-f946f4a9f078 com tenant_id'
WITH params AS (SELECT '50f7b54f-2ccd-4203-bb82-f946f4a9f078'::uuid AS target_flow_id)
SELECT
    f.id,
    f.tenant_id,
    t.slug AS tenant_slug,
    f.name,
    f.status,
    f.is_active,
    f.is_deleted,
    f.trigger_type,
    f.trigger_value,
    f.priority,
    f.current_version_id,
    f.published_version_id,
    f.created_at,
    f.updated_at,
    f.deleted_at
FROM flows f
LEFT JOIN tenants t ON t.id = f.tenant_id
JOIN params p ON f.id = p.target_flow_id;

\echo '5a. Webhooks/mensagens inbound recebidos do número via messages + conversations'
WITH params AS (SELECT '5516994361408'::text AS target_phone)
SELECT
    m.id AS message_id,
    m.tenant_id,
    t.slug AS tenant_slug,
    m.conversation_id,
    c.phone_number,
    m.from_me,
    m.created_at,
    LEFT(m.text, 300) AS text_preview
FROM messages m
JOIN conversations c ON c.id = m.conversation_id
LEFT JOIN tenants t ON t.id = m.tenant_id
JOIN params p ON c.phone_number = p.target_phone
WHERE m.from_me = false
ORDER BY m.created_at DESC;

\echo '5b. Idempotência de webhooks processados por tenant (sem telefone bruto no schema)'
SELECT
    tenant_id,
    COUNT(*) AS processed_message_count,
    MIN(created_at) AS first_processed_at,
    MAX(created_at) AS last_processed_at
FROM processed_messages
GROUP BY tenant_id
ORDER BY last_processed_at DESC NULLS LAST;

\echo '6. Tenant associado ao phone_number_id=876969468828520'
WITH params AS (SELECT '876969468828520'::text AS target_phone_number_id)
SELECT
    'tenants.phone_number_id' AS source,
    t.id AS tenant_id,
    t.slug AS tenant_slug,
    t.name AS tenant_name,
    NULL::uuid AS provider_id,
    NULL::text AS provider_name,
    t.phone_number_id,
    NULL::boolean AS is_active,
    NULL::text AS status,
    NULL::timestamp AS updated_at
FROM tenants t
JOIN params p ON t.phone_number_id = p.target_phone_number_id
UNION ALL
SELECT
    'tenant_whatsapp_providers.phone_number_id' AS source,
    pvd.tenant_id,
    t.slug AS tenant_slug,
    t.name AS tenant_name,
    pvd.id AS provider_id,
    COALESCE(pvd.display_name, pvd.provider_type) AS provider_name,
    pvd.phone_number_id,
    pvd.is_active,
    pvd.status,
    pvd.updated_at
FROM tenant_whatsapp_providers pvd
LEFT JOIN tenants t ON t.id = pvd.tenant_id
JOIN params p ON pvd.phone_number_id = p.target_phone_number_id
ORDER BY source, is_active DESC NULLS LAST, updated_at DESC NULLS LAST;

\echo '7. Verificar se o mesmo phone_number_id existe em mais de um tenant'
SELECT
    phone_number_id,
    COUNT(DISTINCT tenant_id) AS tenant_count,
    ARRAY_AGG(DISTINCT tenant_id ORDER BY tenant_id) AS tenant_ids,
    ARRAY_AGG(id ORDER BY updated_at DESC NULLS LAST) AS provider_ids
FROM tenant_whatsapp_providers
WHERE phone_number_id IS NOT NULL AND BTRIM(phone_number_id) <> ''
GROUP BY phone_number_id
HAVING COUNT(DISTINCT tenant_id) > 1
ORDER BY tenant_count DESC, phone_number_id;

\echo '8. Diagnóstico objetivo: runtime tenant vs tenant de configuração manual'
WITH params AS (
    SELECT
        '5516994361408'::text AS target_phone,
        '50f7b54f-2ccd-4203-bb82-f946f4a9f078'::uuid AS target_flow_id,
        '876969468828520'::text AS target_phone_number_id,
        'b0c1a7d5-587b-476f-89d1-5596c02dad5d'::uuid AS runtime_tenant_id,
        'd89f177f-74dd-40e8-9496-7facaea76aaf'::uuid AS manual_config_tenant_id
), runtime AS (
    SELECT p.runtime_tenant_id AS tenant_id, t.slug, t.name, t.phone_number_id
    FROM params p
    LEFT JOIN tenants t ON t.id = p.runtime_tenant_id
), manual AS (
    SELECT p.manual_config_tenant_id AS tenant_id, t.slug, t.name, t.phone_number_id
    FROM params p
    LEFT JOIN tenants t ON t.id = p.manual_config_tenant_id
), runtime_provider AS (
    SELECT pvd.*
    FROM params p
    JOIN tenant_whatsapp_providers pvd ON pvd.tenant_id = p.runtime_tenant_id
    WHERE pvd.provider_type = 'meta_cloud' AND pvd.is_active = true
    ORDER BY pvd.updated_at DESC NULLS LAST
    LIMIT 1
), manual_provider AS (
    SELECT pvd.*
    FROM params p
    JOIN tenant_whatsapp_providers pvd ON pvd.tenant_id = p.manual_config_tenant_id
    WHERE pvd.phone_number_id = p.target_phone_number_id OR pvd.is_active = true
    ORDER BY (pvd.phone_number_id = p.target_phone_number_id) DESC, pvd.is_active DESC, pvd.updated_at DESC NULLS LAST
    LIMIT 1
), conversation_tenants AS (
    SELECT ARRAY_AGG(DISTINCT c.tenant_id ORDER BY c.tenant_id) AS tenant_ids
    FROM conversations c
    JOIN params p ON c.phone_number = p.target_phone
), flow_tenant AS (
    SELECT f.tenant_id
    FROM flows f
    JOIN params p ON f.id = p.target_flow_id
)
SELECT
    'tenant_correto_runtime' AS item,
    r.tenant_id,
    r.slug,
    r.name,
    r.phone_number_id,
    NULL::uuid AS provider_id,
    NULL::text AS provider_name,
    NULL::boolean AS provider_is_active,
    NULL::text AS provider_status,
    NULL::text AS provider_phone_number_id,
    NULL::text AS evidence
FROM runtime r
UNION ALL
SELECT
    'tenant_incorreto_configuracao_manual' AS item,
    m.tenant_id,
    m.slug,
    m.name,
    m.phone_number_id,
    NULL::uuid,
    NULL::text,
    NULL::boolean,
    NULL::text,
    NULL::text,
    NULL::text
FROM manual m
UNION ALL
SELECT
    'provider_usado_pelo_runtime' AS item,
    rp.tenant_id,
    t.slug,
    t.name,
    t.phone_number_id,
    rp.id,
    COALESCE(rp.display_name, rp.provider_type),
    rp.is_active,
    rp.status,
    rp.phone_number_id,
    'runtime seleciona provider meta_cloud ativo do tenant da conversa' AS evidence
FROM runtime_provider rp
LEFT JOIN tenants t ON t.id = rp.tenant_id
UNION ALL
SELECT
    'provider_configurado_manualmente' AS item,
    mp.tenant_id,
    t.slug,
    t.name,
    t.phone_number_id,
    mp.id,
    COALESCE(mp.display_name, mp.provider_type),
    mp.is_active,
    mp.status,
    mp.phone_number_id,
    'provider encontrado no tenant onde a configuração manual foi feita' AS evidence
FROM manual_provider mp
LEFT JOIN tenants t ON t.id = mp.tenant_id
UNION ALL
SELECT
    'evidencia_conversas_numero' AS item,
    NULL::uuid,
    NULL::text,
    NULL::text,
    NULL::text,
    NULL::uuid,
    NULL::text,
    NULL::boolean,
    NULL::text,
    NULL::text,
    COALESCE(ct.tenant_ids::text, '{}') AS evidence
FROM conversation_tenants ct
UNION ALL
SELECT
    'evidencia_flow_tenant' AS item,
    ft.tenant_id,
    t.slug,
    t.name,
    t.phone_number_id,
    NULL::uuid,
    NULL::text,
    NULL::boolean,
    NULL::text,
    NULL::text,
    'tenant_id do flow informado' AS evidence
FROM flow_tenant ft
LEFT JOIN tenants t ON t.id = ft.tenant_id;
