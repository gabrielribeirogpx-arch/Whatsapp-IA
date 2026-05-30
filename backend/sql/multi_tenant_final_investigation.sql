\pset pager off
\pset null '(null)'
\echo '== multi_tenant_final_investigation =='
\echo 'Target conversation_id: b51fef94-1be8-456e-93a9-69ca4a8ea18c'
\echo 'Target flow_id:         50f7b54f-2ccd-4203-bb82-f946f4a9f078'
\echo 'Target lead_id:         8de6a070-1290-494f-b274-cb6de8660e69'
\echo 'Expected tenant_id:     b0c1a7d5-587b-476f-89d1-5596c02dad5d'
\echo ''

\echo '1) Tenant ownership for the target records'
WITH params AS (
    SELECT
        'b51fef94-1be8-456e-93a9-69ca4a8ea18c'::uuid AS conversation_id,
        '50f7b54f-2ccd-4203-bb82-f946f4a9f078'::uuid AS flow_id,
        '8de6a070-1290-494f-b274-cb6de8660e69'::uuid AS lead_id,
        'b0c1a7d5-587b-476f-89d1-5596c02dad5d'::uuid AS expected_tenant_id
), target_records AS (
    SELECT
        'conversation' AS record_type,
        c.id AS record_id,
        c.tenant_id,
        c.phone_number AS phone,
        c.contact_id,
        c.current_flow AS related_flow_id,
        c.updated_at
    FROM conversations c
    JOIN params p ON p.conversation_id = c.id

    UNION ALL

    SELECT
        'flow' AS record_type,
        f.id AS record_id,
        f.tenant_id,
        NULL::text AS phone,
        NULL::uuid AS contact_id,
        f.id AS related_flow_id,
        f.updated_at
    FROM flows f
    JOIN params p ON p.flow_id = f.id

    UNION ALL

    SELECT
        'lead' AS record_type,
        l.id AS record_id,
        l.tenant_id,
        l.phone,
        l.contact_id,
        l.conversation_id AS related_flow_id,
        l.updated_at
    FROM leads l
    JOIN params p ON p.lead_id = l.id
)
SELECT
    tr.record_type,
    tr.record_id,
    tr.tenant_id,
    t.name AS tenant_name,
    t.slug AS tenant_slug,
    (tr.tenant_id = p.expected_tenant_id) AS is_expected_tenant,
    tr.phone,
    tr.contact_id,
    tr.related_flow_id,
    tr.updated_at
FROM target_records tr
CROSS JOIN params p
LEFT JOIN tenants t ON t.id = tr.tenant_id
ORDER BY tr.record_type;

\echo ''
\echo '2) Definitive tenant classification from target record ownership'
WITH params AS (
    SELECT 'b0c1a7d5-587b-476f-89d1-5596c02dad5d'::uuid AS expected_tenant_id
), target_tenants AS (
    SELECT tenant_id, 'conversation' AS source FROM conversations WHERE id = 'b51fef94-1be8-456e-93a9-69ca4a8ea18c'::uuid
    UNION ALL
    SELECT tenant_id, 'flow' AS source FROM flows WHERE id = '50f7b54f-2ccd-4203-bb82-f946f4a9f078'::uuid
    UNION ALL
    SELECT tenant_id, 'lead' AS source FROM leads WHERE id = '8de6a070-1290-494f-b274-cb6de8660e69'::uuid
), scored AS (
    SELECT
        tt.tenant_id,
        count(*) AS matching_target_records,
        array_agg(tt.source ORDER BY tt.source) AS evidence_sources
    FROM target_tenants tt
    GROUP BY tt.tenant_id
), classified AS (
    SELECT
        s.*,
        (s.tenant_id = p.expected_tenant_id) AS is_expected_tenant,
        dense_rank() OVER (ORDER BY s.matching_target_records DESC, (s.tenant_id = p.expected_tenant_id) DESC, s.tenant_id) AS tenant_rank
    FROM scored s
    CROSS JOIN params p
)
SELECT
    CASE
        WHEN tenant_rank = 1 THEN 'tenant_correto'
        ELSE 'tenant_incorreto'
    END AS classification,
    c.tenant_id,
    t.name AS tenant_name,
    t.slug AS tenant_slug,
    c.is_expected_tenant,
    c.matching_target_records,
    c.evidence_sources
FROM classified c
LEFT JOIN tenants t ON t.id = c.tenant_id
ORDER BY c.tenant_rank, c.tenant_id;

\echo ''
\echo '3) Meta providers for target tenants (provider correto/incorreto candidates)'
WITH params AS (
    SELECT 'b0c1a7d5-587b-476f-89d1-5596c02dad5d'::uuid AS expected_tenant_id
), target_tenants AS (
    SELECT tenant_id FROM conversations WHERE id = 'b51fef94-1be8-456e-93a9-69ca4a8ea18c'::uuid
    UNION
    SELECT tenant_id FROM flows WHERE id = '50f7b54f-2ccd-4203-bb82-f946f4a9f078'::uuid
    UNION
    SELECT tenant_id FROM leads WHERE id = '8de6a070-1290-494f-b274-cb6de8660e69'::uuid
    UNION
    SELECT expected_tenant_id FROM params
), tenant_scores AS (
    SELECT
        tenant_id,
        count(*) AS hits
    FROM (
        SELECT tenant_id FROM conversations WHERE id = 'b51fef94-1be8-456e-93a9-69ca4a8ea18c'::uuid
        UNION ALL
        SELECT tenant_id FROM flows WHERE id = '50f7b54f-2ccd-4203-bb82-f946f4a9f078'::uuid
        UNION ALL
        SELECT tenant_id FROM leads WHERE id = '8de6a070-1290-494f-b274-cb6de8660e69'::uuid
    ) s
    GROUP BY tenant_id
), ranked_tenants AS (
    SELECT
        tt.tenant_id,
        COALESCE(ts.hits, 0) AS hits,
        dense_rank() OVER (ORDER BY COALESCE(ts.hits, 0) DESC, (tt.tenant_id = p.expected_tenant_id) DESC, tt.tenant_id) AS tenant_rank
    FROM target_tenants tt
    CROSS JOIN params p
    LEFT JOIN tenant_scores ts ON ts.tenant_id = tt.tenant_id
), provider_rows AS (
    SELECT
        CASE WHEN rt.tenant_rank = 1 THEN 'provider_tenant_correto' ELSE 'provider_tenant_incorreto' END AS classification,
        p.id AS provider_id,
        p.tenant_id,
        t.name AS tenant_name,
        t.slug AS tenant_slug,
        p.provider_type,
        p.display_name,
        p.is_active,
        p.status,
        p.phone_number_id,
        p.waba_id,
        p.business_id,
        (p.access_token_encrypted IS NOT NULL AND length(trim(p.access_token_encrypted)) > 0) AS has_access_token,
        p.created_at,
        p.updated_at,
        rt.hits AS target_record_hits
    FROM tenant_whatsapp_providers p
    JOIN ranked_tenants rt ON rt.tenant_id = p.tenant_id
    LEFT JOIN tenants t ON t.id = p.tenant_id
    WHERE p.provider_type = 'meta_cloud'
)
SELECT *
FROM provider_rows
ORDER BY classification, is_active DESC, updated_at DESC NULLS LAST;

\echo ''
\echo '4) Same phone_number_id in multiple tenants (all duplicates)'
WITH duplicate_phone_numbers AS (
    SELECT phone_number_id
    FROM tenant_whatsapp_providers
    WHERE provider_type = 'meta_cloud'
      AND phone_number_id IS NOT NULL
      AND length(trim(phone_number_id)) > 0
    GROUP BY phone_number_id
    HAVING count(DISTINCT tenant_id) > 1
)
SELECT
    p.phone_number_id,
    p.id AS provider_id,
    p.tenant_id,
    t.name AS tenant_name,
    t.slug AS tenant_slug,
    p.display_name,
    p.is_active,
    p.status,
    p.waba_id,
    p.business_id,
    (p.access_token_encrypted IS NOT NULL AND length(trim(p.access_token_encrypted)) > 0) AS has_access_token,
    p.updated_at
FROM tenant_whatsapp_providers p
JOIN duplicate_phone_numbers d ON d.phone_number_id = p.phone_number_id
LEFT JOIN tenants t ON t.id = p.tenant_id
WHERE p.provider_type = 'meta_cloud'
ORDER BY p.phone_number_id, p.is_active DESC, p.updated_at DESC NULLS LAST, p.tenant_id;

\echo ''
\echo '5) Duplicate phone_number_id restricted to providers attached to target tenants'
WITH target_tenants AS (
    SELECT tenant_id FROM conversations WHERE id = 'b51fef94-1be8-456e-93a9-69ca4a8ea18c'::uuid
    UNION
    SELECT tenant_id FROM flows WHERE id = '50f7b54f-2ccd-4203-bb82-f946f4a9f078'::uuid
    UNION
    SELECT tenant_id FROM leads WHERE id = '8de6a070-1290-494f-b274-cb6de8660e69'::uuid
    UNION
    SELECT 'b0c1a7d5-587b-476f-89d1-5596c02dad5d'::uuid
), target_provider_phones AS (
    SELECT DISTINCT phone_number_id
    FROM tenant_whatsapp_providers p
    JOIN target_tenants tt ON tt.tenant_id = p.tenant_id
    WHERE p.provider_type = 'meta_cloud'
      AND p.phone_number_id IS NOT NULL
      AND length(trim(p.phone_number_id)) > 0
)
SELECT
    p.phone_number_id,
    p.id AS provider_id,
    p.tenant_id,
    t.name AS tenant_name,
    t.slug AS tenant_slug,
    p.display_name,
    p.is_active,
    p.status,
    p.waba_id,
    p.business_id,
    (p.access_token_encrypted IS NOT NULL AND length(trim(p.access_token_encrypted)) > 0) AS has_access_token,
    p.updated_at
FROM tenant_whatsapp_providers p
JOIN target_provider_phones tp ON tp.phone_number_id = p.phone_number_id
LEFT JOIN tenants t ON t.id = p.tenant_id
WHERE p.provider_type = 'meta_cloud'
ORDER BY p.phone_number_id, p.is_active DESC, p.updated_at DESC NULLS LAST, p.tenant_id;

\echo ''
\echo '6) Safe correction plan preview when expected tenant is the correct tenant'
WITH params AS (
    SELECT 'b0c1a7d5-587b-476f-89d1-5596c02dad5d'::uuid AS expected_tenant_id
), target_tenants AS (
    SELECT tenant_id, 'conversation' AS source FROM conversations WHERE id = 'b51fef94-1be8-456e-93a9-69ca4a8ea18c'::uuid
    UNION ALL
    SELECT tenant_id, 'flow' AS source FROM flows WHERE id = '50f7b54f-2ccd-4203-bb82-f946f4a9f078'::uuid
    UNION ALL
    SELECT tenant_id, 'lead' AS source FROM leads WHERE id = '8de6a070-1290-494f-b274-cb6de8660e69'::uuid
), expected_is_correct AS (
    SELECT bool_and(tenant_id = p.expected_tenant_id) AS value
    FROM target_tenants tt
    CROSS JOIN params p
), expected_provider AS (
    SELECT p.*
    FROM tenant_whatsapp_providers p
    CROSS JOIN params prm
    WHERE p.tenant_id = prm.expected_tenant_id
      AND p.provider_type = 'meta_cloud'
    ORDER BY p.is_active DESC, p.updated_at DESC NULLS LAST
    LIMIT 1
), movable_provider AS (
    SELECT p.*
    FROM tenant_whatsapp_providers p
    CROSS JOIN params prm
    WHERE p.provider_type = 'meta_cloud'
      AND p.tenant_id <> prm.expected_tenant_id
      AND p.phone_number_id IS NOT NULL
      AND length(trim(p.phone_number_id)) > 0
      AND EXISTS (
          SELECT 1
          FROM tenant_whatsapp_providers ep
          WHERE ep.tenant_id = prm.expected_tenant_id
            AND ep.provider_type = 'meta_cloud'
            AND ep.phone_number_id = p.phone_number_id
      )
    ORDER BY p.is_active DESC, p.updated_at DESC NULLS LAST
    LIMIT 1
)
SELECT
    CASE
        WHEN NOT COALESCE((SELECT value FROM expected_is_correct), false) THEN 'do_not_apply_expected_tenant_not_confirmed'
        WHEN EXISTS (SELECT 1 FROM expected_provider) THEN 'activate_or_update_existing_provider_in_expected_tenant'
        WHEN EXISTS (SELECT 1 FROM movable_provider) THEN 'move_provider_to_expected_tenant_inside_transaction_after_manual_approval'
        ELSE 'recreate_provider_meta_in_expected_tenant_with_known_meta_credentials'
    END AS recommended_action,
    (SELECT id FROM expected_provider) AS expected_tenant_provider_id,
    (SELECT id FROM movable_provider) AS movable_provider_id,
    (SELECT tenant_id FROM movable_provider) AS movable_provider_current_tenant_id,
    'No data-changing statement is executed by this investigation script.' AS safety_note;
