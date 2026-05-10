import { FileText } from 'lucide-react';
import TemplateCard from './TemplateCard';
import TemplateForm from './TemplateForm';

export default function TemplatesTab(props: any) {
  const { templates } = props;
  return <div className='space-y-4'>
    <div className='flex flex-wrap items-center justify-between gap-2'>
      <TemplateForm {...props} />
    </div>
    <button disabled={props.loading} className='secondary-button border border-slate-300 bg-white hover:bg-slate-100' onClick={props.onSync}>{props.loading ? 'Sincronizando...' : 'Sincronizar templates'}</button>
    {templates.length === 0 ? <div className='settings-card rounded-2xl border border-dashed border-slate-300 bg-white/70 p-10 text-center text-slate-600'><FileText className='mx-auto mb-3 text-slate-400' size={24} />Crie templates aprováveis para mensagens fora da janela de 24 horas.</div> : <div className='grid gap-3'>{templates.map((t: any) => <TemplateCard key={t.id} t={t} onSubmit={() => props.onSubmitTemplate(t.id)} loading={props.loading} />)}</div>}
  </div>;
}
