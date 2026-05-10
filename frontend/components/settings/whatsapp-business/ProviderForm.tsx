import { ProviderTypeEnum } from '@/lib/whatsappEnums';

const input = 'w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm shadow-sm outline-none transition focus:border-emerald-400 focus:ring-4 focus:ring-emerald-500/10';

export default function ProviderForm({ form, setForm, onSubmit, loading }: { form: any; setForm: any; onSubmit: any; loading: boolean }) {
  return <form onSubmit={onSubmit} className='settings-card rounded-2xl border border-slate-200/80 bg-white/95 p-5 shadow-sm'>
    <div className='mb-4'><h3 className='text-sm font-semibold text-slate-900'>Nova conexão</h3><p className='text-xs text-slate-500'>Configure um provider sem alterar runtime atual.</p></div>
    <div className='grid gap-3 md:grid-cols-2'>
      <label className='space-y-1 text-xs font-medium text-slate-600'><span>Provider</span><select className={input} value={form.provider_type} onChange={e => setForm((p: any) => ({ ...p, provider_type: e.target.value }))}>{Object.values(ProviderTypeEnum).map(v => <option key={v} value={v}>{v}</option>)}</select></label>
      <label className='space-y-1 text-xs font-medium text-slate-600'><span>Nome da conexão</span><input className={input} value={form.display_name} onChange={e => setForm((p: any) => ({ ...p, display_name: e.target.value }))} placeholder='Ex: Meta Produção' /></label>
      <label className='space-y-1 text-xs font-medium text-slate-600'><span>WABA ID</span><input className={input} value={form.waba_id} onChange={e => setForm((p: any) => ({ ...p, waba_id: e.target.value }))} placeholder='ID da conta Business' /></label>
      <label className='space-y-1 text-xs font-medium text-slate-600'><span>Phone Number ID</span><input className={input} value={form.phone_number_id} onChange={e => setForm((p: any) => ({ ...p, phone_number_id: e.target.value }))} placeholder='ID do número conectado' /></label>
      <label className='space-y-1 text-xs font-medium text-slate-600'><span>Business ID</span><input className={input} value={form.business_id} onChange={e => setForm((p: any) => ({ ...p, business_id: e.target.value }))} placeholder='ID do Business Manager' /></label>
      <label className='space-y-1 text-xs font-medium text-slate-600'><span>Access Token</span><input type='password' className={input} value={form.access_token} onChange={e => setForm((p: any) => ({ ...p, access_token: e.target.value }))} placeholder='Token seguro do provider' /></label>
    </div>
    <p className='mt-3 text-xs text-slate-500'>Dica: mantenha credenciais de produção em variáveis seguras.</p>
    <button disabled={loading} className='primary-button mt-4 disabled:opacity-60'>{loading ? 'Salvando...' : 'Adicionar conexão'}</button>
  </form>;
}
