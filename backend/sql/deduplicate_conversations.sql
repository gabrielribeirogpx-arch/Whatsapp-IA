DELETE FROM conversations a
USING conversations b
WHERE a.id < b.id
  AND a.phone_number = b.phone_number
  AND a.tenant_id = b.tenant_id;
