'use client';

import { ReactNode, useEffect } from 'react';
import { X } from 'lucide-react';

type DashboardInsightPanelProps = {
  open: boolean;
  title: string;
  description?: string;
  loading?: boolean;
  onClose: () => void;
  children: ReactNode;
};

export default function DashboardInsightPanel({ open, title, description, loading = false, onClose, children }: DashboardInsightPanelProps) {
  useEffect(() => {
    if (!open) return;
    const original = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = original;
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [open, onClose]);

  return (
    <>
      <div
        onClick={onClose}
        className={`fixed inset-0 z-[110] bg-slate-950/35 backdrop-blur-sm transition-opacity duration-300 ${open ? 'pointer-events-auto opacity-100' : 'pointer-events-none opacity-0'}`}
      />

      <aside
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`fixed right-0 top-0 z-[120] h-full w-full max-w-[720px] border-l border-emerald-100/70 bg-gradient-to-b from-white via-emerald-50/45 to-white shadow-[-16px_0_48px_rgba(15,23,42,0.16)] transition-transform duration-300 ease-out ${open ? 'translate-x-0' : 'translate-x-full'}`}
      >
        <div className="flex h-full flex-col">
          <header className="sticky top-0 z-10 border-b border-emerald-100 bg-white/80 px-5 py-4 backdrop-blur-xl md:px-6">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold text-slate-900 md:text-xl">{title}</h2>
                {description ? <p className="mt-1 text-sm text-slate-500">{description}</p> : null}
              </div>
              <button
                type="button"
                aria-label="Fechar painel"
                onClick={onClose}
                className="rounded-xl border border-slate-200 bg-white p-2 text-slate-500 transition hover:border-emerald-200 hover:text-emerald-700"
              >
                <X size={18} />
              </button>
            </div>
          </header>

          <div className="flex-1 overflow-y-auto px-5 py-5 md:px-6 md:py-6">
            {loading ? (
              <div className="space-y-3">
                {[1, 2, 3, 4, 5].map((item) => (
                  <div key={item} className="h-20 animate-pulse rounded-2xl border border-emerald-100 bg-white/80" />
                ))}
              </div>
            ) : (
              children
            )}
          </div>
        </div>
      </aside>
    </>
  );
}
