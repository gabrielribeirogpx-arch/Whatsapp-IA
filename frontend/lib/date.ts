const SAO_PAULO_TZ = 'America/Sao_Paulo';

function toDate(value: unknown): Date | null {
  if (!value) return null;
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value;

  if (typeof value === 'number') {
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? null : d;
  }

  if (typeof value === 'string') {
    const raw = value.trim();
    if (!raw) return null;

    const normalized = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(raw)
      ? `${raw}Z`
      : raw;

    const d = new Date(normalized);
    return Number.isNaN(d.getTime()) ? null : d;
  }

  return null;
}

export function formatDateTimeBR(value: unknown): string {
  const date = toDate(value);
  if (!date) return '-';

  return new Intl.DateTimeFormat('pt-BR', {
    timeZone: SAO_PAULO_TZ,
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

export function formatTimeBR(value: unknown): string {
  const date = toDate(value);
  if (!date) return '-';

  return new Intl.DateTimeFormat('pt-BR', {
    timeZone: SAO_PAULO_TZ,
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}
