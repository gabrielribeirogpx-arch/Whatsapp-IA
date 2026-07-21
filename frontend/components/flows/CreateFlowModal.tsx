'use client';

import { useEffect, useRef, useState } from 'react';
import { createFlow } from '@/lib/api';
import type { FlowPayload } from '@/lib/types';

type CreateMode = 'blank' | 'welcome';

type Props = {
  open: boolean;
  onClose: () => void;
  onCreated: (flowId: string, flowName?: string | null) => void;
  title?: string;
};

export default function CreateFlowModal({ open, onClose, onCreated, title = 'Criar novo Flow' }: Props) {
  const [isSubmitting, setIsSubmitting] = useState<CreateMode | null>(null);
  const [error, setError] = useState<string | null>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (!open) return;
    titleRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !isSubmitting) onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isSubmitting, onClose, open]);

  if (!open) return null;

  async function handleCreate(mode: CreateMode) {
    let responseDebug: { status: number; body: unknown; rawBody: string } | null = null;

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

      console.info('[FLOW CREATE REQUEST]', payload);

      const created = await createFlow(
        payload as FlowPayload & { nodes: unknown[]; edges: unknown[] },
        ({ status, body, rawBody }) => {
          responseDebug = { status, body, rawBody };
          console.info('[FLOW CREATE RESPONSE]', { status, body, rawBody });
        }
      );
      if (!created?.id) throw new Error('Flow criado sem id');
      onCreated(created.id, created.name);
      onClose();
    } catch (e) {
      console.error('[FLOW CREATE ERROR]', { error: e, response: responseDebug });
      console.error('Erro ao criar flow', e);
      setError('Não foi possível criar o flow agora.');
    } finally {
      setIsSubmitting(null);
    }
  }

  return (
    <div className="fixed inset-0 z-[140] grid place-items-center bg-slate-950/45 p-4 backdrop-blur-[2px]" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-labelledby="create-flow-title" className="w-full max-w-2xl rounded-3xl border border-emerald-100 bg-white p-6 shadow-[0_28px_70px_rgba(15,23,42,0.26)]" onClick={(e) => e.stopPropagation()}>
        <div className="mb-5 flex items-start justify-between gap-4">
          <div>
            <h3 ref={titleRef} id="create-flow-title" tabIndex={-1} className="text-2xl font-semibold text-slate-900">{title}</h3>
            <p className="mt-1 text-sm text-slate-500">Como deseja começar?</p>
          </div>
          <button type="button" onClick={onClose} className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50">Fechar</button>
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          <button type="button" onClick={() => void handleCreate('blank')} disabled={isSubmitting !== null} className="group rounded-2xl border border-emerald-200 bg-gradient-to-b from-emerald-50 to-white p-5 text-left transition hover:-translate-y-0.5 hover:shadow-lg disabled:opacity-70">
            <p className="text-base font-semibold text-slate-900">Criar do zero</p>
            <p className="mt-1 text-sm text-slate-600">Ideal para construir uma automação personalizada.</p>
          </button>
          <button type="button" onClick={() => void handleCreate('welcome')} disabled={isSubmitting !== null} className="group rounded-2xl border border-slate-200 bg-white p-5 text-left transition hover:-translate-y-0.5 hover:shadow-lg disabled:opacity-70">
            <p className="text-base font-semibold text-slate-900">Usar um template</p>
            <p className="mt-1 text-sm text-slate-600">Comece com um fluxo pronto e personalize conforme sua necessidade.</p>
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
