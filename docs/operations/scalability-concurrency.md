# Sprint de escalabilidade, concorrência e carga

## Escopo e princípio

Este documento cobre somente API Wazza, PostgreSQL, Redis, os dois RQ workers,
Delay Worker e os frontends de produção/staging. O `wazza-mcp-test-server` é um
servidor externo de teste e está explicitamente fora da capacidade operacional.

O contrato de concorrência é **paralelismo entre conversas diferentes e
serialização dentro de uma conversa**. A identidade de entrada é sempre
tenant + provider + `external_message_id` (`wamid`); telefone nunca é uma
identidade global.

## Caminho encontrado

1. `POST /webhook` valida a assinatura/estrutura e chama
   `enqueue_webhook_payload`.
2. O ingresso resolve tenant e provider a partir de `phone_number_id`, anexa
   `tenant_id`, `provider_id` e `correlation_id`, e enfileira
   `process_incoming_message`.
3. O job `inbound_message` vai para `INCOMING_MESSAGE_QUEUE` (`high_priority`
   por padrão), com cinco tentativas em 2/5/15/45/120 s e timeout de 60 s.
4. O worker normaliza a mensagem, resolve novamente o tenant e toma o lock
   Redis `wazza:inbound:conversation:{tenant_id}:{normalized_phone}`. Antes de
   existir uma linha de conversa, telefone normalizado é a identidade estável
   usada pela própria consulta de conversa; depois da criação, `conversation_id`
   é propagado ao Flow e aos jobs outbound.
5. `processed_messages` faz o compare-and-insert durável por tenant e message
   id. Somente o vencedor persiste contato, conversa, lead e mensagem, executa
   o runtime Flow/Bot/IA, confirma a transação e publica atualização Redis/SSE.
6. Respostas usam `whatsapp_send` na fila `normal`; o send worker usa lock
   tenant+telefone e sequência de fluxo antes de chamar a Meta, persiste a
   saída e publica tracing.

O Runtime V2 também usa advisory lock PostgreSQL por sessão; delays são jobs
perfilados na fila `low` e devem revalidar sessão/estado ao retomar.

## Proteções e limites atuais

* **Deduplicação:** o índice/`ON CONFLICT DO NOTHING` em `processed_messages`
  é a autoridade durável. Não há dedupe Redis prévio no inbound: ele poderia
  marcar uma mensagem como processada antes de uma falha e causar perda na
  tentativa seguinte.
* **Lock:** TTL obrigatório (15 s por padrão), token UUID e liberação Lua
  compare-and-delete, portanto um worker expirado não remove lock de novo
  owner. Contenção levanta erro retryável para RQ; não usa polling/busy wait.
* **Ordenação:** a fila não é considerada ordenada. O lock serializa a unidade
  de conversa e uma mensagem que chega durante o processamento é reagendada
  pelo backoff. A ordem efetiva é a ordem de aquisição após persistência; não
  existe ainda sequência persistida baseada no timestamp da Meta.
* **Cancelamento/versionamento:** Fluxos V2 protegem sessão com advisory lock,
  mas conversa/lead não possuem coluna de versão otimista. Antes de ampliar
  concorrência de IA, adicionar CAS de `conversation.updated_at`/versão e
  revalidar modo humano imediatamente antes do envio.
* **Idempotência outbound:** o lock e a gravação local impedem concorrência,
  mas uma queda exatamente após aceitar a chamada Meta e antes de persistir a
  saída ainda requer uma chave idempotente suportada pelo provedor ou outbox
  transacional. Não alegar entrega exactly-once até isso existir.

## Filas, workers e escala

As filas configuradas são `high_priority` (inbound), `normal` (outbound) e
`low` (delay/AI longa); `flow_execution` pode usar `default`. O worker atual
consome high, normal e low em ordem de prioridade. Isso pode produzir
head-of-line blocking de IA/delay; a separação incremental recomendada é uma
réplica dedicada a `low` antes de criar filas adicionais. Mantenha pelo menos
um worker consumindo high+normal para preservar ACK/processamento rápido.

Não aumente workers sem calcular conexões: `API processes × pool máximo + RQ
workers × pool máximo + Delay Worker × pool máximo` deve ficar abaixo do limite
PostgreSQL com margem operacional. Cada job deve fechar a sessão; não mantenha
transações durante chamadas Meta/IA/MCP. Timeouts atuais de job são 60 s
inbound, 90 s outbound, 120 s flow, 180 s delay e 300 s IA longa. Chamadas HTTP
externas devem receber timeout próprio menor que o timeout do job.

Use namespace de Redis por ambiente ao configurar `REDIS_URL`/prefixos; nunca
compartilhe Redis staging e produção. Chaves de lock, sequência e idempotência
devem conter tenant. Monitorar memória, eviction, TTLs, `rq:queue:*` e
heartbeats dos workers.

## Operação e incidentes

* **Fila parada:** verificar ping Redis, `rq info`, idade do job mais antigo,
  `StartedJobRegistry`, logs `event=job_started` e heartbeat do processo. Um
  processo Railway vivo não comprova consumo.
* **Conversa travada:** consultar o lock Redis com TTL; nunca apagar lock sem
  confirmar expiração/owner. O TTL permite recuperação de crash.
* **Falhas:** jobs esgotados chamam `record_dead_letter`; investigar tenant,
  conversation, trace/correlation id, tentativa, fila e motivo sanitizado
  antes de reprocessar manualmente.
* **Backpressure:** priorizar high/normal, manter delay/analytics/AI longa em
  low, limitar entrada/IA por tenant com Redis, e expor degradação em vez de
  bloquear webhook. O limite existente de enqueue é por tenant.
* **Rollback:** reverter o commit, executar migrações somente pelo serviço de
  release (lock advisory), drenar jobs compatíveis e observar DLQ/retries.

## Observabilidade e critérios iniciais

Correlacionar logs com `tenant_id`, `conversation_id`, `message_id`, `job_id`,
`execution_id`/`trace_id`, `attempt`, fila, duração e status, sem conteúdo
integral ou segredos. Alertar em crescimento de fila/idade, retries, DLQ,
contenção de lock, deduplicações e falha de heartbeat. Metas iniciais para
caminho sem IA: zero duplicatas/mistura de tenant/execução mutável concorrente
e erro abaixo de 1%; medir p95 de webhook separadamente do tempo do provedor.

## Carga reproduzível (ambiente isolado)

Use `k6 run docs/loadtest/webhook.js` apenas com `BASE_URL` de staging isolado,
token/payload sintéticos e integrações IA simuladas. O script recusa hosts que
parecem produção. Execute perfis 10, 50, 100, 250 e 500 msg/s progressivamente
e pare no primeiro gargalo seguro. Registre throughput, p50/p95/p99, erros,
profundidade/idade de filas, CPU/memória e conexões PostgreSQL/Redis; não há
resultado de capacidade nesta sprint porque nenhuma carga foi executada contra
uma infraestrutura isolada provisionada.

Cobrir A webhook leve, B fluxo simples, C IA simulada, D conversas distintas,
E rajada mesma conversa, F duplicatas, G delays e H timeout/rate-limit/Redis e
provedor indisponíveis. Os testes de concorrência devem usar PostgreSQL e Redis
reais quando o ambiente CI disponibilizá-los.
