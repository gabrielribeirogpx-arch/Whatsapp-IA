# Export de Flow

## Finalidade e diagnóstico da arquitetura atual

O Flow Builder persiste o registro principal em `flows`. Além de nome, descrição,
tenant, estado (`status`/`is_active`), seletor de runtime e configurações de gatilho,
o grafo editável fica nas colunas JSON `nodes`/`nodes_json` e `edges`/`edges_json`.
Cada node conserva seu ID lógico, `type`, `data` e `position`; cada edge conserva
IDs lógicos, `source`, `target`, `sourceHandle`, `targetHandle`, label e data. Não há
uma coluna de viewport/zoom nem um registry global de variáveis no contrato atual:
variáveis, mensagens, escolhas, Coleta de Dados, agenda e tools ficam no `data` dos
nodes. Os registros relacionais `flow_nodes`/`flow_edges` são um fallback legado.
O `tenant_id` do Flow define o workspace proprietário.

Leitura e gravação do editor usam, respectivamente, `GET /api/flows/{flow_id}` e
`POST /api/flows/{flow_id}/save` (além do `PUT` legado). A ativação/publicação aplica
validação e produz uma versão imutável consumida pelo Runtime V2. O export não chama
essa validação: um draft incompleto continua exportável, com edges sem destino
registradas em `validation.warnings` para diagnóstico.

Exemplo abreviado do formato persistido do editor:

```json
{
  "nodes": [{
    "id": "collect-email",
    "type": "data_collection",
    "position": {"x": 280, "y": 120},
    "data": {"prompt": "Qual é seu e-mail?", "variable_name": "email"}
  }],
  "edges": [{
    "id": "edge-success",
    "source": "collect-email",
    "target": "finish",
    "sourceHandle": "success",
    "targetHandle": "input"
  }]
}
```

## Snapshot não é Export

**Snapshot já equivale tecnicamente a um export portátil do Flow Builder? NÃO.**

`FlowVersion.snapshot` é uma versão interna, tenant-scoped e associada por chaves de
banco ao Flow. Publicar cria esse snapshot para execução; o histórico lista versões e
permite restaurá-las para o editor. Ele não gera arquivo, não é um contrato público de
portabilidade, pode conter metadados internos de runtime/hash e não aplica a política
de remoção de credenciais do export. Embora contenha nodes e edges suficientes para o
runtime, sua finalidade é versionamento/restauração interna. Esta entrega não modifica
Snapshot, restauração, publicação, ativação nem Runtime V2.

## Contrato canônico

`GET /api/flows/{flow_id}/export` responde JSON com `Content-Disposition` e extensão
`.wazza-flow.json`. `schema_version` começa em `1`:

```json
{
  "format": "wazza_flow",
  "schema_version": 1,
  "exported_at": "2026-09-26T00:00:00Z",
  "flow": {
    "name": "Clínica Modelo",
    "description": "Agendamento",
    "runtime_version": "v2",
    "status": "draft",
    "nodes": [{
      "id": "choose-slot",
      "type": "choice_dynamic",
      "position": {"x": 120, "y": 80},
      "data": {"result_variable": "selected_slot", "appointment_period": "morning"}
    }],
    "edges": [{
      "id": "selected",
      "source": "choose-slot",
      "target": "confirm",
      "sourceHandle": "selected",
      "targetHandle": "input"
    }],
    "variables": [],
    "settings": {"trigger_type": "default", "priority": 0},
    "metadata": {"source_version": 7, "is_active": false}
  },
  "validation": {"valid_references": true, "warnings": []}
}
```

Os IDs de nodes/edges e handles são preservados porque formam a identidade estrutural
do grafo. IDs do registro Flow, tenant, versões e execuções não são exportados. Como
não existe registry separado de variáveis, `variables` é reservado e atualmente vazio;
as definições e referências reais permanecem integralmente nos nodes.

## Segurança, dados sensíveis e RBAC

Pode ser exportado: tipos e nomes lógicos de integração/tool, capabilities, schemas de
entrada, configuração funcional, mensagens/templates, condições, operadores, posições,
handles, variáveis e referências abstratas. Não pode ser exportado: access/refresh
tokens, API keys, passwords, client/webhook secrets, authorization/cookies ou objetos
de credentials. Referências tenant-bound conhecidas (`connection_id`, `server_id`,
`integration_id`, provider/phone IDs) viram `{{integration.configure_on_import}}`, sem
alterar a definição persistida. Campos legítimos como `max_tokens` e
`idempotency_key` não são removidos por coincidência textual.

O risco arquitetural observado é que o JSON flexível dos nodes historicamente permite
que clientes antigos gravem credenciais diretamente. O export trata essa fronteira com
sanitização recursiva por nomes exatos conhecidos; nenhuma migração ampla foi feita.
Histórico de conversas, leads, mensagens recebidas, logs e estado de execução vivem em
outras tabelas e jamais entram no contrato.

A rota exige autenticação, usuário ativo e header de tenant, busca o Flow já filtrado
pelo tenant e devolve 404 tanto para ID ausente quanto para ID de outro tenant. Owner,
admin, member e viewer podem exportar: essa decisão acompanha a leitura já disponível
do Flow Builder; papéis desconhecidos falham fechados. A ação `FLOW_EXPORTED` é gravada
no audit log somente com identificadores/metadados seguros, nunca com o JSON exportado.

Importação, compartilhamento cross-tenant, marketplace/template, clonagem e qualquer
novo versionamento estão explicitamente fora deste escopo.
