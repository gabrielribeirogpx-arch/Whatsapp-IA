export const ONLINE_THRESHOLD_MS = 2 * 60 * 1000;
export const RECENTLY_ACTIVE_THRESHOLD_MS = 15 * 60 * 1000;
export const STALE_THRESHOLD_MS = 24 * 60 * 60 * 1000;
export const TYPING_TIMEOUT_MS = 8 * 1000;

export type PresenceState = 'online' | 'recently_active' | 'offline' | 'stale';

export function toTimestamp(value?: string | Date | null): number | null {
  if (!value) return null;
  const ts = value instanceof Date ? value.getTime() : new Date(value).getTime();
  return Number.isFinite(ts) ? ts : null;
}

export function derivePresenceState(lastInteractionAt?: string | Date | null, now = Date.now()): PresenceState {
  const ts = toTimestamp(lastInteractionAt);
  if (!ts) return 'offline';
  const elapsed = Math.max(0, now - ts);
  if (elapsed <= ONLINE_THRESHOLD_MS) return 'online';
  if (elapsed <= RECENTLY_ACTIVE_THRESHOLD_MS) return 'recently_active';
  if (elapsed <= STALE_THRESHOLD_MS) return 'offline';
  return 'stale';
}

export function getPresenceLabel(state: PresenceState): string {
  if (state === 'online') return 'online';
  if (state === 'recently_active') return 'ativo recentemente';
  if (state === 'stale') return 'inativo';
  return 'offline';
}

export function isTypingActive(lastTypingEventAt?: number | null, now = Date.now()): boolean {
  if (!lastTypingEventAt) return false;
  return now - lastTypingEventAt <= TYPING_TIMEOUT_MS;
}
