import { Inbox } from 'lucide-react';
import ProviderCard from './ProviderCard';
import ProviderForm from './ProviderForm';

export default function ProvidersTab(props: any) {
  const { providers, ...rest } = props;
  return <div className='space-y-4'>
    <ProviderForm {...rest} />
    {props.loading && providers.length === 0 ? <div className='grid gap-3 md:grid-cols-2'>{Array.from({ length: 2 }).map((_, i) => <div key={i} className='h-36 animate-pulse rounded-2xl border border-slate-200 bg-gradient-to-r from-slate-100 via-slate-50 to-slate-100' />)}</div> : providers.length === 0
      ? <div className='settings-card rounded-2xl border border-dashed border-slate-300 bg-white/70 p-10 text-center text-slate-600'><Inbox className='mx-auto mb-3 text-slate-400' size={24} />Conecte sua conta oficial Meta Cloud API ou futuro provider BSP.</div>
      : <div className='grid gap-3'>{providers.map((p: any) => <ProviderCard key={p.id} p={p} onTest={() => props.onTest(p.id)} onActivate={() => props.onActivate(p.id)} onDelete={() => props.onDelete(p.id)} loading={props.loading} />)}</div>}
  </div>;
}
