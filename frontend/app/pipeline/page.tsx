'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import type { CSSProperties } from 'react';
import {
  CircleDollarSign,
  Clock3,
  Filter,
  Globe2,
  Instagram,
  KanbanSquare,
  MessageCircle,
  Plus,
  Search,
  Sparkles,
  Target,
  TrendingUp,
  UserRound,
  Users
} from 'lucide-react';

import { getPipeline, listWorkspaceUsers, moveLeadToStage } from '../../lib/api';
import { PipelineLead, PipelineStage, WorkspaceUser } from '../../lib/types';

const CHANNELS = ['Todos', 'WhatsApp', 'Instagram', 'Web'] as const;
const ALL_OWNERS_FILTER = 'Todos';

type Channel = (typeof CHANNELS)[number];
type Owner = typeof ALL_OWNERS_FILTER | string;
type PipelineBoardStage = PipelineStage;

const temperatureLabel: Record<string, string> = {
  hot: 'Quente',
  warm: 'Morno',
  cold: 'Frio'
};

const channelIcons: Record<Exclude<Channel, 'Todos'>, typeof MessageCircle> = {
  WhatsApp: MessageCircle,
  Instagram,
  Web: Globe2
};

function getLeadChannel(lead: PipelineLead): Exclude<Channel, 'Todos'> {
  const source = String(lead.source || '').toLowerCase();
  if (source === 'instagram') return 'Instagram';
  if (source === 'webchat' || source === 'api') return 'Web';
  return 'WhatsApp';
}

function getLeadOwnerId(lead: PipelineLead) {
  return lead.responsible_user_id || lead.assigned_user_id || lead.owner_id || lead.assignee_id || null;
}

function getLeadOwnerLabel(lead: PipelineLead, users: WorkspaceUser[]) {
  const ownerId = getLeadOwnerId(lead);
  if (ownerId) {
    const user = users.find((item) => item.id === ownerId);
    return user?.name || user?.email || null;
  }

  const ownerEmail = lead.responsible_user_email || lead.assigned_user_email || lead.owner_email || null;
  if (ownerEmail) {
    const user = users.find((item) => item.email === ownerEmail);
    return user?.name || user?.email || null;
  }

  const ownerName = lead.responsible_user_name || lead.assigned_user_name || lead.owner_name || null;
  if (ownerName && users.some((item) => item.name === ownerName)) return ownerName;

  return null;
}

function formatRelativeDate(value?: string | null) {
  if (!value) return 'Sem interação recente';

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Sem interação recente';

  const diffInMinutes = Math.max(1, Math.floor((Date.now() - date.getTime()) / 60000));
  if (diffInMinutes < 60) return `Há ${diffInMinutes} min`;

  const diffInHours = Math.floor(diffInMinutes / 60);
  if (diffInHours < 24) return `Há ${diffInHours}h`;

  const diffInDays = Math.floor(diffInHours / 24);
  if (diffInDays < 30) return `Há ${diffInDays}d`;

  return date.toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' });
}

function getInitials(name?: string | null) {
  const normalized = (name || '').trim();
  if (!normalized) return 'LD';

  const parts = normalized.split(/\s+/).slice(0, 2);
  return parts.map((part) => part[0]).join('').toUpperCase();
}

export default function PipelinePage() {
  const [stages, setStages] = useState<PipelineStage[]>([]);
  const [draggingLead, setDraggingLead] = useState<PipelineLead | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');
  const [users, setUsers] = useState<WorkspaceUser[]>([]);
  const [isLoadingUsers, setIsLoadingUsers] = useState(true);
  const [usersError, setUsersError] = useState('');
  const [searchTerm, setSearchTerm] = useState('');
  const [channelFilter, setChannelFilter] = useState<Channel>('Todos');
  const [ownerFilter, setOwnerFilter] = useState<Owner>(ALL_OWNERS_FILTER);

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

  useEffect(() => {
    const fetchUsers = async () => {
      console.log('[PIPELINE USERS LOAD]');
      setIsLoadingUsers(true);
      setUsersError('');

      try {
        const data = await listWorkspaceUsers();
        setUsers(data);

        if (data.length === 0) {
          console.log('[PIPELINE USERS EMPTY]');
          setOwnerFilter(ALL_OWNERS_FILTER);
          return;
        }

        console.log('[PIPELINE USERS SUCCESS]', data);
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Erro desconhecido ao carregar responsáveis.';
        console.error('[PIPELINE USERS ERROR]', err);
        setUsers([]);
        setUsersError(message);
        setOwnerFilter(ALL_OWNERS_FILTER);
      } finally {
        setIsLoadingUsers(false);
      }
    };

    fetchUsers();
  }, []);

  useEffect(() => {
    if (ownerFilter === ALL_OWNERS_FILTER) return;
    if (!users.some((user) => user.id === ownerFilter)) setOwnerFilter(ALL_OWNERS_FILTER);
  }, [ownerFilter, users]);

  const boardStages = useMemo<PipelineBoardStage[]>(() => {
    return [...stages].sort((a, b) => a.position - b.position);
  }, [stages]);

  const allBoardLeads = useMemo(() => boardStages.flatMap((stage) => stage.leads), [boardStages]);

  const filteredStages = useMemo(() => {
    const normalizedSearch = searchTerm.trim().toLowerCase();

    return boardStages.map((stage) => ({
      ...stage,
      leads: stage.leads.filter((lead) => {
        const channel = getLeadChannel(lead);
        const ownerId = getLeadOwnerId(lead);
        const searchable = `${lead.name || ''} ${lead.phone} ${lead.last_message || ''}`.toLowerCase();

        const matchesSearch = !normalizedSearch || searchable.includes(normalizedSearch);
        const matchesChannel = channelFilter === 'Todos' || channel === channelFilter;
        const matchesOwner = ownerFilter === ALL_OWNERS_FILTER || ownerId === ownerFilter;

        return matchesSearch && matchesChannel && matchesOwner;
      })
    }));
  }, [boardStages, channelFilter, ownerFilter, searchTerm]);

  const totalLeads = allBoardLeads.length;
  const convertedLeads = boardStages.find((stage) => stage.is_final_stage)?.leads.length || 0;
  const conversionRate = totalLeads > 0 ? Math.round((convertedLeads / totalLeads) * 100) : 0;
  const oldestStageEntry = allBoardLeads
    .map((lead) => lead.entered_stage_at ? new Date(lead.entered_stage_at).getTime() : null)
    .filter((value): value is number => typeof value === 'number' && Number.isFinite(value))
    .sort((a, b) => a - b)[0];
  const maxStageAgeDays = oldestStageEntry ? Math.max(1, Math.floor((Date.now() - oldestStageEntry) / 86400000)) : 0;
  const visibleLeads = filteredStages.reduce((total, stage) => total + stage.leads.length, 0);

  const handleDrop = async (stage: PipelineBoardStage) => {
    if (!draggingLead) return;

    try {
      await moveLeadToStage(draggingLead.id, stage.id);
      await fetchPipeline();
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Erro desconhecido';
      console.error('[PIPELINE MOVE ERROR]', err);
      setError(`Falha real ao mover o contato: ${message}`);
    } finally {
      setDraggingLead(null);
    }
  };

  return (
    <main className="dashboard-page pipeline-crm-page">
      <section className="dashboard-hero pipeline-hero-premium">
        <div>
          <span className="pipeline-eyebrow"><Sparkles size={16} /> CRM Pipeline</span>
          <h1>Pipeline de Vendas</h1>
          <p>Kanban comercial com volume, valor e contexto em tempo real para priorizar oportunidades.</p>
        </div>
        <div className="dashboard-actions">
          <Link href="/crm" className="secondary-button">
            CRM lista
          </Link>
          <Link href="/chat" className="primary-button pipeline-new-lead-button">
            <Plus size={17} /> Novo Lead
          </Link>
        </div>
      </section>

      <section className="pipeline-metrics-grid" aria-label="Resumo do pipeline">
        <article className="pipeline-metric-card">
          <div className="pipeline-metric-icon"><Users size={20} /></div>
          <span>Leads Ativos</span>
          <strong>{totalLeads}</strong>
          <small>{visibleLeads} visíveis nos filtros</small>
        </article>
        <article className="pipeline-metric-card">
          <div className="pipeline-metric-icon"><CircleDollarSign size={20} /></div>
          <span>Leads no Pipeline</span>
          <strong>{totalLeads}</strong>
          <small>Dados reais do banco</small>
        </article>
        <article className="pipeline-metric-card">
          <div className="pipeline-metric-icon"><Target size={20} /></div>
          <span>Taxa de Conversão</span>
          <strong>{conversionRate}%</strong>
          <small>Leads em fechamento</small>
        </article>
        <article className="pipeline-metric-card">
          <div className="pipeline-metric-icon"><Clock3 size={20} /></div>
          <span>SLA na Etapa</span>
          <strong>{maxStageAgeDays ? `${maxStageAgeDays} dias` : '—'}</strong>
          <small>Ciclo comercial previsto</small>
        </article>
      </section>

      <section className="pipeline-toolbar" aria-label="Controles do pipeline">
        <label className="pipeline-search-field">
          <Search size={18} />
          <input
            value={searchTerm}
            onChange={(event) => setSearchTerm(event.target.value)}
            placeholder="Buscar lead por nome, telefone ou interação"
          />
        </label>

        <div className="pipeline-filter-group">
          <Filter size={17} />
          <select value={channelFilter} onChange={(event) => setChannelFilter(event.target.value as Channel)} aria-label="Filtrar por canal">
            {CHANNELS.map((channel) => <option key={channel} value={channel}>{channel === 'Todos' ? 'Todos os canais' : channel}</option>)}
          </select>
          <select
            value={ownerFilter}
            onChange={(event) => setOwnerFilter(event.target.value)}
            aria-label="Filtrar por responsável"
            disabled={isLoadingUsers || Boolean(usersError) || users.length === 0}
          >
            {isLoadingUsers ? <option value={ALL_OWNERS_FILTER}>Carregando responsáveis...</option> : null}
            {!isLoadingUsers && usersError ? <option value={ALL_OWNERS_FILTER}>Erro ao carregar responsáveis</option> : null}
            {!isLoadingUsers && !usersError && users.length === 0 ? <option value={ALL_OWNERS_FILTER}>Nenhum responsável cadastrado</option> : null}
            {!isLoadingUsers && !usersError && users.length > 0 ? (
              <>
                <option value={ALL_OWNERS_FILTER}>Todos os responsáveis</option>
                {users.map((user) => <option key={user.id} value={user.id}>{user.name || user.email}</option>)}
              </>
            ) : null}
          </select>
        </div>
      </section>

      {error ? <p className="error-text">{error}</p> : null}
      {usersError ? <p className="error-text">Falha real ao carregar responsáveis: {usersError}</p> : null}
      {isLoading ? <p className="pipeline-loading">Carregando pipeline...</p> : null}

      {!isLoading && stages.length === 0 ? (
        <div className="products-empty-state" role="status">
          <span className="products-empty-eyebrow">Configuração inicial</span>
          <h3>Nenhum item criado ainda</h3>
          <p>Crie etapas do pipeline para organizar leads por qualificação, proposta e fechamento.</p>
        </div>
      ) : null}

      <section className="pipeline-board" aria-label="Kanban de vendas">
        {filteredStages.map((stage) => {
          const stageValue = stage.leads.length;

          return (
            <article
              key={stage.id}
              className={`pipeline-column ${draggingLead ? 'is-drop-ready' : ''}`}
              onDragOver={(event) => event.preventDefault()}
              onDrop={() => handleDrop(stage)}
            >
              <header className="pipeline-column-header">
                <div>
                  <h2>{stage.name} <span>({stage.leads.length})</span></h2>
                  <strong>{stageValue} leads</strong>
                </div>
                <KanbanSquare size={19} />
              </header>

              <div className="pipeline-leads">
                {stage.leads.map((lead, index) => {
                  const ChannelIcon = channelIcons[getLeadChannel(lead)];
                  const owner = getLeadOwnerLabel(lead, users);

                  return (
                    <div
                      key={lead.id}
                      className="pipeline-lead-card"
                      draggable
                      onDragStart={() => setDraggingLead(lead)}
                      onDragEnd={() => setDraggingLead(null)}
                      style={{ '--stack-offset': `${Math.min(index, 4) * 5}px` } as CSSProperties}
                    >
                      <div className="pipeline-lead-topline">
                        <div className="pipeline-lead-avatar">{getInitials(lead.name)}</div>
                        <div>
                          <strong>{lead.name || 'Lead sem nome'}</strong>
                          <small>{lead.phone}</small>
                        </div>
                      </div>

                      <div className="pipeline-lead-meta-row">
                        <span><ChannelIcon size={14} /> {getLeadChannel(lead)}</span>
                        <span className={`lead-temp temp-${lead.temperature}`}>
                          {temperatureLabel[lead.temperature] || 'Frio'}
                        </span>
                      </div>

                      <p>{lead.last_message || 'Sem interação recente.'}</p>

                      <div className="pipeline-lead-footer">
                        <span className="pipeline-lead-value"><TrendingUp size={14} /> Score {lead.score}</span>
                        <span><Clock3 size={14} /> {formatRelativeDate(lead.last_interaction)}</span>
                      </div>
                      <div className="pipeline-lead-owner"><UserRound size={14} /> {owner || 'Sem responsável'} · Tempo na etapa: {formatRelativeDate(lead.entered_stage_at)}</div>
                    </div>
                  );
                })}

                {!stage.leads.length ? (
                  <div className="pipeline-empty-stage" role="status">
                    <div className="pipeline-empty-icon"><KanbanSquare size={22} /></div>
                    <h3>Nenhum lead nesta etapa</h3>
                    <p>Os contatos aparecerão automaticamente quando iniciarem uma conversa.</p>
                    <Link href="/chat" className="secondary-button">Iniciar conversa</Link>
                  </div>
                ) : null}
              </div>
            </article>
          );
        })}
      </section>
    </main>
  );
}
