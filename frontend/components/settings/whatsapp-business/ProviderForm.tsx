import { useState } from 'react';
import { getMetaConnectUrl } from '@/lib/api';
import { ProviderTypeEnum } from '@/lib/whatsappEnums';

const input = 'premium-input w-full';

function openCenteredPopup(url: string) {
  const width = 760;
  const height = 760;
  const left = Math.max(0, window.screenX + (window.outerWidth - width) / 2);
  const top = Math.max(0, window.screenY + (window.outerHeight - height) / 2);
  return window.open(url, 'meta-whatsapp-embedded-signup', `popup=yes,width=${width},height=${height},left=${left},top=${top},noopener,noreferrer`);
}

export default function ProviderForm({ form, setForm, onSubmit, loading, onMetaConnected }: { form: any; setForm: any; onSubmit: any; loading: boolean; onMetaConnected?: () => Promise<void> | void }) {
  const [connecting, setConnecting] = useState(false);
  const [method, setMethod] = useState<'quick' | 'manual'>('quick');
  const [metaError, setMetaError] = useState('');

  const connectWithMeta = async () => {
    setConnecting(true);
    setMetaError('');
    try {
      const { url } = await getMetaConnectUrl('cloud_api_coexistence');
      const popup = openCenteredPopup(url);
      if (!popup) throw new Error('Não foi possível abrir o popup da Meta. Verifique o bloqueador de popups.');
      const timer = window.setInterval(async () => {
        if (popup.closed) {
          window.clearInterval(timer);
          setConnecting(false);
          await onMetaConnected?.();
        }
      }, 1000);
    } catch (error) {
      setConnecting(false);
      setMetaError(error instanceof Error ? error.message : 'Não foi possível iniciar a conexão com a Meta.');
    }
  };

  return <form onSubmit={onSubmit} className='settings-card w-full min-w-0 rounded-2xl border border-[color:var(--surface-border)] bg-white/95 p-5 shadow-[0_14px_34px_-30px_rgba(15,23,42,0.85)]'>
    <div className='mb-4'><h3 className='text-sm font-semibold text-slate-900'>Nova conexão</h3><p className='text-xs text-slate-500'>Escolha como deseja conectar seu WhatsApp.</p></div>
    <div className='mb-5 grid gap-2 sm:grid-cols-2' role='group' aria-label='Método de conexão'>
      <button type='button' onClick={() => { setMethod('quick'); setMetaError(''); }} className={`rounded-xl border p-3 text-left transition ${method === 'quick' ? 'border-emerald-400 bg-emerald-50 ring-1 ring-emerald-200' : 'border-slate-200 bg-white hover:border-emerald-200'}`}><span className='block text-sm font-semibold text-slate-900'>Conexão rápida</span><span className='mt-1 block text-xs text-slate-600'>Recomendado: conecte com a Meta e valide os dados automaticamente.</span></button>
      <button type='button' onClick={() => { setMethod('manual'); setMetaError(''); }} className={`rounded-xl border p-3 text-left transition ${method === 'manual' ? 'border-slate-500 bg-slate-50 ring-1 ring-slate-200' : 'border-slate-200 bg-white hover:border-slate-300'}`}><span className='block text-sm font-semibold text-slate-900'>Configuração manual</span><span className='mt-1 block text-xs text-slate-600'>Informe as credenciais que você já possui.</span></button>
    </div>
    {method === 'quick' ? <div className='rounded-2xl border border-emerald-200 bg-emerald-50 p-4'>
      <p className='text-sm font-semibold text-emerald-900'>Integração via Embedded Signup da Meta</p>
      <p className='mt-1 text-xs text-emerald-800'>WABA ID, Phone Number ID, Business Manager ID e token serão obtidos e validados automaticamente.</p>
      <button type='button' disabled={loading || connecting} onClick={connectWithMeta} className='primary-button mt-4 disabled:opacity-60'>{connecting ? 'Aguardando Meta...' : 'Conectar com Meta'}</button>
      {metaError && <div className='mt-3 rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700'><p>{metaError}</p><div className='mt-2 flex gap-2'><button type='button' onClick={connectWithMeta} className='secondary-button border border-rose-300 bg-white'>Tentar novamente</button><button type='button' onClick={() => setMethod('manual')} className='secondary-button border border-slate-300 bg-white'>Usar configuração manual</button></div></div>}
    </div> : <>
      <p className='mb-3 text-xs text-slate-500'>Use a configuração manual caso você já possua as credenciais da Meta ou tenha recebido os dados do administrador da conta.</p>
    <div className='grid gap-3 md:grid-cols-2 xl:grid-cols-3'>
      <label className='space-y-1 text-xs font-medium text-slate-600'><span>Provider</span><select className={input} value={form.provider_type} onChange={e => setForm((p: any) => ({ ...p, provider_type: e.target.value }))}>{Object.values(ProviderTypeEnum).map(v => <option key={v} value={v}>{v}</option>)}</select></label>
      <label className='space-y-1 text-xs font-medium text-slate-600'><span>Tipo de conexão</span><select className={input} value={form.connection_type || 'cloud_api'} onChange={e => setForm((p: any) => ({ ...p, connection_type: e.target.value, coexistence_enabled: e.target.value === 'cloud_api_coexistence' }))}><option value='cloud_api'>Conectar WhatsApp Cloud API</option><option value='cloud_api_coexistence'>Conectar WhatsApp com Coexistence</option></select><small className='block text-[11px] font-normal text-slate-500'>Use o Wazza no mesmo número do WhatsApp Business App, sem perder o uso manual do aplicativo.</small></label>
        <label className='space-y-1 text-xs font-medium text-slate-600'><span>Nome da conexão</span><input className={input} value={form.display_name} onChange={e => setForm((p: any) => ({ ...p, display_name: e.target.value }))} placeholder='Ex: Meta Produção' /></label>
        <label className='space-y-1 text-xs font-medium text-slate-600'><span>WABA ID (WhatsApp Business Account)</span><input className={input} value={form.waba_id} onChange={e => setForm((p: any) => ({ ...p, waba_id: e.target.value }))} placeholder='WhatsApp Business Account ID' /></label>
        <label className='space-y-1 text-xs font-medium text-slate-600'><span>Phone Number ID</span><input className={input} value={form.phone_number_id} onChange={e => setForm((p: any) => ({ ...p, phone_number_id: e.target.value }))} placeholder='ID do número conectado' /></label>
        <label className='space-y-1 text-xs font-medium text-slate-600'><span>Business Manager ID</span><input className={input} value={form.business_id} onChange={e => setForm((p: any) => ({ ...p, business_id: e.target.value }))} placeholder='Business Manager ID' /></label>
        <label className='space-y-1 text-xs font-medium text-slate-600'><span>Access Token</span><input type='password' className={input} value={form.access_token} onChange={e => setForm((p: any) => ({ ...p, access_token: e.target.value }))} placeholder='Token seguro do provider' /></label>
    </div>
      <p className='mt-3 text-xs text-slate-500'>Dica: mantenha credenciais de produção em variáveis seguras.</p>
      <button disabled={loading} className='primary-button mt-4 disabled:opacity-60'>{loading ? 'Salvando...' : 'Adicionar conexão'}</button>
    </>}
  </form>;
}
