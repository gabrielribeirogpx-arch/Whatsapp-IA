# Dashboard — Fase 4: lifecycle, abandono e autoria

## Princípio

Esta fase mantém a regra: **não inferir histórico que o sistema não consegue
provar**. A cobertura histórica dos campos canônicos começa com a aplicação da
migration da Fase 4. Não há backfill a partir de `created_at`, `updated_at`, texto,
estado atual ou `from_me`.

## Auditoria das fontes existentes

| Evento conceitual | Fonte anterior | Timestamp confiável? | Ator conhecido? | Histórico confiável? | Decisão da Fase 4 |
|---|---|---:|---:|---:|---|
| conversa iniciada | `Conversation.created_at` | sim | cliente/integração não distinguido | sim para criação | sem alteração |
| customer message | `Message(from_me=false).created_at` | sim | direção apenas | não para autoria legada | novas entradas recebem `sender_type=customer` |
| outbound | `Message(from_me=true).created_at` | sim | não | não para autoria legada | manter `from_me`; adicionar autoria nullable |
| resposta de flow | filas com `flow_id`, `flow_version_id`, `session_id` ou `node_id` | sim | executor do flow | sim somente no momento da emissão | persistir `automation` |
| resposta de IA | `node_type` de família `ai_*` no payload do Runtime V2 | sim | IA | sim somente no momento da emissão | persistir `ai` antes de `automation` |
| resposta humana | endpoint autenticado de envio do Inbox | sim | operador (categoria) | sim somente no momento da emissão | persistir `human_agent` |
| mensagem de sistema | não há produtor persistente inequivocamente identificado | — | — | não | valor reservado; não classificar por heurística |
| takeover/retorno | `AuditLog` append-only `CONVERSATION_MODE_CHANGED`, com old/new mode | sim desde a introdução do audit | usuário quando fornecido | cobertura parcial | manter como evento; não criar timestamp na conversa |
| conclusão de flow | `FlowSession.completed_at` na primeira transição `completed` | sim desde a Fase 3 | sistema | sim desde a Fase 3 | não equiparar a resolução da conversa |
| abandono/expiração/reset | transição explícita de `FlowSession.status` para `abandoned`/`expired` | antes: não; agora: sim | sistema/runtime | não para legado | capturar primeiro `abandoned_at` |
| fechamento/resolução | não existe evento inequívoco de conversa resolvida | não | não | não | nenhuma coluna/KPI novo |
| timeout | estado `expired`, sem causa estruturada universal | antes: não | sistema | não para legado | conta como transição terminal abandonada futura |
| reabertura | mudança posterior de status/modo | momento parcial | parcial | parcial | timestamps de primeiro evento não são reescritos |
| lead convertido | `Lead.converted_at` | sim desde a Fase 3 | sistema | sim desde a Fase 3 | sem alteração |

Também existem `FlowEvent`, eventos do Runtime V2 e eventos de analytics. Eles
descrevem execução de flows, mas não formam um event store único e completo para
todo o lifecycle de conversa. Não foram promovidos artificialmente a fonte de
resolução ou abandono.

## Contrato canônico de autoria

`Message.sender_type` é nullable e aceita:

* `customer`: mensagem inbound persistida pelos ingressos WhatsApp;
* `human_agent`: envio feito pelo endpoint autenticado do Inbox;
* `ai`: saída enfileirada por nó cujo tipo canônico é `ai_*`;
* `automation`: resposta de regra/bot ou saída de flow com metadados estruturados;
* `system`: reservado para um futuro produtor que prove essa origem.

`from_me` continua existindo e seus contratos públicos não mudam. `sender_type`
não é derivado de `from_me`, do texto nem do modo atual da conversa. Um envio
genérico de fila que não carrega evidência fica `NULL`.

## Primeira resposta

Para a taxa de resposta, o inbound elegível é uma mensagem `customer` criada na
janela civil selecionada. Uma resposta válida é a primeira mensagem posterior da
mesma conversa, antes do fim exclusivo da janela, cuja autoria seja
`human_agent`, `ai` ou `automation`. `system` e `NULL` não contam.

O tempo médio mantém os ciclos da Fase 3 (primeiro inbound pendente seguido da
primeira resposta), mas agora aplica a mesma autoria canônica. A mensagem já é o
evento temporal imutável; não foi criada uma coluna redundante
`first_response_at`. Primeira resposta humana é comprovável por consultas a
`human_agent`, porém nenhum KPI/contrato novo foi exposto nesta fase.

## Definição formal de abandono

**ABANDONED** = uma `FlowSession` que sofreu uma transição explícita para
`abandoned` ou `expired`, incluindo reset explícito que encerra a sessão como
`expired`. O primeiro instante dessa transição é `abandoned_at`.

**NOT ABANDONED** = sessão sem `abandoned_at`; conclusão de flow, conversão,
conversa em modo humano e mera inatividade não são abandono por si sós.

* unidade: sessão de flow;
* denominador: sessões do tenant criadas em `[start, end)`;
* numerador: subconjunto do denominador com `abandoned_at` em `[start, end)`;
* resposta tardia/takeover: não apagam o evento;
* reabertura: preserva o primeiro abandono;
* multiplicidade: uma sessão pode transicionar mais de uma vez, mas conta uma vez;
  sessões distintas da mesma conversa continuam unidades distintas.

Essa definição preserva o significado operacional que o código já dava a
`abandoned` e `expired`; não tenta distinguir timeout de reset onde a origem não
está estruturada de maneira universal. A janela usa comparação semiaberta, de
modo que um abandono exatamente em `end` pertence apenas à próxima janela.

## Takeover, retorno e reabertura

`set_conversation_mode` grava evento append-only com `old_mode`, `new_mode`,
fonte, motivo e usuário quando disponível. Isso comprova mudanças executadas por
esse serviço, inclusive `automation -> human` e retorno, mas não garante que todo
código legado histórico tenha passado por ele. Por isso não foi criada
`transferred_to_human_at` nem uma taxa de takeover.

Reabrir sessão, devolver a conversa ao bot/IA, responder tardiamente ou alterar o
status de um lead não apaga os primeiros timestamps já capturados. Conversão e
conclusão continuam com os contratos idempotentes da Fase 3.

## Timezone e janelas

Não há segunda implementação temporal. O dashboard continua usando
`tenant.timezone`, `ZoneInfo`, armazenamento UTC e helpers da Fase 3. Períodos
customizados são dias civis do tenant convertidos para UTC, e todas as janelas
são `[start, end)`.

## Migration, desempenho e observabilidade

Migration `20260926_dashboard_phase4`, sobre
`20260926_dashboard_phase3`, adiciona:

* `messages.sender_type` nullable, check constraint e índice
  `(tenant_id, sender_type, created_at)`;
* `flow_sessions.abandoned_at` nullable e índice
  `(tenant_id, abandoned_at)`.

As taxas usam `COUNT`, subqueries/`EXISTS` e filtros tenant-scoped. Os índices
correspondem aos filtros reais de autoria/tempo e abandono/tempo. Nenhum novo log
inclui texto, telefone, nome, tokens, variáveis de sessão ou payload bruto.

## Legacy e limitações

Registros anteriores permanecem `sender_type=NULL` e `abandoned_at=NULL`. Em
consequência, métricas canônicas podem mostrar amostra vazia/`—` para períodos
sem cobertura; isto é preferível a reconstruir autoria ou datas.

Limitações remanescentes:

1. não existe resolução canônica de conversa; `FlowSession.completed_at` prova
   conclusão de flow, não resolução;
2. não existe abandono canônico no nível de conversa ou lead;
3. causa de `expired` não é normalizada para separar timeout, reset e abandono;
4. autoria genérica de alguns envios legados/filas permanece desconhecida;
5. o histórico de mudança de modo é confiável apenas para chamadas que passaram
   pelo serviço auditado;
6. nenhuma fonte real de CSAT existe e CSAT continua `NULL`;
7. não foi acessado banco de produção e não havia staging necessário para esta
   implementação; testes locais não provam detalhes exclusivos do PostgreSQL.
