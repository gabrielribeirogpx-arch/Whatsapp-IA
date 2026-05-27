'use client';

import { useState } from 'react';
import { createFlow } from '@/lib/api';
import type { FlowPayload } from '@/lib/types';

type CreateMode = 'blank' | 'welcome';

type Props = {
  open: boolean;
  onClose: () => void;
  onCreated: (flowId: string) => void;
  title?: string;
};

export default function CreateFlowModal({ open, onClose, onCreated, title = 'Criar novo Flow' }: Props) {
  const [isSubmitting, setIsSubmitting] = useState<CreateMode | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  async function handleCreate(mode: CreateMode) {
    try {
      setError(null);
      setIsSubmitting(mode);
      const payload = {
        name: mode === 'blank' ? 'Novo Flow' : 'Novo Flow',
        trigger_type: 'default',
        trigger_value: '',
        ...(mode === 'welcome' ? {
          nodes: [
            {
              id: typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}`,
              type: 'message',
              position: { x: 180, y: 160 },
              data: { label: 'Mensagem', text: 'Olá! 👋', is_start: true, is_end: false },
            },
          ],
          edges: [],
        } : { nodes: [], edges: [] }),
      };

      const created = await createFlow(payload as FlowPayload & { nodes: unknown[]; edges: unknown[] });
      if (!created?.id) throw new Error('Flow criado sem id');
      onCreated(created.id);
      onClose();
    } catch (e) {
      console.error('Erro ao criar flow', e);
      setError('Não foi possível criar o flow agora.');
    } finally {
      setIsSubmitting(null);
    }
  }

  return (
    <div className="fixed inset-0 z-[140] grid place-items-center bg-slate-950/45 p-4 backdrop-blur-[2px]" onClick={onClose}>
      <div className="w-full max-w-2xl rounded-3xl border border-emerald-100 bg-white p-6 shadow-[0_28px_70px_rgba(15,23,42,0.26)]" onClick={(e) => e.stopPropagation()}>
        <div className="mb-5 flex items-start justify-between gap-4">
          <div>
            <h3 className="text-2xl font-semibold text-slate-900">{title}</h3>
            <p className="mt-1 text-sm text-slate-500">Escolha como deseja começar seu fluxo.</p>
          </div>
          <button type="button" onClick={onClose} className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50">Fechar</button>
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          <button type="button" onClick={() => void handleCreate('welcome')} disabled={isSubmitting !== null} className="group rounded-2xl border border-emerald-200 bg-gradient-to-b from-emerald-50 to-white p-5 text-left transition hover:-translate-y-0.5 hover:shadow-lg disabled:opacity-70">
            <p className="text-base font-semibold text-slate-900">Adicionar mensagem inicial</p>
            <p className="mt-1 text-sm text-slate-600">Cria um flow com primeiro bloco pronto para editar.</p>
          </button>
          <button type="button" onClick={() => void handleCreate('blank')} disabled={isSubmitting !== null} className="group rounded-2xl border border-slate-200 bg-white p-5 text-left transition hover:-translate-y-0.5 hover:shadow-lg disabled:opacity-70">
            <p className="text-base font-semibold text-slate-900">Usar template simples</p>
            <p className="mt-1 text-sm text-slate-600">Abre o builder vazio para montar do seu jeito.</p>
          </button>
        </div>

        <div className="mt-5 min-h-6 text-sm">
          {isSubmitting ? <span className="text-emerald-700">Criando fluxo...</span> : null}
          {error ? <span className="text-rose-600">{error}</span> : null}
        </div>
      </div>
    </div>
  );
}
