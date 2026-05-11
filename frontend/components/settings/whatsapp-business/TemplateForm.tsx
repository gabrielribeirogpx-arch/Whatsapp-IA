import { TemplateCategoryEnum } from '@/lib/whatsappEnums';

const input = 'premium-input w-full';

export default function TemplateForm({ form, setForm, onSubmit, loading, error }: { form: any; setForm: any; onSubmit: any; loading: boolean; error: string }) {
  return <form onSubmit={onSubmit} className='settings-card rounded-2xl border border-[color:var(--surface-border)] bg-white/95 p-5 shadow-[0_14px_34px_-30px_rgba(15,23,42,0.85)] space-y-3'>
    <h3 className='text-sm font-semibold text-slate-900'>Novo template</h3>
    <div className='grid gap-3 md:grid-cols-2'>
      <label className='space-y-1 text-xs font-medium text-slate-600'><span>Nome técnico</span><input className={input} value={form.name} onChange={e => setForm((p: any) => ({ ...p, name: e.target.value }))} placeholder='confirmacao_pedido_v1' /></label>
      <label className='space-y-1 text-xs font-medium text-slate-600'><span>Categoria</span><select className={input} value={form.category} onChange={e => setForm((p: any) => ({ ...p, category: e.target.value }))}>{Object.values(TemplateCategoryEnum).map(v => <option key={v} value={v}>{v}</option>)}</select></label>
    </div>
    <label className='space-y-1 text-xs font-medium text-slate-600 block'><span>Body</span><textarea className={`${input} min-h-24`} value={form.body_text} onChange={e => setForm((p: any) => ({ ...p, body_text: e.target.value }))} placeholder='Olá {{1}}, seu pedido {{2}} saiu para entrega.' /></label>
    <p className='text-xs text-slate-500'>Use variáveis sequenciais como {"{{1}}"}, {"{{2}}"}.</p>
    {error && <div className='rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700'>{error}</div>}
    <button disabled={loading} className='primary-button disabled:opacity-60'>{loading ? 'Criando...' : 'Novo template'}</button>
  </form>;
}
