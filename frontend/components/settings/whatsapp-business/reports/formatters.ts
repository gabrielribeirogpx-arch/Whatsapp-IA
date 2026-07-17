export function formatInteger(value?: number | null) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 0 }).format(value);
}

export function formatCompact(value?: number | null) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  const abs = Math.abs(value);
  if (abs >= 1_000_000) return `${new Intl.NumberFormat('pt-BR', { maximumFractionDigits: abs >= 10_000_000 ? 0 : 1 }).format(value / 1_000_000)} mi`;
  if (abs >= 10_000) return `${new Intl.NumberFormat('pt-BR', { maximumFractionDigits: abs >= 100_000 ? 0 : 1 }).format(value / 1_000)} mil`;
  return formatInteger(value);
}

export function formatPercent(value?: number | null, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return `${value.toLocaleString('pt-BR', { minimumFractionDigits: value % 1 === 0 ? 0 : digits, maximumFractionDigits: digits })}%`;
}

export function formatDuration(seconds?: number | null) {
  if (!seconds && seconds !== 0) return '—';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  return `${Math.floor(seconds / 3600)}h ${Math.round((seconds % 3600) / 60)}min`;
}

export function formatDateTime(value?: string | null) {
  if (!value) return '—';
  return new Date(value).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' });
}
