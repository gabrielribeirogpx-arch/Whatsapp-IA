# Dashboard — Fase 3: política histórica e diagnóstico

## Decisões canônicas

- Todos os intervalos são semiabertos: `[start, end)`.
- Presets (`24h`, `7d`, `30d`, `90d`) continuam sendo durações móveis absolutas.
- Datas customizadas são dias civis no timezone IANA do tenant e viram UTC antes da query.
- Taxa e tempo médio de resposta só observam respostas anteriores ao `end` da própria janela. Uma entrada às 23:59 respondida às 00:05 do dia seguinte não conta na janela encerrada à meia-noite.
- `Lead.converted_at` registra a primeira conversão. Reabertura e reconversão não apagam nem reescrevem esse instante.
- `FlowSession.completed_at` registra a primeira transição para `completed`. Reabertura não o limpa.
- Registros anteriores à migration permanecem nulos e são excluídos das métricas temporais; não há backfill especulativo.

## Auditoria dos caminhos de conversão

| Caminho | Converte lead? | Emitia `LEAD_CONVERTED`? | Podia duplicar? | Podia faltar? |
|---|---:|---:|---:|---:|
| API/drag-and-drop `move_lead` para estágio final | Sim | Sim | Sim, após sair e voltar ao final | Não |
| `flow_analytics_service` ao registrar conversão do runtime | Sim, movia ao estágio final | Não | O evento analítico possui dedupe próprio, mas o AuditLog não existia | Sim |
| Alteração da configuração `is_final_stage` | Não é uma conversão do lead | Não | Não | O estado corrente podia parecer convertido sem evento histórico |
| Criação/importação/auto-criação | Não; cria lead ativo no primeiro estágio | Não aplicável | Não | Não |
| Exclusão de estágio | Move leads ao fallback, não converte | Não | Não | Não |
| Escrita direta externa ao ORM/banco | Não há contrato suportado | Não | Indeterminado | Sim |

O AuditLog append-only é útil para atividade, mas não cobria o runtime e permitia múltiplos eventos do mesmo lead após reabertura. Por isso ele não é mais a fonte numérica. A fonte canônica simples é `converted_at`, com uma contagem por lead e timestamp imutável da primeira conversão. Histórico sem evento confiável não foi inventado.

## Sessões

Não há event store único cobrindo todas as mutações de `FlowSession`: há `FLOW_COMPLETED` em um caminho, mas reset, publicação e serviços legados também finalizam sessões. O timestamp nullable foi preferido a criar um segundo evento incompleto. A instrumentação ORM cobre transições normais; a atualização em lote da publicação usa `coalesce`, preservando a primeira conclusão.

Estados `converted`, `abandoned`, `expired`, `finished` e erros não são tratados como conclusão. Somente o valor exato `completed` define `completed_at`.

## Timezone e gráfico

O tenant passa a ter `timezone`, default `UTC`, validado pelo resolvedor com `zoneinfo.ZoneInfo`; offsets soltos são rejeitados. Limites e queries continuam em UTC naive, conforme o armazenamento atual. Buckets quebram em meia-noite local e portanto respeitam DST. A label é a data civil local. O frontend interpreta labels `YYYY-MM-DD` como data civil ao meio-dia, evitando recuo de dia em browsers com offset negativo.

## CSAT e SLA

A busca por `csat`, `satisfaction`, `survey`, `rating`, `feedback`, `NPS`, `nota` e `reaction` não encontrou uma avaliação de conversa com escala, timestamp e tenant. `quality_rating` é qualidade do número/template da Meta, e não satisfação. CSAT continua visível como `—`/`null`, sem dado fabricado.

Não existe um SLA canônico de resposta do dashboard. A política fechada no fim do período foi escolhida em vez de criar configuração arbitrária. A política de agenda/business hours não representa SLA de atendimento e não foi reutilizada indevidamente.

## API, observabilidade e limites

Os campos existentes foram preservados. Foram acrescentados `response_rate_details` e `abandonment_rate_details`, com numerador e denominador. Logs em debug incluem tenant, timezone, limites, métrica e componentes, sem conteúdo de mensagem ou PII.

Limites conhecidos:

- dados anteriores à migration não recebem `converted_at`/`completed_at` e ficam fora das métricas temporais;
- autoria `from_me` ainda agrega humano, bot e IA;
- abandono ainda reflete o status final atualmente observado da coorte e pode mudar; um timestamp/evento de abandono fica para uma fase futura;
- distribuição de canais e conversas movimentadas continuam baseadas em `updated_at`, conforme contrato da Fase 2;
- não havia credencial identificada de homologação para validação destrutiva; qualquer validação externa deve ser somente leitura.
