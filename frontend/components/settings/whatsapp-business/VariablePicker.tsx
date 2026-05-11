import { useMemo, useState } from 'react';
import { Search } from 'lucide-react';
import { TEMPLATE_VARIABLES } from '@/lib/templateVariableMapper';

export default function VariablePicker({ onInsert }: { onInsert: (label: string) => void }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');

  const filtered = useMemo(() => TEMPLATE_VARIABLES.filter((item) => {
    const q = query.trim().toLowerCase();
    if (!q) return true;
    return item.label.toLowerCase().includes(q) || item.key.toLowerCase().includes(q) || item.description.toLowerCase().includes(q);
  }), [query]);

  const grouped = useMemo(() => filtered.reduce((acc, item) => {
    if (!acc[item.category]) acc[item.category] = [];
    acc[item.category].push(item);
    return acc;
  }, {} as Record<string, typeof TEMPLATE_VARIABLES>), [filtered]);

  return <div className='relative'>
    <button type='button' className='secondary-button border border-slate-300 bg-white hover:bg-slate-100' onClick={() => setOpen(v => !v)}>Inserir variável</button>
    {open && <div className='absolute z-30 mt-2 w-[min(38rem,92vw)] rounded-2xl border border-slate-200 bg-white p-3 shadow-2xl'>
      <label className='mb-2 flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-500'>
        <Search size={14} />
        <input value={query} onChange={e => setQuery(e.target.value)} placeholder='Buscar variável...' className='w-full bg-transparent text-sm text-slate-700 outline-none' />
      </label>
      <div className='max-h-80 space-y-3 overflow-auto pr-1'>
        {Object.entries(grouped).map(([category, items]) => <div key={category}>
          <p className='mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500'>{category}</p>
          <div className='flex flex-wrap gap-2'>
            {items.map(item => <button key={item.key} type='button' onClick={() => { onInsert(item.label); setOpen(false); }} className='rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs text-emerald-800 hover:bg-emerald-100'>
              {item.label} <span className='text-emerald-600'>· {item.example}</span>
            </button>)}
          </div>
        </div>)}
        {filtered.length === 0 && <p className='text-xs text-slate-500'>Nenhuma variável encontrada.</p>}
      </div>
    </div>}
  </div>;
}
