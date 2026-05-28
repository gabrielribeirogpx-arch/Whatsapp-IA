'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';

import { getPipeline, moveLeadToStage } from '../../lib/api';
import { PipelineLead, PipelineStage } from '../../lib/types';

const temperatureLabel: Record<string, string> = {
  hot: 'Quente',
  warm: 'Morno',
  cold: 'Frio'
};

export default function PipelinePage() {
  const [stages, setStages] = useState<PipelineStage[]>([]);
  const [draggingLead, setDraggingLead] = useState<PipelineLead | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');

  const fetchPipeline = async () => {
    try {
      setError('');
      const data = await getPipeline();
      setStages(data);
    } catch {
      setError('Falha real ao sincronizar o pipeline. Tente novamente em alguns instantes.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchPipeline();
  }, []);

  const handleDrop = async (stageId: string) => {
    if (!draggingLead) return;

    try {
      await moveLeadToStage(draggingLead.id, stageId);
      await fetchPipeline();
    } catch {
      setError('Falha real ao mover o contato. Tente novamente.');
    } finally {
      setDraggingLead(null);
    }
  };

  const totalLeads = stages.reduce((total, stage) => total + stage.leads.length, 0);

  return (
    <main className="dashboard-page">
      <section className="dashboard-hero">
        <div>
          <h1>Pipeline de Vendas</h1>
          <p>Visual Kanban dos contatos por etapa do cliente.</p>
        </div>
        <div className="dashboard-actions">
          <Link href="/crm" className="secondary-button">
            CRM lista
          </Link>
          <Link href="/chat" className="primary-button">
            Abrir chat
          </Link>
        </div>
      </section>

      {error ? <p className="error-text">{error}</p> : null}

      {isLoading ? <p>Carregando pipeline...</p> : null}

      {!isLoading && stages.length > 0 && totalLeads === 0 ? (
        <div className="products-empty-state" role="status">
          <span className="products-empty-eyebrow">Pipeline pronto para operar</span>
          <h3>Nenhum item criado ainda</h3>
          <p>Novos leads aparecerão automaticamente quando contatos qualificados chegarem pelo WhatsApp. Use o CRM e as conversas para começar a nutrir oportunidades.</p>
          <Link href="/chat" className="primary-button">Iniciar conversas</Link>
        </div>
      ) : null}

      {!isLoading && stages.length === 0 ? (
        <div className="products-empty-state" role="status">
          <span className="products-empty-eyebrow">Configuração inicial</span>
          <h3>Nenhum item criado ainda</h3>
          <p>Crie etapas do pipeline para organizar leads por qualificação, proposta e fechamento.</p>
        </div>
      ) : null}

      <section className="pipeline-board">
        {stages.map((stage) => (
          <article
            key={stage.id}
            className="pipeline-column"
            onDragOver={(event) => event.preventDefault()}
            onDrop={() => handleDrop(stage.id)}
          >
            <header className="pipeline-column-header">
              <h2>{stage.name}</h2>
              <span>{stage.leads.length}</span>
            </header>

            <div className="pipeline-leads">
              {stage.leads.map((lead) => (
                <div
                  key={lead.id}
                  className="pipeline-lead-card"
                  draggable
                  onDragStart={() => setDraggingLead(lead)}
                >
                  <strong>{lead.name || 'Sem nome'}</strong>
                  <small>{lead.phone}</small>
                  <p>{lead.last_message || 'Sem interação recente.'}</p>
                  <span className={`lead-temp temp-${lead.temperature}`}>
                    {temperatureLabel[lead.temperature] || 'Frio'}
                  </span>
                </div>
              ))}

              {!stage.leads.length ? <p className="empty-state">Arraste contatos para esta etapa.</p> : null}
            </div>
          </article>
        ))}
      </section>
    </main>
  );
}
