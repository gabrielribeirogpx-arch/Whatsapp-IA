'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';

export type DateRange = { startDate: string; endDate: string };

type Props = {
  initialRange: DateRange | null;
  onApply: (range: DateRange) => void;
  onCancel: () => void;
};

const weekDays = ['D', 'S', 'T', 'Q', 'Q', 'S', 'S'];

function toIsoDate(date: Date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function fromIsoDate(value: string) {
  const [year, month, day] = value.split('-').map(Number);
  return new Date(year, month - 1, day);
}

export default function DateRangePicker({ initialRange, onApply, onCancel }: Props) {
  const today = useMemo(() => new Date(), []);
  const [draft, setDraft] = useState<DateRange>(() => initialRange ?? { startDate: '', endDate: '' });
  const [visibleMonth, setVisibleMonth] = useState(() => {
    const basis = initialRange?.startDate ? fromIsoDate(initialRange.startDate) : today;
    return new Date(basis.getFullYear(), basis.getMonth(), 1);
  });
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handlePointerDown = (event: PointerEvent) => {
      if (!panelRef.current?.contains(event.target as Node)) onCancel();
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onCancel();
    };
    document.addEventListener('pointerdown', handlePointerDown);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [onCancel]);

  const firstWeekday = visibleMonth.getDay();
  const daysInMonth = new Date(visibleMonth.getFullYear(), visibleMonth.getMonth() + 1, 0).getDate();
  const days = Array.from({ length: firstWeekday + daysInMonth }, (_, index) =>
    index < firstWeekday ? null : new Date(visibleMonth.getFullYear(), visibleMonth.getMonth(), index - firstWeekday + 1),
  );

  function selectDay(date: Date) {
    const selected = toIsoDate(date);
    if (!draft.startDate || draft.endDate) {
      setDraft({ startDate: selected, endDate: '' });
    } else if (selected < draft.startDate) {
      setDraft({ startDate: selected, endDate: draft.startDate });
    } else {
      setDraft({ ...draft, endDate: selected });
    }
  }

  function updateDate(key: keyof DateRange, value: string) {
    setDraft((current) => {
      const next = { ...current, [key]: value };
      if (next.startDate && next.endDate && next.startDate > next.endDate) {
        if (key === 'startDate') next.endDate = value;
        else next.startDate = value;
      }
      return next;
    });
    if (value) {
      const date = fromIsoDate(value);
      setVisibleMonth(new Date(date.getFullYear(), date.getMonth(), 1));
    }
  }

  return (
    <div
      ref={panelRef}
      role="dialog"
      aria-label="Selecionar período personalizado"
      className="absolute right-0 top-12 z-50 w-[min(22rem,calc(100vw-2rem))] rounded-xl border border-slate-200 bg-white p-4 shadow-[0_16px_40px_rgba(15,23,42,0.16)]"
    >
      <div className="grid grid-cols-2 gap-3">
        <label className="text-xs font-medium text-slate-600">Data inicial
          <input type="date" value={draft.startDate} max={draft.endDate || undefined} onChange={(event) => updateDate('startDate', event.target.value)} className="mt-1 h-9 w-full rounded-lg border border-slate-200 px-2 text-xs outline-none focus-visible:border-emerald-500 focus-visible:ring-2 focus-visible:ring-emerald-100" />
        </label>
        <label className="text-xs font-medium text-slate-600">Data final
          <input type="date" value={draft.endDate} min={draft.startDate || undefined} onChange={(event) => updateDate('endDate', event.target.value)} className="mt-1 h-9 w-full rounded-lg border border-slate-200 px-2 text-xs outline-none focus-visible:border-emerald-500 focus-visible:ring-2 focus-visible:ring-emerald-100" />
        </label>
      </div>

      <div className="mt-4 flex items-center justify-between">
        <button type="button" onClick={() => setVisibleMonth(new Date(visibleMonth.getFullYear(), visibleMonth.getMonth() - 1, 1))} aria-label="Mês anterior" className="rounded-md p-1.5 text-slate-500 hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-200"><ChevronLeft size={17} /></button>
        <strong className="text-sm font-semibold capitalize text-slate-800">{visibleMonth.toLocaleDateString('pt-BR', { month: 'long', year: 'numeric' })}</strong>
        <button type="button" onClick={() => setVisibleMonth(new Date(visibleMonth.getFullYear(), visibleMonth.getMonth() + 1, 1))} aria-label="Próximo mês" className="rounded-md p-1.5 text-slate-500 hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-200"><ChevronRight size={17} /></button>
      </div>
      <div className="mt-2 grid grid-cols-7 text-center text-[11px] font-medium text-slate-400">{weekDays.map((day, index) => <span key={`${day}-${index}`}>{day}</span>)}</div>
      <div className="mt-1 grid grid-cols-7 gap-y-0.5">
        {days.map((date, index) => {
          if (!date) return <span key={`empty-${index}`} />;
          const iso = toIsoDate(date);
          const isEdge = iso === draft.startDate || iso === draft.endDate;
          const isInside = Boolean(draft.startDate && draft.endDate && iso > draft.startDate && iso < draft.endDate);
          return <button key={iso} type="button" onClick={() => selectDay(date)} aria-pressed={isEdge || isInside} aria-label={date.toLocaleDateString('pt-BR')} className={`h-8 rounded-md text-xs transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300 ${isEdge ? 'bg-emerald-600 font-semibold text-white' : isInside ? 'bg-emerald-100 text-emerald-800' : 'text-slate-700 hover:bg-slate-100'}`}>{date.getDate()}</button>;
        })}
      </div>

      <div className="mt-4 flex justify-end gap-2 border-t border-slate-100 pt-3">
        <button type="button" onClick={onCancel} className="h-9 rounded-lg px-3 text-xs font-semibold text-slate-600 hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-200">Cancelar</button>
        <button type="button" disabled={!draft.startDate || !draft.endDate} onClick={() => onApply(draft)} className="h-9 rounded-lg bg-emerald-600 px-3 text-xs font-semibold text-white hover:bg-emerald-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300 disabled:cursor-not-allowed disabled:opacity-50">Aplicar</button>
      </div>
    </div>
  );
}
