import { ReactNode } from 'react';

type HeaderProps = {
  title: string;
  subtitle: string;
  actions?: ReactNode;
};

export default function Header({ title, subtitle, actions }: HeaderProps) {
  return (
    <header
      style={{
        padding: '2rem',
        borderBottom: '0.5px solid var(--color-border-tertiary)',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'flex-start',
        gap: '12px'
      }}
    >
      <div>
        <h1 style={{ fontSize: 22, fontWeight: 500, margin: 0 }}>{title}</h1>
        <p style={{ fontSize: 13, color: 'var(--color-text-secondary)', margin: '6px 0 0' }}>{subtitle}</p>
      </div>
      {actions}
    </header>
  );
}
