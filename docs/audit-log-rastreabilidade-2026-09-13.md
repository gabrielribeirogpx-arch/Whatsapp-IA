# Auditoria de rastreabilidade, Audit Log e eventos administrativos

**Data da revisão:** 2026-09-13  
**Escopo:** análise estática do backend, modelos e migrations do repositório. Nenhum código, schema, migration, frontend, Runtime V2 ou infraestrutura foi alterado.  
**Veredito:** **AUDIT LOG PARCIAL**.

O mecanismo persistente existe, tem isolamento de leitura por tenant e cobre bem o RBAC e parte dos flows. Porém, publicação por endpoints canônicos, tenant/settings, IA, OAuth/Google, MCP, templates e várias exclusões não deixam trilha administrativa. Há ainda operações de WhatsApp confirmadas antes da escrita do audit, ausência de política de retenção/imutabilidade no banco e application/debug logs com conteúdo de mensagens, flows e webhooks.

## Método e limites

Foram inventariados modelos, migrations, routers, services, workers, scripts e testes com buscas por termos de auditoria/log/evento, todas as chamadas de `write_audit_log`, rotas mutáveis e operações de exclusão/commit. A conclusão descreve o código versionado; não houve inspeção de dados de produção nem de configuração externa de coleta/retenção de stdout.

## A. Arquitetura atual do Audit Log

### Mecanismo principal

| Camada | Local | Diagnóstico |
|---|---|---|
| Modelo/tabela | `backend/app/models/audit_log.py` / `audit_logs` | Registro SQLAlchemy persistente, com índices por tenant/data, tenant/ação e tenant/usuário. |
| Migration | `backend/alembic/versions/20260529_enterprise_security_audit_sessions.py` | Cria `audit_logs` e `user_sessions`; tenant é anulável e tem `ON DELETE CASCADE`; usuário é anulável e tem `ON DELETE SET NULL`. |
| Service/helper | `backend/app/services/audit_service.py` | `write_audit_log` normaliza metadata, adiciona a row à sessão e só faz commit quando `commit=True`; `serialize_audit_log` produz a resposta. Não há repository dedicado. |
| Schema | `backend/app/schemas/account.py` (`AuditLogOut`) | Espelha todos os campos persistidos e acrescenta nome/e-mail resolvidos do ator. |
| Router de consulta | `backend/app/routers/account.py`, `GET /security/audit` | Lista até 200 eventos do tenant autenticado e permite filtros exatos por ator, ação e período. |
| Autorização | `backend/app/security/workspace_rbac.py` | `VIEW_AUDIT_LOG` é concedida somente a `owner` e `admin`. |
| Middleware | nenhum específico | IP é obtido por `get_client_ip(request)` quando a chamada fornece `Request`; não existe middleware que audite automaticamente mutações ou recusas. |
| Outros event stores | `FlowV2Event`, `ExecutionTrace`, `FlowEvent`, `FlowAnalyticsEvent`, `ConversationLog`, logs stdout | São telemetria/runtime/application logs, não o Audit Log administrativo central. |

### Schema atual e suficiência

| Campo desejado | Estado | Campo atual / observação |
|---|---|---|
| `id` | presente | UUID. |
| `tenant_id/workspace_id` | presente, mas parcial | `tenant_id` é anulável; `workspace_id` aparece duplicado apenas no metadata de RBAC. Falhas de login de e-mail inexistente ficam sem tenant. |
| `actor_user_id` | presente, semântica parcial | `user_id` é o ator na maioria das rotas. Em login/reset ele representa o próprio alvo; jobs/webhooks deixam nulo. RBAC também duplica `actor_user_id` no JSON. |
| `target_user_id` | parcial | Não há coluna: RBAC usa `entity_id` e metadata. |
| `action` | presente | String livre de 80 caracteres; há mistura de maiúsculas, minúsculas e nomenclatura pontuada. |
| `resource_type` | presente equivalente | `entity_type`. |
| `resource_id` | presente equivalente | `entity_id`, string anulável. |
| `old_value/new_value` | parcial | Só em metadata de algumas ações (role/status/mode); não há campos próprios nem snapshots uniformes. |
| `metadata` | presente | `metadata_json` JSONB; aceita dicts/Pydantic/dataclasses recursivos, sem allowlist/redação de secrets. |
| `ip_address` | presente, preenchimento parcial | Somente quando `request` é repassado. RBAC de usuários e vários services não o repassam. |
| `user_agent` | presente, preenchimento parcial | Mesma limitação do IP. |
| `created_at` | presente | `datetime.utcnow`; sem timezone explícito no modelo. |

Não há request/correlation ID, resultado (`success/failure`), origem, hash/assinatura ou versão do evento. `user_email`/`user_name` são calculados na leitura: ao remover o ator ou alterar seu perfil, a apresentação histórica pode perder/mudar a identidade, embora IDs colocados no metadata de RBAC sobrevivam.

## B. Eventos existentes

Eventos administrativos/segurança encontrados no Audit Log central:

* autenticação e conta: `USER_CREATED`, `LOGIN_SUCCESS`, `LOGIN_FAILED`, `PASSWORD_RESET_REQUESTED`, `PASSWORD_RESET_COMPLETED`, `PASSWORD_CHANGED`, `SESSION_REVOKED`;
* RBAC: `user_invited`, `user_role_changed`, `user_promoted`, `user_demoted`, `user_disabled`, `user_enabled`, `user_removed`;
* flows: `FLOW_CREATED`, `FLOW_UPDATED`, `FLOW_DELETED`, `FLOW_PUBLISHED`, `FLOW_UNPUBLISHED`;
* WhatsApp: `WHATSAPP_PROVIDER_UPDATED`, `API_KEY_UPDATED`;
* conversas/CRM/tasks: `CONVERSATION_STARTED`, `CONVERSATION_MODE_CHANGED`, `TEST_CONVERSATION_RESET`, `LEAD_CREATED`, `LEAD_UPDATED`, `LEAD_DELETED`, `TASK_CREATED`, `TASK_UPDATED`, `TASK_COMPLETED`, `TEAM_NOTIFICATION_CREATED` (alguns nomes vêm de constantes/branches);
* billing/observabilidade: `TRIAL_STARTED`, `TRIAL_EXTENDED`, `TRIAL_EXPIRED`, `DOWNGRADE_INCOMPATIBILITY_DETECTED`, `BILLING_FEATURE_BLOCKED`, `BILLING_LIMIT_BLOCKED`, `BILLING_CURRENT_VIEWED`, `TRIAL_VIEWED`, `STRIPE_CUSTOMER_CREATED`, `CHECKOUT_SESSION_CREATED`, `CHECKOUT_SESSION_COMPLETED`, `CUSTOMER_PORTAL_OPENED`, `BILLING_WEBHOOK_PROCESSED`, `SUBSCRIPTION_CANCELED`, `SUBSCRIPTION_ACTIVATED`, `SUBSCRIPTION_UPDATED`, `PAYMENT_FAILED`, `PAYMENT_SUCCEEDED`, `GROWTH_OVERVIEW_VIEWED`, `observability.trace.view`, `OBSERVABILITY_EXPORT_SUCCESS`/`OBSERVABILITY_EXPORT_FAILED` (sufixo dinâmico);
* marketplace: ações dinâmicas gravadas diretamente pelo service, associadas a `marketplace_installation`.

### Inconsistências de taxonomia

Há caixa e formato divergentes (`user_invited`, `FLOW_CREATED`, `observability.trace.view`), e criação/ativação/exclusão de provider são todas chamadas `WHATSAPP_PROVIDER_UPDATED` com a operação apenas no metadata. Alterar credencial usa `API_KEY_UPDATED`, sem indicar no nome que é WhatsApp. Atualização de role produz dois eventos (`user_role_changed` e promoted/demoted), enquanto update de nome pelo mesmo endpoint não produz evento. `FLOW_PUBLISHED` pode significar ativação, mas os endpoints canônicos `publish`/`republish` não o registram.

## C. Cobertura atual

| Área | Ação | Auditada? | Evento / ressalva |
|---|---|---:|---|
| Usuários | cadastro do owner/tenant | sim, parcial | `USER_CREATED`; não há `TENANT_CREATED`. |
| Usuários | convite | sim | `user_invited`, mesma transação; ator/target/role/tenant no metadata. |
| Usuários | role/promoção/downgrade | sim | `user_role_changed` + `user_promoted`/`user_demoted`, mesma transação. |
| Usuários | ativar/desativar | sim | `user_enabled`/`user_disabled`; endpoint dedicado de desativação omite old/new status. |
| Usuários | remover | sim | `user_removed`, mesma transação e target preservado no metadata. Hard delete. |
| Usuários | editar nome por admin | **não** | PATCH altera nome sem evento se role/status não mudarem. |
| Segurança | login válido/inválido/inativo | sim | `LOGIN_SUCCESS`/`LOGIN_FAILED`, IP/UA presentes. Falha desconhecida não tem tenant. |
| Segurança | senha/reset | sim | solicitado/concluído/alterado; troca autenticada não recebe `request`, logo sem IP/UA. |
| Segurança | logout | parcial | não há logout; revogação de uma/todas as outras sessões gera `SESSION_REVOKED`. |
| Segurança | access denied/cross-tenant | **não** | somente HTTP errors/application behavior, sem security event persistente. |
| Tenant | criar | parcial | inferível por `USER_CREATED`; nenhuma ação de tenant. |
| Tenant | nome/language/profile/webhook/WhatsApp legado | **não** | `/settings`, `/account/preferences` só têm application logs. |
| Tenant | bloquear/desativar/excluir/trocar owner | **não/parcial** | não foi encontrada API CRUD de tenant; troca de owner via RBAC aparece como mudança de role, sem evento específico. Cascade apagaria audit ao excluir tenant. |
| Flows | criar/salvar/editar/renomear | sim na maioria | `FLOW_CREATED`/`FLOW_UPDATED`; versão registrada no save canônico, mas nem sempre em rotas legadas/rename. |
| Flows | apagar | sim na rota normal | `FLOW_DELETED` com modo soft/hard; resets/hard reset administrativos alternativos não têm audit central. |
| Flows | ativar/desativar | sim | `FLOW_PUBLISHED`/`FLOW_UNPUBLISHED`, versão publicada na ativação. |
| Flows | publicar/republicar endpoint canônico | **não** | `POST /flows/{id}/publish` e `/republish` não recebem ator nem chamam audit. |
| Flows | duplicar | **não** | endpoint existe, sem `FLOW_DUPLICATED`. |
| Flows | restore/version ativa | **não** | endpoints restore sem audit; save registra nova versão, mas não old/new snapshot. |
| Flows | importar/exportar | não identificado | sem eventos administrativos equivalentes; export de observabilidade não é export de flow. |
| AI Agents | CRUD/config/prompt/model/ativação | parcial via flow | agent/AI-system está embutido no grafo e pode cair em `FLOW_UPDATED`; não há evento específico nem diff de prompt/model/config. |
| AI settings | provider/model/key/enable/delete key | **não** | PUT, teste e DELETE da key sem audit. |
| Memória IA | criar/editar/excluir fatos manuais | **não** | rotas persistentes sem ator/audit; contém dados pessoais/conteúdo, portanto requer política cuidadosa. |
| Google Calendar/Gmail/Drive/Sheets | conectar/callback/desconectar/revogação | **não** | apenas application logs; callback tem tenant mas não ator persistido. |
| Suitable/Meta | conectar/desconectar/configurar | **não** | sem audit central. |
| MCP | criar/editar/excluir/discover server; habilitar tool; testar | **não** | services fazem commit internamente; nenhum ator/audit. |
| WhatsApp providers | criar/editar/ativar/apagar/rotacionar key | sim, com falha transacional | operação é commitada no service antes do audit; evento genérico para create/delete/activate. Test/diagnóstico não auditado. |
| Templates WhatsApp | criar/editar/apagar/submeter/sync/test-send | **não** | só prints/application logs. |
| Agenda | appointment policy | **não** | PUT sem audit. |
| Webhooks/config operacional | alterar | **não** | settings e conexões sem audit. Recebimento é application/runtime log. |
| Conversas | início/mudança de modo/reset teste | sim/parcial | eventos existem; não há endpoint DELETE de conversation encontrado. Atribuições/takeover não usam audit central. |
| Leads | criar/atualizar/excluir | sim, parcial | automação e exclusão centralizadas auditam; stage/pipeline CRUD não é uniformemente auditado. |
| Produtos/bot rules/knowledge | CRUD e exclusão | **não** | mutações importantes sem audit. |

### Runtime V2: telemetria, não audit administrativo

`flow_v2_events` é um stream persistente descrito como append-only e liga tenant, sessão, versão, node, índice, payload e data. Ele registra `session.started`, input, entrada/execução/conclusão de node, escolha/transição, delay, condição, output, waiting, complete e failure. `flow_v2_sessions` liga ainda contact/conversation e estado atual. `ExecutionTrace` guarda trace/execution/tenant/conversation/contact/flow/event/metadata. Portanto início, fim, falha, node, transição e correlação são rastreáveis operacionalmente; MCP tool start/result/error também tem application logs.

Isso **não** é `audit_logs`: inclui texto de entrada/saída e payloads de execução, não ator administrativo, e pode ser apagado em cascata junto da sessão. Para compliance administrativo, têm valor somente publicação/troca de versão, hard-reset/replay/export/consulta privilegiada, mudança de runtime selector e alterações de tools/credenciais. Não se recomenda copiar conteúdo de conversa, prompts renderizados ou outputs para o Audit Log.

## D. Ações sensíveis sem auditoria e matriz de risco

| Área | Ação | Existe audit? | Evento atual | Ator | Tenant | Target | Antes/depois | Risco |
|---|---|---:|---|---:|---:|---:|---:|---|
| Segurança | acesso negado/cross-tenant | não | — | não | parcial | não | não | **CRÍTICO** |
| Tenant | alteração settings, token/webhook/nome | não | application log | não | sim | não | campos apenas, sem valores | **CRÍTICO** |
| IA | trocar provider/model/prompt/API key/enable | não | — | não | sim | não | não | **CRÍTICO** |
| Integrações | OAuth conectar/desconectar/refresh/revogar | não | application log | callback não | sim | provider parcial | não | **CRÍTICO** |
| MCP | server/config/credentials/tools | não | — | não | sim | sim na operação | não | **CRÍTICO** |
| WhatsApp | CRUD/credential rotation | sim, não atômico | `WHATSAPP_PROVIDER_UPDATED` / `API_KEY_UPDATED` | sim | sim | sim | somente nomes dos campos/operação | **CRÍTICO** |
| Flows | publish/republish canônico | não | runtime/application log | não | sim | flow/version | não | **ALTO** |
| Flows | restore/duplicate/reset/hard reset | não | application log ou nenhum | parcial/não | sim | parcial | não | **ALTO** |
| Usuários | nome/perfil/preferências | não | — | implícito | sim | próprio/target | não | **MÉDIO** |
| Usuários | RBAC completo | sim | sete eventos | sim | sim | sim | role/status parcial | **BAIXO** |
| Segurança | login/reset/revogação | sim | eventos específicos | sim/parcial | sim/parcial | sim | razão parcial | **BAIXO** |
| Templates | CRUD/submissão/test send | não | application logs | não | sim | sim | não | **ALTO** |
| Agenda/canais/tools | configuração | não | application log ou nenhum | não | sim | parcial | não | **ALTO** |
| Conversation | atribuição/takeover/modo | parcial | só modo é auditado | parcial | sim | sim | modo tem old/new | **MÉDIO** |
| Audit | apagar tenant apaga histórico | não aplicável | FK cascade | — | sim | todos | — | **CRÍTICO** |

Principais bypasses: services de integração/MCP/WhatsApp fazem commits diretos; callbacks OAuth e endpoints baseados apenas no tenant não passam usuário; scripts de limpeza, reset de flows, jobs/webhooks de billing e Runtime executam fora de uma identidade humana. O helper não é obrigatório nem intercepta essas vias.

## E. Possíveis vazamentos de dados

### Achados exatos

| Arquivo/função/linha aproximada | Dado potencialmente exposto | Tipo | Severidade |
|---|---|---|---|
| `backend/app/workers/message_worker.py`, `process_incoming_message`, ~228-230 | payload bruto do webhook e mensagem normalizada; pode conter telefone, nome, texto, IDs e mídia | runtime/debug stdout | **CRÍTICO** |
| `backend/app/routers/webhook.py`, ingestão Meta, ~331-332 | primeiros 800 caracteres do webhook bruto, inclusive conteúdo/PII | application/debug stdout | **CRÍTICO** |
| `backend/app/routers/flows.py`, create/save/update, ~225-226, 2020-2021, 2357-2359, 2553, 2594, 2638-2639 | grafo/payload completo: prompts, mensagens, node configs, URLs e potencialmente configurações embutidas | debug stdout | **ALTO** |
| `backend/app/flow_v2/contracts.py`, `RuntimeInput.__post_init__`, ~54-81 | `message_text` do usuário | runtime stdout | **ALTO** |
| `backend/app/flow_v2/executors/agent_system_executor.py`, execução interna, ~126 e ~219 | até 500 caracteres de resposta de IA e fallback | runtime stdout | **ALTO** |
| `backend/app/routers/whatsapp_templates.py`, `test_send_template`, ~85-95 | destinatário e valores completos das variáveis/componentes do template | application stdout | **ALTO** |
| routers Google, handlers connect/callback, ~195-323 | redirect URIs, scopes, tenant headers/slug/id, provider e mensagens de exception. Não logam `code`/`state` diretamente, mas `str(exc)` de dependências é superfície de vazamento | application stdout | **MÉDIO** |
| `backend/app/routers/ai_settings.py`, `test_ai_settings`, ~88-99 | provider/model e texto de exceção do provider; key não é impressa diretamente, mas a exceção pode incorporar resposta externa | application stdout | **MÉDIO** |
| `backend/app/services/whatsapp_credentials_service.py`, resolução, ~37-49 | origem e comprimento do token (não o valor); informação lateral | application stdout | **BAIXO** |

Não foi encontrada impressão direta óbvia de password, access token, refresh token, API key, Authorization, cookie ou JWT completo nas chamadas pesquisadas. O OAuth callback registra apenas `has_code`/`has_state`, não os valores. Mesmo assim, logar exceções externas e objetos/payloads inteiros mantém risco indireto.

### Metadata do Audit Log

As chamadas atuais em geral constroem dicts pequenos. Não foi achado `user.__dict__`, `request.json()` ou `payload.dict()` passado diretamente ao audit. O provider WhatsApp registra somente os **nomes** dos campos alterados, não as credenciais. O risco arquitetural permanece: `to_json_safe` aceita `model_dump`, dataclasses, listas e dicts sem redaction/denylist; uma chamada futura pode persistir secrets ou PII integralmente. `observability` grava o dict de filtros e billing enforcement grava `decision.as_dict()`, que precisam de contrato/allowlist formal.

## F. Isolamento tenant e acesso

### Leitura central

`GET /security/audit`:

1. resolve o tenant da requisição;
2. autentica o bearer e rejeita token cujo `tenant_id` difira do tenant resolvido;
3. executa `require_same_tenant`;
4. exige `VIEW_AUDIT_LOG`;
5. começa a query com `AuditLog.tenant_id == tenant.id` antes dos filtros fornecidos.

Assim, manipular `user_id`, `action`, datas ou URL não remove o predicado do tenant. **Não foi identificada leitura cross-tenant nesse endpoint.** Owner e admin recebem 200; member e viewer recebem 403. Os testes de RBAC cobrem a matriz.

Há, contudo, dois problemas adjacentes: (a) o dashboard lê uma allowlist de ações do mesmo tenant e não é o endpoint completo; (b) rotas de billing fazem queries globais sobre `AuditLog` para métricas internas, sem filtro de tenant, e devem ser tratadas como endpoint administrativo global e revisadas quanto à autorização, embora não sejam `/security/audit`.

### Recursos da consulta

* limite fixo de 200; **não** há paginação (`offset`, cursor, page) nem contagem;
* filtros por ator (`user_id`), ação exata, data inicial e final;
* não há busca textual, filtro por `entity_type`, `entity_id`/recurso, target, IP ou resultado;
* ordenação decrescente só por `created_at`, sem desempate por `id`;
* resposta inclui e-mail/nome do ator e IP/UA, justificando restringir a owner/admin.

## G. Integridade, transações e falhas

### Append-only

Na API não foram encontrados endpoints UPDATE/DELETE de `AuditLog` nem métodos para fazê-lo. Porém, o banco não impõe append-only: qualquer sessão/SQL com acesso pode atualizar/deletar rows; não há trigger, privilégios separados, hash chain ou assinatura. E `ON DELETE CASCADE` no tenant elimina todos os eventos quando o tenant é apagado. Portanto é **append-only por convenção da API, não por garantia de integridade**.

### Atomicidade

* RBAC, password, flow CRUD/activate e vários eventos de domínio adicionam mudança + audit e dão um único commit: uma exceção do serializer/flush/commit normalmente aborta a operação na transação.
* `write_audit_log(commit=False)` não captura erros. Logo, quando chamado antes do único commit, a operação falha e pode ser revertida pela lifecycle da sessão; alguns handlers fazem rollback explícito e outros dependem do encerramento da sessão.
* **WhatsApp provider é a exceção crítica:** `create_provider`, `update_provider`, `set_active_provider` e `delete_provider` fazem commit dentro do service; só depois o router grava audit com `commit=True`. Se o audit falhar, a alteração permanece sem trilha. Na criação, o catch ainda pode responder 500 após a criação já confirmada.
* MCP e integration connection services também commitam internamente e atualmente nem tentam auditar; adicionar audit apenas no router repetiria o mesmo defeito.
* Billing/webhooks/jobs geralmente não têm ator humano; alguns services só adicionam evento e deixam o commit ao chamador. `billing_enforcement_service` omite `tenant_id` em eventos bloqueados em uma chamada, criando audit global/anônimo se for confirmado.
* `_write_flow_audit_log` retorna `False` e apenas avisa quando não há `current_user`; o chamador continua. Endpoints canônicos publish/republish nem têm dependência de usuário. Isso permite operação sem evento.

Não existe fila/outbox/retry para audit. Falha não é ignorada dentro do helper, mas os efeitos dependem da fronteira transacional do chamador; não há métrica/alerta próprio de perda de auditoria.

## H. Retenção

Não foi encontrada política, job, TTL, archive, purge ou configuração por tenant para `audit_logs`. Na prática os registros permanecem indefinidamente **enquanto o tenant existir**. Ao excluir o tenant, a FK cascade apaga todo o histórico. Isso combina retenção ilimitada de IP/UA/PII com destruição total no encerramento do tenant, sem política explícita ou legal hold.

Os recursos de billing chamados `observability_retention_days` são entitlement de observabilidade e não uma política do Audit Log. Retenção de traces/runtime não deve ser confundida com retenção administrativa.

## I. Exclusões importantes

“Quem pode apagar” abaixo descreve enforcement visível no handler: `get_current_user` + RBAC quando presente; somente `get_current_tenant` não demonstra role administrativa.

| Recurso | Endpoint/caminho | Quem pode apagar | Audit? | Tipo |
|---|---|---|---:|---|
| usuário | `DELETE /workspace/users/{user_id}` | owner/admin, sujeito à hierarquia/último owner | sim | hard delete |
| flow legado/canônico | `DELETE /flows/{flow_id}` e CRUD equivalente | usuário autenticado no legado/canônico normal | sim | soft se em uso; senão hard, com fallback soft |
| flows em massa/runtime state | reset tenant flows/admin hard reset | header/tenant conforme handler; sem evento uniforme | não | hard deletes/limpeza operacional |
| AI agent | sem entidade CRUD própria; dentro de flow | mesma permissão do flow | só `FLOW_UPDATED` em alguns saves | alteração/hard/soft conforme flow |
| integration Google | endpoints disconnect e `/integrations/connections/{provider}` | contexto de tenant, sem role/ator no handler | não | soft/status + remoção/limpeza de tokens conforme service |
| WhatsApp provider | `DELETE /api/whatsapp/providers/{provider_id}` | usuário autenticado do tenant | sim, após commit | hard delete |
| MCP server | `DELETE /mcp/servers/{server_id}` | contexto de tenant, sem role/ator | não | hard delete |
| template | `DELETE /.../templates/{template_id}` | contexto de tenant, sem role/ator | não | hard delete |
| conversation | nenhum DELETE de conversation localizado | — | — | — |
| contact | `DELETE /contacts/{contact_id}` | contexto de tenant | não | hard delete |
| tenant | nenhum endpoint DELETE localizado | DB/script direto | não; cascade apaga audit | hard delete possível no modelo/DB |
| AI key | `DELETE /ai/settings/key` | contexto de tenant | não | clear/soft (coluna `NULL`) |
| memória IA | `DELETE /ai/memories/{memory_id}` | contexto de tenant | não | hard delete |
| knowledge source | `DELETE /knowledge/sources/{source_id}` | contexto de tenant | não | service delete |
| bot rule/product/pipeline stage/campaign | respectivos DELETE | contexto de tenant | não | hard delete (ou service-specific) |

## J. Arquivos prováveis para implementação futura

Sem alterar nesta etapa:

* núcleo/schema/migration: `backend/app/models/audit_log.py`, `backend/app/services/audit_service.py`, `backend/app/schemas/account.py`, nova migration Alembic e testes de imutabilidade/retention;
* segurança/consulta: `backend/app/routers/account.py`, `backend/app/security/workspace_rbac.py`, `backend/app/routers/auth.py`, `backend/tests/test_workspace_rbac.py`;
* tenant/settings: `backend/app/routers/settings.py`, `backend/app/routers/appointment_policy.py`, `backend/app/routers/account.py`;
* flows (sem tocar no Runtime V2): `backend/app/routers/flows.py` e testes dos endpoints publish/restore/reset/duplicate;
* IA: `backend/app/routers/ai_settings.py`, `backend/app/routers/ai_memories.py` e, se criada uma entidade administrativa de agent, seu router/service;
* integrações: routers `google_*_integration.py`, `gmail_integration.py`, `meta_integration.py`, `suitable_integration.py`, `integration_connections.py`, `whatsapp_providers.py`, `mcp.py`; services `integration_connection_service.py`, `whatsapp_provider_service.py`, `mcp_service.py`;
* recursos administrativos: `whatsapp_templates.py`, `bot_rules.py`, `knowledge.py`, `chat.py`, `leads.py`, `products.py`, `whatsapp_campaigns.py`;
* exposição em logs: `workers/message_worker.py`, `routers/webhook.py`, `routers/flows.py`, `flow_v2/contracts.py`, `flow_v2/executors/agent_system_executor.py`, `routers/whatsapp_templates.py` (redução/redação de application/runtime logging, sem transformar conversa em audit).

## K. Plano recomendado de implementação

1. **P0 — conter exposição de conteúdo/secrets:** redigir payload bruto de webhook, texto de conversa/resposta, graphs/payloads integrais e template variables; criar utilitário único de sanitização e testes negativos para password/token/key/Authorization/cookie.
2. **P0 — integridade e atomicidade:** definir política append-only no DB, remover a dependência destrutiva de cascade conforme política legal, e refatorar fronteiras transacionais de WhatsApp/MCP/integrations antes de adicionar eventos. Operação e audit devem confirmar juntos ou usar outbox confiável.
3. **P0 — autenticação/autorização administrativa:** exigir identidade humana e permissão explícita em settings, IA, MCP, templates e conexões; persistir security events para recusas relevantes/cross-tenant sem revelar o alvo.
4. **P1 — integrações e credenciais:** eventos distintos connect/update/disable/disconnect/delete/credential-rotated, com provider/resource, ator, tenant e apenas nomes dos campos/fingerprint seguro — nunca secret.
5. **P1 — flows:** cobrir publish/republish/restore/duplicate/reset, sempre com ator, flow, old/new version ID, snapshot hash e resultado; manter conteúdo do grafo fora do audit.
6. **P1 — tenant e IA:** registrar criação/update/nome/profile/security settings e AI provider/model/prompt/config/enable/key rotation usando diff allowlisted e sem prompt/texto completo quando contiver dados sensíveis.
7. **P1 — templates/canais/agenda/tools:** cobrir CRUD, submit, enable/disable e deletes, com controle de role.
8. **P2 — consulta:** cursor determinístico, paginação/contagem e filtros por resource/target/result/IP; manter filtro de tenant não sobrescrevível e testes adversariais.
9. **P2 — retenção/compliance:** política explícita por classe de evento, minimização de IP/UA/PII, archive/legal hold e purge auditável; separar retenção de runtime/observabilidade.
10. **P2 — governança:** enum/taxonomia versionada, outcome/source/request ID, testes de cobertura de cada caminho alternativo, métrica/alerta de falha e revisão periódica de bypasses.

## Conclusão

**AUDIT LOG PARCIAL**

Os pontos positivos são a tabela persistente central, o filtro obrigatório de tenant na consulta, a autorização owner/admin, eventos de autenticação/RBAC com boa identificação e atomicidade de várias operações de usuário/flow. Os impeditivos para considerá-lo adequado são: grandes áreas administrativas sem eventos; publicação/restauração de flow sem trilha uniforme; ausência de ator em diversos endpoints; provider WhatsApp não atômico; metadata sem proteção contra secrets; logs operacionais com conteúdo/PII; imutabilidade não garantida; e retenção contraditória (indefinida, mas apagada em cascade com o tenant).

## Apêndice: comandos de verificação executados

```bash
find .. -name AGENTS.md -print
find backend -type f | sort
rg -n -i --glob '!**/__pycache__/**' '(audit[_ -]?log|audit_event|security_event|event_log|activity_log|\baudit\b)' backend
rg -n -C 2 'write_audit_log\(' backend/app --glob '*.py'
rg -n -C 2 'AuditLog\(' backend/app --glob '*.py'
rg -n '^@(router|crud_router)\.(get|post|put|patch|delete)' backend/app/routers backend/app/api --glob '*.py'
rg -n -i --glob '*.py' '(print|logger\.(debug|info|warning|error|exception))\([^\n]*(password|token|secret|api.?key|credential|authorization|cookie|jwt|oauth|smtp|client.?secret|access.?token|refresh.?token)' backend
rg -n -i '(retention|cleanup|purge|ttl|archive|delete\(AuditLog|AuditLog.*delete|audit_logs)' backend/app backend/alembic --glob '*.py'
DATABASE_URL=sqlite:////tmp/wazza-audit-test.db PYTHONPATH=backend pytest -q backend/tests/test_workspace_rbac.py backend/tests/test_register_trial.py backend/tests/test_trial_service.py
```
