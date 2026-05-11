import { useMemo, useRef } from 'react';
import { TemplateCategoryEnum } from '@/lib/whatsappEnums';
import VariablePicker from './VariablePicker';
import { friendlyToMeta, renderExample } from '@/lib/templateVariableMapper';

const input = 'premium-input w-full';

export default function TemplateForm({ form, setForm, onSubmit, loading, error }: { form: any; setForm: any; onSubmit: any; loading: boolean; error: string }) {
  const ref = useRef<HTMLTextAreaElement | null>(null);
  const mapped = useMemo(() => friendlyToMeta(form.friendly_body_text || ''), [form.friendly_body_text]);
  const preview = useMemo(() => renderExample(mapped.bodyText, mapped.variables), [mapped.bodyText, mapped.variables]);

  function insertAtCursor(label: string) {
    const token = `{${label}}`;
    const textarea = ref.current;
    if (!textarea) {
      setForm((p: any) => ({ ...p, friendly_body_text: `${p.friendly_body_text || ''}${token}` }));
      return;
    }
    const start = textarea.selectionStart ?? (form.friendly_body_text || '').length;
    const end = textarea.selectionEnd ?? start;
    const text = form.friendly_body_text || '';
    const next = `${text.slice(0, start)}${token}${text.slice(end)}`;
    setForm((p: any) => ({ ...p, friendly_body_text: next }));
  }

  return <form onSubmit={onSubmit} className='settings-card w-full min-w-0 space-y-4 rounded-2xl border border-[color:var(--surface-border)] bg-white/95 p-5 shadow-[0_14px_34px_-30px_rgba(15,23,42,0.85)]'>
    <h3 className='text-sm font-semibold text-slate-900'>Novo template</h3>
    <div className='grid gap-3 md:grid-cols-2 xl:grid-cols-3'>
      <label className='space-y-1 text-xs font-medium text-slate-600'><span>Nome técnico</span><input className={input} value={form.name} onChange={e => setForm((p: any) => ({ ...p, name: e.target.value }))} placeholder='confirmacao_pedido_v1' /></label>
      <label className='space-y-1 text-xs font-medium text-slate-600'><span>Categoria</span><select className={input} value={form.category} onChange={e => setForm((p: any) => ({ ...p, category: e.target.value }))}>{Object.values(TemplateCategoryEnum).map(v => <option key={v} value={v}>{v}</option>)}</select></label>
    </div>
    <div className='flex items-center justify-between'><span className='text-xs font-medium text-slate-600'>Body</span><VariablePicker onInsert={insertAtCursor} /></div>
    <textarea ref={ref} className={`${input} min-h-24 xl:min-h-28`} value={form.friendly_body_text || ''} onChange={e => setForm((p: any) => ({ ...p, friendly_body_text: e.target.value }))} placeholder='Olá {Primeiro nome}, seu pedido {Número do pedido} saiu para entrega.' />
    <div className='rounded-xl border border-slate-200 bg-slate-50 p-4 text-xs text-slate-600 space-y-2 xl:text-sm'>
      <p><span className='font-semibold text-slate-700'>Preview com exemplos:</span> {preview || 'Mensagem do template...'}</p>
      <p><span className='font-semibold text-slate-700'>Formato enviado para Meta:</span> {mapped.bodyText || '-'}</p>
    </div>
    {error && <div className='rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700 whitespace-pre-line'>{error}</div>}
    <button disabled={loading} className='primary-button disabled:opacity-60'>{loading ? 'Criando...' : 'Novo template'}</button>
  </form>;
}
