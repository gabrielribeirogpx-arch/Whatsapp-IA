type KPICardProps = {
  label: string;
  value: string | number;
  trend?: string;
  unit?: string;
};

function getTrendColor(trend: string) {
  const normalized = trend.toLowerCase();
  if (normalized.includes('↓') || normalized.includes('-')) return 'var(--color-text-danger)';
  return 'var(--color-text-success)';
}

export default function KPICard({ label, value, trend, unit }: KPICardProps) {
  return (
    <article
      style={{
        background: 'var(--color-background-secondary)',
        padding: '1rem',
        borderRadius: 'var(--border-radius-md)'
      }}
    >
      <p style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.5px', color: 'var(--color-text-secondary)', margin: '0 0 10px' }}>
        {label}
      </p>
      <p style={{ fontSize: 32, fontWeight: 500, color: 'var(--color-text-primary)', margin: 0 }}>{value}</p>
      {unit && <p style={{ fontSize: 11, color: 'var(--color-text-secondary)', margin: '6px 0 0' }}>{unit}</p>}
      {trend && <p style={{ fontSize: 11, color: getTrendColor(trend), margin: '6px 0 0' }}>{trend}</p>}
    </article>
  );
}
