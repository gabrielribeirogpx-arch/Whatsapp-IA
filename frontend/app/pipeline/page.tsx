'use client';

import Link from 'next/link';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import { useRouter } from 'next/navigation';
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
import { getUserDisplayName } from '../../lib/userDisplayName';
import { canMoveLeadToStage } from './dropGuards';
import { MobileBottomSheet } from '../../components/layout/MobileBottomSheet';
import { MobileListCard } from '../../components/layout/MobileListCard';
import { ResponsiveFilterToolbar } from '../../components/layout/ResponsiveFilterToolbar';

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
    return getUserDisplayName(user) || user?.email || null;
  }

  const ownerEmail = lead.responsible_user_email || lead.assigned_user_email || lead.owner_email || null;
  if (ownerEmail) {
    const user = users.find((item) => item.email === ownerEmail);
    return getUserDisplayName(user) || user?.email || null;
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

function moveLeadBetweenStages(stages: PipelineStage[], lead: PipelineLead, targetStageId: string): PipelineStage[] {
  const movedLead = { ...lead, stage_id: targetStageId };

  return stages.map((stage) => {
    const leadsWithoutMovedLead = stage.leads.filter((item) => item.id !== lead.id);

    if (stage.id !== targetStageId) {
      return { ...stage, leads: leadsWithoutMovedLead };
    }

    return { ...stage, leads: [movedLead, ...leadsWithoutMovedLead] };
  });
}

function pipelineContainsLeadInStage(stages: PipelineStage[], leadId: string, stageId: string) {
  return stages.some((stage) => stage.id === stageId && stage.leads.some((lead) => lead.id === leadId));
}

export default function PipelinePage() {
  const router = useRouter();
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
  const [selectedStageId, setSelectedStageId] = useState<string>('');
  const [selectedLead, setSelectedLead] = useState<PipelineLead | null>(null);
  const [moveLead, setMoveLead] = useState<PipelineLead | null>(null);
  const [moveTargetStageId, setMoveTargetStageId] = useState('');
  const [isMoving, setIsMoving] = useState(false);
  const pendingMoveLeadIds = useRef<Set<string>>(new Set());
  const activeDragRef = useRef<{ lead: PipelineLead; dropHandled: boolean } | null>(null);

  const syncPipeline = async () => {
    const data = await getPipeline();
    setStages(data);
    return data;
  };

  const fetchPipeline = async () => {
    try {
      setError('');
      await syncPipeline();
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

  // The stage query is intentionally optional: old pipeline links remain valid.
  useEffect(() => {
    const requestedStage = new URLSearchParams(window.location.search).get('stage');
    if (requestedStage && boardStages.some((stage) => stage.id === requestedStage)) {
      setSelectedStageId(requestedStage);
    } else if (!selectedStageId && boardStages[0]) {
      setSelectedStageId(boardStages[0].id);
    }
  }, [boardStages, selectedStageId]);

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

  const selectStage = useCallback((stageId: string) => {
    setSelectedStageId(stageId);
    const params = new URLSearchParams(window.location.search);
    params.set('stage', stageId);
    router.replace(`/pipeline?${params.toString()}`, { scroll: false });
  }, [router]);

  const handleDrop = async (stage: PipelineBoardStage) => {
    const dragSession = activeDragRef.current;
    if (!dragSession || dragSession.dropHandled) {
      setDraggingLead(null);
      return;
    }

    const leadToMove = dragSession.lead;
    const targetStageId = stage.id;

    if (!canMoveLeadToStage(leadToMove, targetStageId, pendingMoveLeadIds.current)) {
      setDraggingLead(null);
      return;
    }

    dragSession.dropHandled = true;
    pendingMoveLeadIds.current.add(leadToMove.id);
    const previousStages = stages;
    setError('');
    setDraggingLead(null);
    setStages((currentStages) => moveLeadBetweenStages(currentStages, leadToMove, targetStageId));

    try {
      await moveLeadToStage(leadToMove.id, targetStageId);
    } catch (moveErr) {
      console.error('[PIPELINE MOVE ERROR]', moveErr);

      try {
        const refreshedStages = await syncPipeline();
        if (pipelineContainsLeadInStage(refreshedStages, leadToMove.id, targetStageId)) return;
      } catch (refreshErr) {
        console.error('[PIPELINE MOVE CONFIRMATION ERROR]', refreshErr);
      }

      const message = moveErr instanceof Error ? moveErr.message : 'Erro desconhecido';
      setStages(previousStages);
      setError(`Falha real ao mover o contato: ${message}`);
      return;
    } finally {
      pendingMoveLeadIds.current.delete(leadToMove.id);
    }

    try {
      await syncPipeline();
    } catch (refreshErr) {
      console.error('[PIPELINE REFRESH AFTER MOVE ERROR]', refreshErr);
      setError('Contato movido com sucesso, mas não foi possível sincronizar o pipeline agora. A atualização visual foi mantida.');
    }
  };

  const handleMobileMove = async () => {
    if (!moveLead || !moveTargetStageId || isMoving) return;
    const targetStage = boardStages.find((stage) => stage.id === moveTargetStageId);
    if (!targetStage || !canMoveLeadToStage(moveLead, targetStage.id, pendingMoveLeadIds.current)) return;

    pendingMoveLeadIds.current.add(moveLead.id);
    const previousStages = stages;
    setIsMoving(true);
    setError('');
    setStages((current) => moveLeadBetweenStages(current, moveLead, targetStage.id));
    try {
      await moveLeadToStage(moveLead.id, targetStage.id);
      setMoveLead(null);
      setSelectedLead((current) => current?.id === moveLead.id ? { ...current, stage_id: targetStage.id } : current);
    } catch (moveErr) {
      setStages(previousStages);
      const message = moveErr instanceof Error ? moveErr.message : 'Erro desconhecido';
      setError(`Falha real ao mover o contato: ${message}`);
    } finally {
      pendingMoveLeadIds.current.delete(moveLead.id);
      setIsMoving(false);
    }
  };

  const activeFilters = Number(channelFilter !== 'Todos') + Number(ownerFilter !== ALL_OWNERS_FILTER);
  const clearFilters = () => { setChannelFilter('Todos'); setOwnerFilter(ALL_OWNERS_FILTER); setSearchTerm(''); };
  const mobileStage = filteredStages.find((stage) => stage.id === selectedStageId) || filteredStages[0];

  return (
    <main className="dashboard-page pipeline-crm-page">
      <section className="pipeline-mobile-view" aria-label="Pipeline de vendas">
        <header className="pipeline-mobile-header">
          <div><span className="pipeline-eyebrow"><Sparkles size={15} /> CRM</span><h1>Pipeline</h1></div>
          <Link href="/chat" className="pipeline-mobile-create" aria-label="Abrir conversa para criar lead"><Plus size={20} /></Link>
        </header>
        <ResponsiveFilterToolbar
          activeCount={activeFilters}
          onClear={clearFilters}
          search={<input value={searchTerm} onChange={(event) => setSearchTerm(event.target.value)} placeholder="Buscar lead" aria-label="Buscar lead por nome, telefone ou interação" />}
          filters={<>
            <label className="pipeline-mobile-filter-label">Canal<select value={channelFilter} onChange={(event) => setChannelFilter(event.target.value as Channel)} aria-label="Filtrar por canal">{CHANNELS.map((channel) => <option key={channel} value={channel}>{channel === 'Todos' ? 'Todos os canais' : channel}</option>)}</select></label>
            <label className="pipeline-mobile-filter-label">Responsável<select value={ownerFilter} onChange={(event) => setOwnerFilter(event.target.value)} disabled={isLoadingUsers || Boolean(usersError) || users.length === 0} aria-label="Filtrar por responsável"><option value={ALL_OWNERS_FILTER}>Todos os responsáveis</option>{users.map((user) => <option key={user.id} value={user.id}>{getUserDisplayName(user) || user.email}</option>)}</select></label>
          </>}
        />
        {error ? <p className="error-text" role="alert">{error}</p> : null}
        <nav className="pipeline-stage-tabs" aria-label="Etapas do pipeline">
          {filteredStages.map((stage) => <button key={stage.id} type="button" className={stage.id === mobileStage?.id ? 'is-active' : ''} onClick={() => selectStage(stage.id)} aria-pressed={stage.id === mobileStage?.id}><span>{stage.name}</span><small>{stage.leads.length}</small></button>)}
        </nav>
        {isLoading ? <div className="pipeline-mobile-skeleton" role="status">Carregando etapa…</div> : null}
        {!isLoading && mobileStage ? <section className="pipeline-mobile-stage" aria-live="polite">
          <header><div><h2>{mobileStage.name}</h2><p>{mobileStage.leads.length} {mobileStage.leads.length === 1 ? 'lead' : 'leads'}</p></div><KanbanSquare size={19} /></header>
          <div className="pipeline-mobile-leads">
            {mobileStage.leads.map((lead) => {
              const owner = getLeadOwnerLabel(lead, users);
              const ChannelIcon = channelIcons[getLeadChannel(lead)];
              return <MobileListCard key={lead.id} title={<button type="button" className="pipeline-mobile-lead-title" onClick={() => setSelectedLead(lead)}>{lead.name || 'Lead sem nome'}</button>} subtitle={lead.phone} status={<span className={`lead-temp temp-${lead.temperature}`}>{temperatureLabel[lead.temperature] || 'Frio'}</span>} meta={<span className="pipeline-mobile-card-meta"><ChannelIcon size={14} /> {owner || 'Sem responsável'} · {formatRelativeDate(lead.last_interaction)}</span>} action={<button type="button" className="pipeline-mobile-move" onClick={() => { setMoveLead(lead); setMoveTargetStageId(lead.stage_id || ''); }}>Mover</button>}>
                <p className="pipeline-mobile-last-message">{lead.last_message || 'Sem interação recente.'}</p>
              </MobileListCard>;
            })}
            {!mobileStage.leads.length ? <div className="pipeline-empty-stage" role="status"><div className="pipeline-empty-icon"><KanbanSquare size={22} /></div><h3>{searchTerm || activeFilters ? 'Nenhum resultado nesta etapa' : 'Nenhum lead nesta etapa'}</h3><p>{searchTerm || activeFilters ? 'Ajuste a busca ou os filtros para ver outros leads.' : 'Os contatos aparecerão automaticamente quando iniciarem uma conversa.'}</p></div> : null}
          </div>
        </section> : null}
      </section>

      <section className="dashboard-hero pipeline-hero-premium pipeline-desktop-only">
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

      <section className="pipeline-metrics-grid pipeline-desktop-only" aria-label="Resumo do pipeline">
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

      <section className="pipeline-toolbar pipeline-desktop-only" aria-label="Controles do pipeline">
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
                {users.map((user) => <option key={user.id} value={user.id}>{getUserDisplayName(user) || user.email}</option>)}
              </>
            ) : null}
          </select>
        </div>
      </section>

      <div className="pipeline-desktop-only">{error ? <p className="error-text">{error}</p> : null}
      {usersError ? <p className="error-text">Falha real ao carregar responsáveis: {usersError}</p> : null}
      {isLoading ? <p className="pipeline-loading">Carregando pipeline...</p> : null}</div>

      {!isLoading && stages.length === 0 ? (
        <div className="products-empty-state pipeline-desktop-only" role="status">
          <span className="products-empty-eyebrow">Configuração inicial</span>
          <h3>Nenhum item criado ainda</h3>
          <p>Crie etapas do pipeline para organizar leads por qualificação, proposta e fechamento.</p>
        </div>
      ) : null}

      <section className="pipeline-board pipeline-desktop-only" aria-label="Kanban de vendas">
        {filteredStages.map((stage) => {
          const stageValue = stage.leads.length;

          return (
            <article
              key={stage.id}
              className={`pipeline-column ${draggingLead ? 'is-drop-ready' : ''}`}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault();
                event.stopPropagation();
                void handleDrop(stage);
              }}
            >
              <header className="pipeline-column-header">
                <div>
                  <h2>{stage.name}</h2>
                  <strong><span>{stageValue}</span> {stageValue === 1 ? 'lead' : 'leads'}</strong>
                </div>
                <span className="pipeline-stage-action" aria-label="Etapa do pipeline"><KanbanSquare size={17} /></span>
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
                      onDragStart={() => {
                        activeDragRef.current = { lead, dropHandled: false };
                        setDraggingLead(lead);
                      }}
                      onDragEnd={() => {
                        activeDragRef.current = null;
                        setDraggingLead(null);
                      }}
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
                        <span className="pipeline-lead-channel"><ChannelIcon size={13} /> {getLeadChannel(lead)}</span>
                        <span className={`lead-temp temp-${lead.temperature}`}>
                          {temperatureLabel[lead.temperature] || 'Frio'}
                        </span>
                      </div>

                      <p>{lead.last_message || 'Sem interação recente.'}</p>

                      <div className="pipeline-lead-footer">
                        <span className="pipeline-lead-value"><TrendingUp size={14} /> Score {lead.score}</span>
                        <span className="pipeline-lead-time"><Clock3 size={13} /> {formatRelativeDate(lead.last_interaction)}</span>
                      </div>
                      <div className="pipeline-lead-owner"><UserRound size={13} /> <span>{owner || 'Sem responsável'}</span><span className="pipeline-stage-age">· {formatRelativeDate(lead.entered_stage_at)}</span></div>
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

      <MobileBottomSheet open={Boolean(selectedLead)} onClose={() => setSelectedLead(null)} title={selectedLead?.name || 'Detalhes do lead'} footer={selectedLead ? <button type="button" className="primary-button w-full" onClick={() => { setMoveLead(selectedLead); setMoveTargetStageId(selectedLead.stage_id || ''); setSelectedLead(null); }}>Mover de etapa</button> : null}>
        {selectedLead ? <div className="pipeline-lead-details"><section><h3>Contato</h3><p>{selectedLead.phone}</p>{selectedLead.email ? <p>{selectedLead.email}</p> : null}</section><section><h3>Etapa</h3><p>{boardStages.find((stage) => stage.id === selectedLead.stage_id)?.name || 'Sem etapa'}</p></section><section><h3>Responsável</h3><p>{getLeadOwnerLabel(selectedLead, users) || 'Sem responsável'}</p></section>{selectedLead.last_message ? <section><h3>Última interação</h3><p>{selectedLead.last_message}</p></section> : null}</div> : null}
      </MobileBottomSheet>
      <MobileBottomSheet open={Boolean(moveLead)} onClose={() => !isMoving && setMoveLead(null)} title="Mover lead" closeOnBackdrop={!isMoving} footer={<button type="button" className="primary-button w-full" disabled={!moveTargetStageId || isMoving || moveTargetStageId === moveLead?.stage_id} onClick={() => void handleMobileMove()}>{isMoving ? 'Movendo…' : 'Confirmar movimentação'}</button>}>
        <div className="pipeline-move-options" role="radiogroup" aria-label="Etapa de destino">{boardStages.map((stage) => <label key={stage.id}><input type="radio" name="target-stage" value={stage.id} checked={moveTargetStageId === stage.id} onChange={() => setMoveTargetStageId(stage.id)} disabled={isMoving} />{stage.name}<small>{stage.leads.length} leads</small></label>)}</div>
      </MobileBottomSheet>
    </main>
  );
}
