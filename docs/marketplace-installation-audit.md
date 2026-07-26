# Auditoria de materialização dos Business Intelligence Kits

## Estado anterior

O callback vivia no frontend: o catálogo entregava um `installManifest` declarativo
ao callback do Flow Builder. Não existiam endpoint, instalação ou transação no
servidor. `flows` era parcialmente suportado; `nodes` e `edges` dependiam do grafo
montado pela UI. As demais seções eram apenas exibidas ou ignoradas.

## Matriz após esta entrega

| Seção | Classificação |
|---|---|
| flows, nodes, edges | materializado em grafos editáveis no runtime `v2` padrão |
| knowledge_bases | materializado nas variantes com IA |
| pipeline_stages | materializado; registros preexistentes são reutilizados |
| pipelines | parcialmente suportado: há estágios tenant-wide, mas não entidade Pipeline |
| checklist | materializado no estado versionado da instalação |
| ai_agents, tags, custom_fields, dashboards | `capability_not_supported`; nenhum registro falso |
| academy, documentation | `preview_only`; não há persistência tenant/versionada |
| methodologies, post_install_steps | snapshot/preview; o checklist executa os passos |

## Segurança, idempotência e rollback

O tenant vem das dependências autenticadas e somente `owner`/`admin` ativo instala.
A constraint `(tenant_id, idempotency_key)` retorna o resultado original. Cada
recurso registra ownership; rollback remove somente o que a instalação criou.
Integrações ausentes resultam em `needs_configuration` e checklist bloqueado.
