'use client';

import { FormEvent, useEffect, useMemo, useState } from 'react';
import { ArrowDown, ArrowUp, GripVertical, KanbanSquare, Pencil, Plus, Save, Sparkles } from 'lucide-react';
import { createPipelineStage, getSystemSettings, listPipelineStages, reorderPipelineStages, updatePipelineStage, updateSystemSettings } from '@/lib/api';
import { PipelineStage, WorkspaceProfile } from '@/lib/types';

const profileOptions: Array<{ value: WorkspaceProfile; label: string; description: string }> = [
  { value: 'private_sales', label: 'Vendas privadas', description: 'Funil comercial padrão para leads, proposta e fechamento.' },
  { value: 'government', label: 'Governo', description: 'Perfil de atendimento público sem protocolos, SLA ou departamentos nesta Sprint.' }
];

function stageSummary(stages: PipelineStage[]) {
  const totalLeads = stages.reduce((total, stage) => total + stage.leads.length, 0);
  return { totalLeads, totalStages: stages.length };
}

export default function PipelineSettingsTab() {
  const [stages, setStages] = useState<PipelineStage[]>([]);
  const [workspaceProfile, setWorkspaceProfile] = useState<WorkspaceProfile>('private_sales');
  const [newStageName, setNewStageName] = useState('');
  const [editingStageId, setEditingStageId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState('');
  const [error, setError] = useState('');

  const orderedStages = useMemo(() => [...stages].sort((a, b) => a.position - b.position), [stages]);
  const summary = useMemo(() => stageSummary(orderedStages), [orderedStages]);

  const refresh = async () => {
    setLoading(true);
    setError('');
    try {
      const [settings, pipelineStages] = await Promise.all([getSystemSettings(), listPipelineStages()]);
      setWorkspaceProfile(settings.workspace_profile || 'private_sales');
      setStages(pipelineStages);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Falha ao carregar configurações do pipeline.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { refresh(); }, []);

  const run = async (action: () => Promise<void>, successMessage: string) => {
    setSaving(true);
    setError('');
    try {
      await action();
      setToast(successMessage);
      setTimeout(() => setToast(''), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Não foi possível salvar o pipeline.');
    } finally {
      setSaving(false);
    }
  };

  const createStage = async (event: FormEvent) => {
    event.preventDefault();
    const name = newStageName.trim();
    if (!name) return;
    await run(async () => {
      await createPipelineStage({ name });
      setNewStageName('');
      await refresh();
    }, 'Etapa criada com sucesso.');
  };

  const saveStage = async (stage: PipelineStage) => {
    const name = editingName.trim();
    if (!name) return;
    await run(async () => {
      await updatePipelineStage(stage.id, { name });
      setEditingStageId(null);
      setEditingName('');
      await refresh();
    }, 'Etapa atualizada com sucesso.');
  };

  const moveStage = async (stageId: string, direction: -1 | 1) => {
    const currentIndex = orderedStages.findIndex((stage) => stage.id === stageId);
    const nextIndex = currentIndex + direction;
    if (currentIndex < 0 || nextIndex < 0 || nextIndex >= orderedStages.length) return;
    const nextOrder = [...orderedStages];
    const [stage] = nextOrder.splice(currentIndex, 1);
    nextOrder.splice(nextIndex, 0, stage);
    await run(async () => {
      const updated = await reorderPipelineStages(nextOrder.map((item) => item.id));
      setStages(updated);
    }, 'Ordem do pipeline atualizada.');
  };

  const saveProfile = async (profile: WorkspaceProfile) => {
    await run(async () => {
      const settings = await getSystemSettings();
      await updateSystemSettings({
        ...settings,
        token: settings.token || null,
        webhook_url: settings.webhook_url || null,
        workspace_profile: profile
      });
      setWorkspaceProfile(profile);
    }, 'Perfil do workspace salvo.');
  };

  return (
    <div className='overflow-hidden rounded-3xl border border-[color:var(--surface-border)] bg-white/95 shadow-[0_18px_44px_-34px_rgba(15,23,42,0.75)]'>
      <div className='relative border-b border-slate-100 bg-gradient-to-br from-white via-slate-50 to-emerald-50/70 p-6 md:p-8'>
        <div className='pointer-events-none absolute right-8 top-6 h-24 w-24 rounded-full bg-emerald-300/20 blur-2xl' />
        <p className='inline-flex items-center gap-2 rounded-full border border-emerald-200 bg-white/80 px-3 py-1 text-xs font-semibold text-emerald-700 shadow-sm'><KanbanSquare size={14} /> Pipeline configurável</p>
        <h2 className='mt-4 text-2xl font-semibold tracking-tight text-slate-950'>Configurações → Pipeline</h2>
        <p className='mt-2 max-w-3xl text-sm leading-relaxed text-slate-600'>Crie, edite e reordene as etapas que também alimentam o Kanban de leads por <code>stage_id</code>, preservando o dashboard atual.</p>
      </div>

      <div className='grid gap-5 p-5 md:p-6'>
        {toast ? <p className='rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-semibold text-emerald-700'>{toast}</p> : null}
        {error ? <p className='rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-700'>{error}</p> : null}

        <section className='grid gap-3 lg:grid-cols-3'>
          <div className='rounded-3xl border border-slate-200 bg-slate-50 p-5'>
            <p className='text-xs font-semibold uppercase tracking-[0.14em] text-slate-400'>Perfil ativo</p>
            <strong className='mt-2 block text-lg text-slate-950'>{profileOptions.find((item) => item.value === workspaceProfile)?.label}</strong>
            <p className='mt-1 text-sm text-slate-500'>{summary.totalStages} etapas · {summary.totalLeads} leads vinculados</p>
          </div>
          {profileOptions.map((option) => (
            <button
              key={option.value}
              type='button'
              disabled={saving || workspaceProfile === option.value}
              onClick={() => saveProfile(option.value)}
              className={`rounded-3xl border p-5 text-left transition ${workspaceProfile === option.value ? 'border-emerald-300 bg-emerald-50 text-emerald-900' : 'border-slate-200 bg-white hover:border-emerald-200 hover:bg-slate-50'}`}
            >
              <span className='inline-flex items-center gap-2 text-sm font-semibold'><Sparkles size={15} /> {option.label}</span>
              <span className='mt-2 block text-sm text-slate-500'>{option.description}</span>
            </button>
          ))}
        </section>

        <form onSubmit={createStage} className='grid gap-3 rounded-3xl border border-slate-200 bg-slate-50 p-4 md:grid-cols-[minmax(0,1fr)_auto]'>
          <input value={newStageName} onChange={(event) => setNewStageName(event.target.value)} className='w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-emerald-400 focus:ring-4 focus:ring-emerald-100' placeholder='Nome da nova etapa' />
          <button disabled={saving || !newStageName.trim()} className='inline-flex items-center justify-center gap-2 rounded-2xl bg-slate-950 px-5 py-3 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50'><Plus size={16} /> Criar etapa</button>
        </form>

        <section className='grid gap-3'>
          {loading ? <p className='rounded-2xl bg-slate-50 p-4 text-sm text-slate-500'>Carregando etapas...</p> : null}
          {!loading && orderedStages.map((stage, index) => {
            const isEditing = editingStageId === stage.id;
            return (
              <article key={stage.id} className='grid gap-3 rounded-3xl border border-slate-200 bg-white p-4 shadow-sm md:grid-cols-[auto_minmax(0,1fr)_auto] md:items-center'>
                <div className='flex items-center gap-3 text-slate-400'><GripVertical size={18} /><span className='rounded-full bg-slate-100 px-3 py-1 text-xs font-bold text-slate-600'>#{index + 1}</span></div>
                <div>
                  {isEditing ? (
                    <input value={editingName} onChange={(event) => setEditingName(event.target.value)} className='w-full rounded-2xl border border-slate-200 px-4 py-3 text-sm font-semibold text-slate-950 outline-none focus:border-emerald-400 focus:ring-4 focus:ring-emerald-100' />
                  ) : (
                    <><h3 className='text-base font-semibold text-slate-950'>{stage.name}</h3><p className='text-sm text-slate-500'>{stage.leads.length} leads nesta etapa · stage_id preservado</p></>
                  )}
                </div>
                <div className='flex flex-wrap gap-2'>
                  <button type='button' disabled={saving || index === 0} onClick={() => moveStage(stage.id, -1)} className='rounded-xl border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-600 disabled:opacity-40'><ArrowUp size={15} /></button>
                  <button type='button' disabled={saving || index === orderedStages.length - 1} onClick={() => moveStage(stage.id, 1)} className='rounded-xl border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-600 disabled:opacity-40'><ArrowDown size={15} /></button>
                  {isEditing ? <button type='button' disabled={saving} onClick={() => saveStage(stage)} className='inline-flex items-center gap-2 rounded-xl bg-emerald-600 px-3 py-2 text-sm font-semibold text-white'><Save size={15} /> Salvar</button> : <button type='button' onClick={() => { setEditingStageId(stage.id); setEditingName(stage.name); }} className='inline-flex items-center gap-2 rounded-xl border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-700'><Pencil size={15} /> Editar</button>}
                </div>
              </article>
            );
          })}
        </section>

        <section className='rounded-3xl border border-dashed border-emerald-200 bg-emerald-50/50 p-5'>
          <p className='text-xs font-semibold uppercase tracking-[0.16em] text-emerald-700'>Screenshot conceitual</p>
          <div className='mt-4 grid gap-3 md:grid-cols-3'>
            {orderedStages.slice(0, 3).map((stage) => <div key={stage.id} className='rounded-2xl border border-white bg-white/90 p-4 shadow-sm'><p className='font-semibold text-slate-950'>{stage.name}</p><div className='mt-3 h-16 rounded-xl bg-gradient-to-br from-slate-100 to-emerald-100' /></div>)}
          </div>
        </section>
      </div>
    </div>
  );
}
