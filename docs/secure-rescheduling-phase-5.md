# Fase 5 — remarcação segura de agendamentos

## Diagnóstico e decisão

O template comercial **Clinicas - Agenda Automática** não está versionado neste
repositório; a busca pelo nome e pelas variáveis do ramo não encontrou seed ou
snapshot editável. Nenhum fluxo persistido deve ser alterado automaticamente.

`current_appointment_date` como texto não produz os três argumentos temporais da
busca. A solução canônica é trocar apenas o tipo desse DataCollection para
`appointment_lookup_period` e, preferencialmente, renomear a variável para
`current_appointment_period`. Esse tipo reutiliza o resolvedor determinístico e a
política/timezone do tenant já usados por `appointment_period`: data simples gera
o dia local `[00:00, 00:00 do dia seguinte)`; manhã/tarde/noite preservam a
interseção com o horário comercial. Entrada ambígua é inválida, em vez de causar
uma busca ampla. A janela normal tem no máximo um dia, muito abaixo de 90 dias.

`reschedule_patient_name` é redundante para autorização e lookup. Pode continuar
por UX/CRM nesta fase, mas pode ser removido futuramente se não alimentar outra
finalidade. Nunca deve ser enviado à ferramenta como identidade.

## Configuração exata no Flow Builder

1. **DataCollection — consulta atual**
   - `variable_name`: `current_appointment_period`
   - `data_type`: `appointment_lookup_period`
   - prompt: `Em qual dia ou período está a consulta que você quer remarcar?`
   - configurar `invalid`, tentativas e `timeout` segundo a política comercial.
2. **MCP Tool — localizar consultas**
   - `tool_name`: `google_calendar_find_managed_appointments`
   - `arguments.start`: `{{current_appointment_period.window_start}}`
   - `arguments.end`: `{{current_appointment_period.window_end}}`
   - `arguments.timezone`: `{{current_appointment_period.timezone}}`
   - `output_variable`: `managed_appointments`
   - remover o node `google_calendar_list_events` deste ramo.
3. **Dynamic Choice — consulta a remarcar**
   - `options_variable`: `managed_appointments` (sem `result_path`)
   - `label_field`: `label`
   - `value_field`: `id`
   - `result_variable`: `event_to_reschedule`
   - ligar `empty` a: `Não encontrei um agendamento seu nesse período. Você pode informar outra data ou falar com nossa equipe.`
   - dessa mensagem, oferecer **Informar outra data** (retorna ao passo 1) e
     **Falar com atendente** (handoff). Não ligar `error` a esse caminho; encaminhar
     falha técnica/configuração ao fallback técnico ou atendente.
4. **DataCollection — novo horário**
   - manter `variable_name`: `new_appointment_period`
   - manter `data_type`: `appointment_period`.
5. **MCP Tool — disponibilidade**
   - `tool_name`: `google_calendar_check_availability`
   - `arguments.start`: `{{new_appointment_period.window_start}}`
   - `arguments.end`: `{{new_appointment_period.window_end}}`
   - `arguments.timezone`: `{{new_appointment_period.timezone}}`
   - `arguments.mode`: `{{new_appointment_period.mode}}`
   - `output_variable`: `new_availability`.
6. **Dynamic Choice — novo slot**
   - `options_variable`: `new_availability.appointments`
   - `label_field`: `label`; `value_field`: `id`
   - `result_variable`: `new_selected_slot`.
7. **MCP Tool — atualizar**
   - `tool_name`: `google_calendar_update_event`
   - `event_id`: `{{event_to_reschedule.id}}`
   - `start`: `{{new_selected_slot.start}}`
   - `end`: `{{new_selected_slot.end}}`
   - `timezone`: `{{new_selected_slot.timezone}}`
   - manter autorização explícita de escrita externa habilitada.

## Contratos e segurança auditados

`google_calendar_check_availability` aceita `start`/`end` (não
`window_start`/`window_end`); os nomes `window_*` pertencem somente ao objeto do
DataCollection. O Dynamic Choice materializa uma lista raiz e persiste o objeto
original completo selecionado.

`google_calendar_update_event` usa HTTP `PATCH`. Como o payload não inclui
`extendedProperties`, o PATCH preserva as propriedades privadas existentes. Porém,
o adapter ainda aceita qualquer `event_id` fornecido pelo flow. Classificação:
**PRECISA DE HARDENING SERVER-SIDE**. A próxima fase deve exigir `ToolContext`,
buscar/verificar o evento no calendário configurado e rejeitar update salvo quando
`asa_managed=true`, `asa_schema=appointment-v1` e `asa_patient_ref` corresponder à
referência opaca derivada do tenant/contact atuais. Até lá, a operação é segura
somente quando o template correto impede IDs manuais; o Flow Builder não constitui
uma fronteira de autorização.

Eventos legacy sem a metadata Asa permanecem deliberadamente fora da descoberta.
