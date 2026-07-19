import type { ReactNode } from 'react';

/** Shared structure, while each domain supplies its own meaningful fields/actions. */
export function MobileListCard({ title, subtitle, status, meta, action, children }: { title: ReactNode; subtitle?: ReactNode; status?: ReactNode; meta?: ReactNode; action?: ReactNode; children?: ReactNode }) {
  return <article className="mobile-list-card">
    <div className="mobile-list-card__header"><div className="min-w-0"><h2>{title}</h2>{subtitle ? <p>{subtitle}</p> : null}</div>{status}</div>
    {children ? <div className="mobile-list-card__body">{children}</div> : null}
    {(meta || action) ? <footer><div className="min-w-0">{meta}</div>{action}</footer> : null}
  </article>;
}
