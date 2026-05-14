export function getWhatsappWindowStatus(lastInteractionAt?: string | null): string {
  const timestamp = lastInteractionAt ? new Date(lastInteractionAt).getTime() : Number.NaN;

  if (Number.isNaN(timestamp)) {
    return 'Fora da janela de 24h';
  }

  const elapsedMs = Date.now() - timestamp;

  if (elapsedMs < 5 * 60 * 1000) {
    return 'Ativo recentemente';
  }

  if (elapsedMs < 24 * 60 * 60 * 1000) {
    return 'Janela de atendimento ativa';
  }

  return 'Fora da janela de 24h';
}
