# Auditoria de nome de exibição do Pipeline

## Registro inicial (antes da correção)

O `GET /api/pipeline` entrega cada card em `stages[].leads[]`. A resposta é
serializada diretamente do modelo `Lead` para `PipelineLeadOut`; não inclui o
objeto `contact`, `conversation`, `preview`, `body` ou `message`.

Exemplo representativo e sanitizado do objeto de lead entregue ao frontend
(campos e estrutura conferidos no serializador em `backend/app/routers/leads.py`
e no contrato `backend/app/schemas/lead.py`):

```json
{
  "id": "00000000-0000-0000-0000-000000000001",
  "name": "Contato de teste",
  "phone": "5511999990000",
  "last_message": "olá",
  "temperature": "cold",
  "score": 0,
  "email": null,
  "source": "whatsapp",
  "status": "active",
  "contact_id": "00000000-0000-0000-0000-000000000002",
  "conversation_id": "00000000-0000-0000-0000-000000000003",
  "stage_id": "00000000-0000-0000-0000-000000000004",
  "last_interaction": "2026-07-20T00:00:00",
  "entered_stage_at": "2026-07-20T00:00:00"
}
```

- **Nome presente:** `name` (campo do `Lead`).
- **Telefone presente:** `phone`.
- **Mensagem presente:** `last_message`.
- **Campos ausentes nesse endpoint:** `contact.name`, `contact.display_name`,
  `lead.contact_name`, `customer_name`, `conversation.contact.name`, `preview`,
  `body` e `message`.

> A instância remota configurada não pôde ser consultada neste ambiente: a
> tentativa de `GET https://api.wazzaapi.com.br/api/pipeline` foi bloqueada pelo
> proxy com HTTP 403 antes de chegar à API. Portanto, o exemplo acima omite
> dados sensíveis e registra o objeto realmente consumido pelo frontend conforme
> o contrato/serialização em execução no repositório, não dados de produção.

## Resultado da auditoria

- O card do Pipeline não calculava `displayName`: renderizava `lead.name`
  diretamente, tanto no Kanban quanto no Pipeline Mobile e no drawer.
- O webhook tinha um fallback incorreto: tratava qualquer mensagem curta sem
  dígitos como nome e gravava esse texto em `Conversation.name` e, na ausência
  de um nome de contato, em `Contact.name`. Assim, a mensagem `olá` podia virar
  um nome persistido que chegava ao Pipeline.
- A resposta do Pipeline agora inclui `contact_name`, resolvido pela relação
  `Lead.contact_id`, e o frontend usa `resolveLeadDisplayName()` com a ordem:
  nome do contato, nome do lead, telefone formatado e `Contato sem nome`.
  O helper não aceita `last_message`, `preview`, `body` ou `message`.
- CRM e as telas de conversa mobile usam o contrato `Conversation`/`CRMContact`
  e já renderizam nome/telefone; não fazem fallback de título para
  `last_message`. O Pipeline Mobile fazia parte do mesmo componente de Pipeline
  e foi corrigido junto com o Kanban e o drawer.
