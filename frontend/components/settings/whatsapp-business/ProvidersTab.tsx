import { Inbox } from 'lucide-react';
import { FormEvent, useMemo, useState } from 'react';
import ProviderCard from './ProviderCard';
import ProviderForm from './ProviderForm';

export default function ProvidersTab(props: any) {
  const { providers, ...rest } = props;
  const [editingProvider, setEditingProvider] = useState<any | null>(null);
  const [editForm, setEditForm] = useState({ provider_type: 'meta_cloud', connection_type: 'cloud_api', display_name: '', waba_id: '', phone_number_id: '', business_id: '', access_token: '' });
  const [error, setError] = useState('');

  const statusBadges = useMemo(() => {
    if (!editingProvider) return [];
    return [editingProvider.connection_status || editingProvider.status || 'disconnected', editingProvider.is_active ? 'active' : 'inactive'];
  }, [editingProvider]);

  const openEditor = (provider: any) => {
    setEditingProvider(provider);
    setEditForm({
      provider_type: provider.provider_type || 'meta_cloud',
      connection_type: provider.connection_type || 'cloud_api',
      display_name: provider.display_name || '',
      waba_id: provider.waba_id || '',
      phone_number_id: provider.phone_number_id || '',
      business_id: provider.business_id || '',
      access_token: ''
    });
    setError('');
  };

  const submitEdit = async (event: FormEvent) => {
    event.preventDefault();
    try {
      setError('');
      await props.onEdit(editingProvider.id, editForm);
      setEditingProvider(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Não foi possível atualizar a conexão.');
    }
  };

  return <div className='w-full min-w-0 space-y-4'>
    <ProviderForm {...rest} />
    {props.loading && providers.length === 0 ? <div className='grid w-full min-w-0 gap-3 md:grid-cols-2'>{Array.from({ length: 2 }).map((_, i) => <div key={i} className='h-36 animate-pulse rounded-2xl border border-slate-200 bg-gradient-to-r from-slate-100 via-slate-50 to-slate-100' />)}</div> : providers.length === 0
      ? <div className='settings-card rounded-2xl border border-dashed border-slate-300 bg-white/70 p-10 text-center text-slate-600'><Inbox className='mx-auto mb-3 text-slate-400' size={24} />Conecte sua conta oficial Meta Cloud API ou futuro provider BSP.</div>
      : <div className='grid w-full min-w-0 gap-3'>{providers.map((p: any) => <ProviderCard key={p.id} p={p} onTest={() => props.onTest(p.id)} onActivate={() => props.onActivate(p.id)} onDelete={() => props.onDelete(p.id)} onEdit={() => openEditor(p)} loading={props.loading} />)}</div>}

    {editingProvider && <div className='fixed inset-0 z-50 flex items-center justify-center bg-slate-900/45 p-4 backdrop-blur-sm'>
      <form onSubmit={submitEdit} className='w-full max-w-2xl space-y-4 rounded-3xl border border-slate-200 bg-white p-6 shadow-2xl'>
        <div>
          <h3 className='text-xl font-semibold text-slate-900'>Editar conexão WhatsApp</h3>
          <p className='text-sm text-slate-600'>{(editingProvider.connection_status || editingProvider.status) === 'token_expired' ? 'Cole um novo token para restaurar a conexão sem remover o provider.' : 'Atualize credenciais sem interromper o runtime'}</p>
          <p className='mt-1 text-xs text-slate-500'>Método: {editingProvider.auth_type === 'embedded_signup' ? 'Conexão rápida com a Meta' : 'Configuração manual'}. As conexões manuais permanecem manuais.</p>
          <div className='mt-2 flex gap-2'>{statusBadges.map((badge: string) => <span key={badge} className='rounded-full border border-slate-200 bg-slate-50 px-2 py-1 text-xs font-medium text-slate-700'>{badge}</span>)}</div>
        </div>
        <div className='grid gap-3 sm:grid-cols-2'>
          <select className='premium-input' value={editForm.provider_type} onChange={(e) => setEditForm(prev => ({ ...prev, provider_type: e.target.value }))}><option value='meta_cloud'>meta_cloud</option><option value='bsp_360dialog'>bsp_360dialog</option></select>
          <select className='premium-input' value={editForm.connection_type} onChange={(e) => setEditForm(prev => ({ ...prev, connection_type: e.target.value }))}><option value='cloud_api'>Conectar WhatsApp Cloud API</option><option value='cloud_api_coexistence'>Conectar WhatsApp com Coexistence</option></select>
          <input className='premium-input' value={editForm.display_name} onChange={(e) => setEditForm(prev => ({ ...prev, display_name: e.target.value }))} placeholder='Nome da conexão' />
          <input className='premium-input' value={editForm.waba_id} onChange={(e) => setEditForm(prev => ({ ...prev, waba_id: e.target.value }))} placeholder='WABA ID (WhatsApp Business Account)' />
          <input className='premium-input' value={editForm.phone_number_id} onChange={(e) => setEditForm(prev => ({ ...prev, phone_number_id: e.target.value }))} placeholder='Phone Number ID' />
          <input className='premium-input' value={editForm.business_id} onChange={(e) => setEditForm(prev => ({ ...prev, business_id: e.target.value }))} placeholder='Business Manager ID' />
          <input type='password' className='premium-input sm:col-span-2' value={editForm.access_token} onChange={(e) => setEditForm(prev => ({ ...prev, access_token: e.target.value }))} placeholder='Cole novo token apenas se quiser substituir' />
        </div>
        <p className='text-xs text-slate-500'>Dica: Deixe o token em branco para manter o atual.</p>
        {error && <div className='rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700'>{error}</div>}
        <div className='flex justify-end gap-2'>
          <button type='button' onClick={() => setEditingProvider(null)} className='secondary-button border border-slate-300 bg-white'>Cancelar</button>
          <button disabled={props.loading} className='primary-button'>{props.loading ? 'Salvando...' : ((editingProvider.connection_status || editingProvider.status) === 'token_expired' ? 'Atualizar Token' : 'Salvar')}</button>
        </div>
      </form>
    </div>}
  </div>;
}
