import { CheckCircle2, Clock3, ListChecks, Loader2, PauseCircle, XCircle, AlertTriangle, FileEdit } from 'lucide-react';

const meta = {
  draft: { label: 'Rascunho', desc: 'Ainda não iniciado', cls: 'border-slate-200 bg-slate-100 text-slate-700', Icon: FileEdit },
  scheduled: { label: 'Agendada', desc: 'Aguardando horário', cls: 'border-sky-200 bg-sky-50 text-sky-700', Icon: Clock3 },
  queued: { label: 'Na fila', desc: 'Destinatário aguardando envio', cls: 'border-indigo-200 bg-indigo-50 text-indigo-700', Icon: ListChecks },
  running: { label: 'Executando', desc: 'Envios em andamento', cls: 'border-emerald-200 bg-emerald-50 text-emerald-700', Icon: Loader2 },
  paused: { label: 'Pausada', desc: 'Novos envios interrompidos', cls: 'border-amber-200 bg-amber-50 text-amber-700', Icon: PauseCircle },
  completed: { label: 'Concluída', desc: 'Todos os destinatários processados', cls: 'border-violet-200 bg-violet-50 text-violet-700', Icon: CheckCircle2 },
  cancelled: { label: 'Cancelada', desc: 'Campanha encerrada manualmente', cls: 'border-slate-300 bg-slate-200 text-slate-800', Icon: XCircle },
  failed: { label: 'Falha', desc: 'Execução com falha', cls: 'border-rose-200 bg-rose-50 text-rose-700', Icon: AlertTriangle }
} as const;

export function getCampaignStatusMeta(status?: string) {
  return meta[String(status || '').toLowerCase() as keyof typeof meta] || meta.draft;
}

export default function CampaignStatusBadge({ status, showDescription = false }: { status?: string; showDescription?: boolean }) {
  const item = getCampaignStatusMeta(status);
  const Icon = item.Icon;
  return <span title={item.desc} className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold ${item.cls}`}>
    <Icon size={13} className={status === 'running' ? 'animate-spin' : ''} />
    {item.label}{showDescription ? <span className='hidden font-normal opacity-80 sm:inline'>· {item.desc}</span> : null}
  </span>;
}
