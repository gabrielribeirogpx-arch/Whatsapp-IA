type Status = 'success' | 'warning' | 'danger';

type StatusBadgeProps = {
  status: Status;
  label: string;
};

const statusColorMap: Record<Status, string> = {
  success: '#16A34A',
  warning: '#D97706',
  danger: '#DC2626'
};

export default function StatusBadge({ status, label }: StatusBadgeProps) {
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        background: `var(--color-background-${status})`,
        color: `var(--color-text-${status})`,
        padding: '3px 10px',
        borderRadius: 'var(--border-radius-md)',
        fontSize: 12,
        fontWeight: 500
      }}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: '999px',
          background: statusColorMap[status],
          display: 'inline-block'
        }}
      />
      {label}
    </span>
  );
}
