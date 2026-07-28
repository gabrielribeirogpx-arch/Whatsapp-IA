# Investigação: respostas de botões no webhook do provedor

## Conclusão

O evento `button_reply` deixa de existir somente quando o provedor está
registrado no endpoint legado `POST /api/webhook`. Esse handler aceitava apenas
`message.type == "text"`; para qualquer outro tipo, inclusive `interactive`,
substituía o conteúdo por uma string vazia e executava diretamente o fluxo
legado. Assim, o envelope original nunca chegava ao normalizador nem ao worker.

O endpoint canônico `POST /webhook` não descarta mensagens interativas. Ele
encaminha o envelope integral à fila, e `normalize_meta_message` reconhece
explicitamente `interactive.button_reply` e `interactive.list_reply`,
preservando `id` e `title`.

## Comparação de contrato

| Questão | Resultado |
| --- | --- |
| O provedor converte `button_reply` em `text`? | Não no contrato Meta recebido pelo endpoint canônico. A conversão para texto ocorre internamente no normalizador e usa o `id` estável, sem perder os metadados interativos. |
| O webhook descarta mensagens `interactive`? | Sim, apenas o handler legado `POST /api/webhook` descartava semanticamente o tipo ao produzir texto vazio. O handler canônico não descarta. |
| Existe endpoint específico para respostas interativas? | Não. A Meta entrega texto e respostas interativas na mesma assinatura de webhook. `/webhook`, `/api/webhook/whatsapp` e `/api/webhook` são rotas de gerações/compatibilidade diferentes, não rotas por tipo de mensagem. |
| O payload difere do oficial da Meta? | O pipeline implementado e os testes usam o envelope oficial `entry[].changes[].value.messages[]`, com `type: interactive` e `interactive.type: button_reply`. Não há adaptador de um formato proprietário WazzaAPI no backend. |

## Correção na camada do provedor

`POST /api/webhook` agora delega ao mesmo ingresso usado pelas rotas canônica e
de compatibilidade. Isso preserva o payload bruto até o worker e elimina o
desvio síncrono que aceitava somente texto. Runtime V2 e ChoiceResolver não
foram alterados.
