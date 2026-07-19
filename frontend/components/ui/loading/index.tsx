import type { ReactNode } from 'react';

export function Skeleton({ className = '' }: { className?: string }) {
  return <span aria-hidden="true" className={`wazza-skeleton ${className}`} />;
}

function Lines({ count = 2 }: { count?: number }) {
  return <div className="space-y-2">{Array.from({ length: count }, (_, index) => <Skeleton key={index} className={index === count - 1 ? 'w-2/3' : 'w-full'} />)}</div>;
}

export function WazzaAnimatedLogo() {
  return <div className="wazza-logo-loader" aria-hidden="true"><span className="wazza-logo-loader__wave" /><img src="/Logo.svg" alt="" /></div>;
}

export function GlobalPageLoader({ label = 'Preparando sua experiência' }: { label?: string }) {
  return <section className="wazza-global-loader" aria-busy="true" aria-live="polite" role="status"><WazzaAnimatedLogo /><span className="sr-only">{label}</span><p>{label}</p><div className="wazza-loader-dots" aria-hidden="true"><i /><i /><i /></div></section>;
}

export function PageSkeleton({ children }: { children?: ReactNode }) {
  return <section className="wazza-page-skeleton wazza-content-enter" aria-hidden="true">{children ?? <><Skeleton className="h-8 w-48" /><Skeleton className="mt-3 h-4 w-80 max-w-full" /><Skeleton className="mt-8 h-12 w-full" /><div className="mt-5 grid gap-4 md:grid-cols-3"><CardSkeleton /><CardSkeleton /><CardSkeleton /></div></>}</section>;
}

export function CardSkeleton() { return <div className="wazza-skeleton-card"><Skeleton className="h-4 w-2/5" /><Skeleton className="mt-4 h-8 w-1/2" /><Skeleton className="mt-5 h-3 w-full" /></div>; }

export function DashboardSkeleton() { return <PageSkeleton><div className="flex flex-wrap items-end justify-between gap-4"><div><Skeleton className="h-8 w-52" /><Skeleton className="mt-3 h-4 w-72 max-w-full" /></div><Skeleton className="h-10 w-40" /></div><div className="mt-7 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{Array.from({ length: 4 }, (_, i) => <CardSkeleton key={i} />)}</div><div className="mt-5 grid gap-5 xl:grid-cols-[1.6fr_1fr]"><div className="wazza-skeleton-card h-80"><Skeleton className="h-5 w-36" /><Skeleton className="mt-6 h-56 w-full" /></div><div className="wazza-skeleton-card"><Skeleton className="h-5 w-32" /><div className="mt-6 space-y-5">{Array.from({ length: 4 }, (_, i) => <div key={i} className="flex gap-3"><Skeleton className="h-9 w-9 rounded-full" /><Lines /></div>)}</div></div></div></PageSkeleton>; }

export function TableSkeleton({ rows = 6, columns = 5, showHeader = true, showToolbar = true, showPagination = true }: { rows?: number; columns?: number; showHeader?: boolean; showToolbar?: boolean; showPagination?: boolean }) { return <section className="wazza-table-skeleton" aria-hidden="true">{showToolbar && <div className="mb-4 flex justify-between gap-3"><Skeleton className="h-10 w-64 max-w-[60%]" /><Skeleton className="h-10 w-28" /></div>}<div className="overflow-hidden rounded-2xl border border-[var(--surface-border)] bg-[var(--wazza-skeleton-surface)]">{showHeader && <div className="grid gap-5 border-b border-[var(--surface-border)] p-4" style={{ gridTemplateColumns: `repeat(${columns}, minmax(80px, 1fr))` }}>{Array.from({ length: columns }, (_, i) => <Skeleton key={i} className="h-3" />)}</div>}<div>{Array.from({ length: rows }, (_, row) => <div key={row} className="grid gap-5 border-b border-[var(--surface-border)] p-4 last:border-0" style={{ gridTemplateColumns: `repeat(${columns}, minmax(80px, 1fr))` }}>{Array.from({ length: columns }, (_, col) => <Skeleton key={col} className={`h-4 ${col === 0 ? 'w-4/5' : col === columns - 1 ? 'w-1/2' : ''}`} />)}</div>)}</div></div>{showPagination && <div className="mt-4 flex justify-between"><Skeleton className="h-4 w-32" /><Skeleton className="h-8 w-24" /></div>}</section>; }

export function ListSkeleton({ items = 6 }: { items?: number }) { return <div className="divide-y divide-[var(--surface-border)] rounded-2xl border border-[var(--surface-border)] bg-[var(--wazza-skeleton-surface)]" aria-hidden="true">{Array.from({ length: items }, (_, i) => <div key={i} className="flex items-center gap-3 p-4"><Skeleton className="h-11 w-11 shrink-0 rounded-full" /><div className="min-w-0 flex-1"><Lines /></div><Skeleton className="h-3 w-10" /></div>)}</div>; }

export function FormSkeleton() { return <PageSkeleton><Skeleton className="mt-7 h-7 w-48" /><div className="mt-5 max-w-3xl space-y-6 rounded-2xl border border-[var(--surface-border)] bg-[var(--wazza-skeleton-surface)] p-6">{Array.from({ length: 4 }, (_, i) => <div key={i}><Skeleton className="h-3 w-28" /><Skeleton className="mt-2 h-11 w-full" /></div>)}<Skeleton className="h-10 w-32" /></div></PageSkeleton>; }

export function InboxSkeleton() { return <div className="grid min-h-[calc(100vh-7rem)] grid-cols-1 overflow-hidden rounded-2xl border border-[var(--surface-border)] bg-[var(--wazza-skeleton-surface)] lg:grid-cols-[300px_1fr_280px]" aria-hidden="true"><ListSkeleton items={7} /><div className="border-y border-[var(--surface-border)] p-5 lg:border-x lg:border-y-0"><Skeleton className="h-12 w-full" /><div className="mt-8 space-y-5">{Array.from({ length: 7 }, (_, i) => <Skeleton key={i} className={`h-12 ${i % 2 ? 'ml-auto w-2/3' : 'w-3/5'}`} />)}</div></div><div className="hidden p-5 lg:block"><Skeleton className="h-6 w-32" /><div className="mt-5 space-y-4"><Lines count={3} /><Lines count={3} /></div></div></div>; }

export function KanbanSkeleton() { return <div className="flex gap-4 overflow-hidden" aria-hidden="true">{Array.from({ length: 4 }, (_, col) => <div key={col} className="min-w-[260px] flex-1 rounded-2xl bg-[var(--wazza-skeleton-surface)] p-4"><div className="flex justify-between"><Skeleton className="h-4 w-28" /><Skeleton className="h-5 w-5 rounded-full" /></div><div className="mt-4 space-y-3">{Array.from({ length: 4 }, (_, card) => <div key={card} className="wazza-skeleton-card"><Lines count={card % 2 ? 3 : 2} /></div>)}</div></div>)}</div>; }

export function FlowBuilderSkeleton() { return <div className="relative min-h-screen overflow-hidden bg-[var(--wazza-skeleton-surface)] p-6" aria-hidden="true"><div className="flex justify-between"><Skeleton className="h-12 w-72" /><Skeleton className="h-12 w-44" /></div><div className="relative mt-8 h-[calc(100vh-9rem)] rounded-2xl border border-[var(--surface-border)] bg-[radial-gradient(var(--surface-border)_1px,transparent_1px)] [background-size:20px_20px]"><Skeleton className="absolute left-[15%] top-[18%] h-28 w-52" /><Skeleton className="absolute left-[47%] top-[40%] h-32 w-56" /><Skeleton className="absolute right-[12%] top-[20%] h-24 w-48" /></div></div>; }

export function InlineLoader({ label = 'Atualizando' }: { label?: string }) { return <span className="wazza-inline-loader" role="status" aria-label={label}><i aria-hidden="true" /><span className="sr-only">{label}</span></span>; }
export function ButtonLoader({ label = 'Salvando' }: { label?: string }) { return <span className="inline-flex items-center gap-2" role="status"><InlineLoader label={label} /><span>{label}</span></span>; }
