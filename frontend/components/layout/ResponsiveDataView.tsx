import { ReactNode } from 'react';

type Props<T> = { items: T[]; desktop: ReactNode; mobile: (item: T) => ReactNode; empty?: ReactNode; className?: string };

/** Keeps a desktop data view and purpose-built mobile cards backed by the same data. */
export function ResponsiveDataView<T>({ items, desktop, mobile, empty, className = '' }: Props<T>) {
  if (!items.length) return <>{empty ?? <p className="text-sm text-slate-500">Nenhum resultado encontrado.</p>}</>;
  return <><div className={`responsive-data-desktop ${className}`}>{desktop}</div><div className="responsive-data-mobile">{items.map(mobile)}</div></>;
}
