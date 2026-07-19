'use client';

import { ReactNode, useEffect, useState } from 'react';

type Props<T> = {
  data: T[];
  loading?: boolean;
  error?: ReactNode;
  desktopView: ReactNode;
  mobileView: (item: T, index: number) => ReactNode;
  emptyState?: ReactNode;
  loadingState?: ReactNode;
  pagination?: ReactNode;
  className?: string;
};

/**
 * Selects one presentation for one already-loaded collection. Fetching, filters,
 * permissions and pagination deliberately stay in the calling page.
 */
export function ResponsiveDataView<T>({
  data,
  loading = false,
  error,
  desktopView,
  mobileView,
  emptyState,
  loadingState,
  pagination,
  className = '',
}: Props<T>) {
  const [isCompact, setIsCompact] = useState<boolean | null>(null);

  useEffect(() => {
    const media = window.matchMedia('(max-width: 1023px)');
    const update = () => setIsCompact(media.matches);
    update();
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);

  if (loading) return <>{loadingState ?? <div role="status" aria-live="polite">Carregando…</div>}</>;
  if (error) return <>{error}</>;
  if (!data.length) return <>{emptyState ?? <p className="text-sm text-slate-500">Nenhum resultado encontrado.</p>}</>;

  // During SSR use the desktop table; after hydration only one costly view exists.
  const content = isCompact ? <div className="responsive-data-mobile">{data.map(mobileView)}</div> : desktopView;
  return <div className={`min-w-0 ${className}`}>{content}{pagination ? <div className="responsive-data-pagination">{pagination}</div> : null}</div>;
}
