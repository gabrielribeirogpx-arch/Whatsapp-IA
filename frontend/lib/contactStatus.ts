import { derivePresenceState } from './presence';

export function getWhatsappWindowStatus(lastInteractionAt?: string | null): string {
  const presence = derivePresenceState(lastInteractionAt);

  if (presence === 'online' || presence === 'recently_active') {
    return 'Ativo recentemente';
  }

  if (presence === 'offline') {
    return 'Janela de atendimento ativa';
  }

  return 'Fora da janela de 24h';
}
