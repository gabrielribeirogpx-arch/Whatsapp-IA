# Mapa de mutações P0 residuais do Audit Log

Revisão focada em settings, IA, MCP e conexões administrativas. A sanitização de
logs operacionais, Runtime V2, flows e frontend ficaram fora deste patch.

| Endpoint | Serviço | Permissão | Ator | Tenant | Evento | Atômico |
|---|---|---|---:|---:|---|---:|
| `PUT /api/settings` | router/SQLAlchemy | `manage_settings` | sim | sim | `tenant_settings_updated` | sim |
| `PUT /api/ai/settings` | router/SQLAlchemy | `manage_settings` | sim | sim | `ai_settings_updated` | sim |
| `DELETE /api/ai/settings/key` | router/SQLAlchemy | `manage_settings` | sim | sim | `ai_credentials_rotated` | sim |
| `POST /api/mcp/servers` | `mcp_service` | `manage_integrations` | sim | sim | `mcp_server_created` | sim |
| `PUT /api/mcp/servers/{id}` | `mcp_service` | `manage_integrations` | sim | sim | `mcp_server_updated` | sim |
| `DELETE /api/mcp/servers/{id}` | `mcp_service` | `manage_integrations` | sim | sim | `mcp_server_disconnected` | sim |
| `PUT /api/mcp/tools/{id}` | router/SQLAlchemy | `manage_integrations` | sim | sim | `mcp_tool_updated` | sim |
| `DELETE /api/integrations/connections/{provider}` | `IntegrationConnectionService` | `manage_integrations` | sim | sim | `integration_disconnected` | sim |

As permissões reutilizam a matriz workspace existente e são concedidas apenas a
owner/admin. Recusas persistem `admin_permission_denied` em best effort: uma
falha de persistência nunca altera o 403. Divergência entre o tenant do token e
o tenant resolvido persiste `cross_tenant_access_denied` no tenant do ator e
mantém a resposta externa sem informação sobre o alvo.

Metadata de IA contém apenas provider/model, flags e parâmetros numéricos; não
contém prompt nem valor de chave. Metadata MCP contém nomes de campos de config,
nunca os valores, e ainda atravessa a redação recursiva do audit service.

## Limites da validação local

Não há servidor/binários PostgreSQL nem `DATABASE_URL` PostgreSQL disponíveis no
ambiente desta execução. Portanto a prova em PostgreSQL real (insert, triggers
de UPDATE/DELETE, FK RESTRICT e Alembic head) permanece uma validação externa
obrigatória e não é substituída pelos testes SQLite.
