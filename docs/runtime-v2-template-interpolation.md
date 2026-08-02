# Runtime V2 — interpolação de variáveis

## Causa-raiz e superfícies investigadas

O `MessageNodeExecutor` renderiza por `BaseNodeExecutor._render`, que usa
`flow_v2.template_renderer.render_template`. O renderer montava o contexto apenas com
metadados seguros e `session.context`; ele não lia `flow_v2_sessions.variables`. Assim,
a Coleta de Dados persistia corretamente nesse JSONB, mas a Mensagem não via o valor.
A IA Classificação, por sua vez, gravava apenas no campo legado `context`.

Condição e Mensagem usam a sessão carregada pelo executor, inclusive após retomadas do
worker. O `send_worker` recebe uma `SendMessageAction` já renderizada e não interpola
novamente. Runtime V1 e simulador legado têm pipeline próprio e não foram alterados; a
simulação que seleciona Runtime V2 usa o mesmo executor e renderer da produção. O
preview do editor é somente visual e preserva o template salvo pelo builder.

## Contrato

O contexto é composto, da menor para a maior precedência, por contexto legado,
metadados seguros, variáveis persistidas e outputs do node atual. As variáveis também
são expostas sob `variables`. São aceitas `{{name}}` (canônica),
`{{variables.name}}`, dot notation e `{name}` (compatibilidade legada).

Variáveis ausentes continuam vazias por padrão, preservando o contrato anterior.
`FLOW_V2_MISSING_VARIABLE=preserve` mantém o placeholder literal. Nos dois modos é
emitido `event=runtime_v2_template_render` com node/sessão, chaves resolvidas e
ausentes e previews com e-mail/telefone redigidos.
