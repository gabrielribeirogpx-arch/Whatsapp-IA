export type EventMeta = { label: string; description: string; tone: 'success' | 'danger' | 'warning' | 'info' | 'neutral' };

const events: Record<string, EventMeta> = {
  WEBHOOK_RECEIVED: { label: 'Webhook recebido', description: 'Evento recebido pelo canal.', tone: 'info' },
  MESSAGE_SENT: { label: 'Mensagem enviada', description: 'Mensagem entregue ao provedor.', tone: 'success' },
  MESSAGE_FAILED: { label: 'Falha ao enviar mensagem', description: 'O envio não foi concluído.', tone: 'danger' },
  EXECUTION_FAILED: { label: 'Execução com falha', description: 'O fluxo terminou com erro.', tone: 'danger' },
  NODE_FAILED: { label: 'Nó com falha', description: 'Uma etapa do fluxo falhou.', tone: 'danger' },
  RETRY_SCHEDULED: { label: 'Nova tentativa agendada', description: 'A operação será tentada novamente.', tone: 'warning' },
  AI_AGENT_STARTED: { label: 'Agente de IA iniciado', description: 'O agente iniciou o processamento.', tone: 'info' },
  AI_AGENT_FINISHED: { label: 'Agente de IA concluído', description: 'O agente concluiu o processamento.', tone: 'success' },
  MCP_TOOL_CALLED: { label: 'Ferramenta MCP executada', description: 'Uma ferramenta MCP foi chamada.', tone: 'info' },
};

export function eventMeta(eventType: string): EventMeta {
  return events[eventType] ?? {
    label: eventType.replace(/[_-]+/g, ' ').toLocaleLowerCase('pt-BR').replace(/(^|\s)\S/g, (letter) => letter.toLocaleUpperCase('pt-BR')),
    description: 'Evento operacional registrado.', tone: 'neutral',
  };
}

export function eventStatus(eventType: string) {
  if (eventType.includes('FAILED') || eventType === 'ERROR') return { label: 'Erro', tone: 'danger' as const };
  if (eventType.includes('RETRY')) return { label: 'Retry', tone: 'warning' as const };
  return { label: 'Registrado', tone: 'success' as const };
}
