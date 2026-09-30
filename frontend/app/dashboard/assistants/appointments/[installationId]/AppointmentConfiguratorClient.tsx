'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { AlertTriangle, CalendarDays, CheckCircle2, Clock3, Plus, Trash2 } from 'lucide-react';
import {
  activateAppointmentAssistant, AppointmentAssistantApiError, type AppointmentAssistantConfiguration,
  type AppointmentConfigurator, getAppointmentConfigurator, getGoogleCalendarConnectUrl, updateAppointmentConfiguration,
} from '@/lib/api';
import { configurationFrom, NOTICE_MESSAGES, serviceId, STATUS_LABELS } from '@/lib/appointment-configurator';

const DAYS: Record<string, string> = { monday: 'Segunda', tuesday: 'Terça', wednesday: 'Quarta', thursday: 'Quinta', friday: 'Sexta', saturday: 'Sábado', sunday: 'Domingo' };
const CALENDAR_TEXT = { connected: 'Conectado', inactive: 'Reconectar Google Calendar', missing: 'Conexão não encontrada', not_configured: 'Conectar Google Calendar' } as const;

export default function AppointmentConfiguratorClient({ installationId }: { installationId: string }) {
  const router = useRouter();
  const [snapshot, setSnapshot] = useState<AppointmentConfigurator | null>(null);
  const [form, setForm] = useState<AppointmentAssistantConfiguration | null>(null);
  const [loading, setLoading] = useState(true); const [loadError, setLoadError] = useState(false);
  const [dirty, setDirty] = useState(false); const [saving, setSaving] = useState(false); const [activating, setActivating] = useState(false);
  const [conflict, setConflict] = useState(false); const [replaceOpen, setReplaceOpen] = useState(false); const [builderOpen, setBuilderOpen] = useState(false);
  const [toast, setToast] = useState(''); const [operationError, setOperationError] = useState('');
  const dialogRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    setLoading(true); setLoadError(false); setConflict(false);
    try {
      const value = await getAppointmentConfigurator(installationId);
      const locallyPreselected = value.calendar.provider === 'google_calendar' && !value.calendar.connection_id && value.calendar.available_connections.length === 1;
      setSnapshot(value); setForm(configurationFrom(value)); setDirty(locallyPreselected);
    }
    catch { setLoadError(true); } finally { setLoading(false); }
  }, [installationId]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => { const warn = (event: BeforeUnloadEvent) => { if (dirty) event.preventDefault(); }; window.addEventListener('beforeunload', warn); return () => window.removeEventListener('beforeunload', warn); }, [dirty]);
  useEffect(() => { if (!replaceOpen && !builderOpen) return; const first = dialogRef.current?.querySelector<HTMLElement>('button'); first?.focus(); }, [replaceOpen, builderOpen]);
  const change = (next: AppointmentAssistantConfiguration) => { setForm(next); setDirty(true); setConflict(false); setOperationError(''); };
  const valid = Boolean(form && form.clinic_name.trim().length >= 2 && form.services.length && form.services.every((item) => item.label.trim() && Number.isInteger(item.duration_minutes) && item.duration_minutes >= 5 && item.duration_minutes <= 480) && ((form.calendar.provider === 'wazza_native' && form.calendar.timezone) || form.google_calendar_connection_id) && (!form.handoff.enabled || form.handoff.reason?.trim()));

  const save = async () => {
    if (!snapshot || !form || !valid) return;
    setSaving(true); setOperationError('');
    try {
      await updateAppointmentConfiguration(installationId, { expected_configuration_version: snapshot.concurrency.configuration_version, configuration: form });
      setToast('Alterações salvas com sucesso.'); await load();
    } catch (error) {
      if (error instanceof AppointmentAssistantApiError && error.status === 409) setConflict(true);
      else setOperationError('Não foi possível salvar as alterações. Revise os campos e tente novamente.');
    } finally { setSaving(false); }
  };
  const activate = async (confirmed = false) => {
    if (!snapshot || dirty || !snapshot.actions.can_activate) return;
    if (!confirmed && snapshot.activation.would_replace_active_flow) { setReplaceOpen(true); return; }
    setActivating(true); setOperationError('');
    try {
      await activateAppointmentAssistant(installationId, { expected_configuration_version: snapshot.concurrency.configuration_version, expected_managed_flow_version_id: snapshot.concurrency.managed_flow_version_id, confirm_replace_active_flow: confirmed });
      setReplaceOpen(false); await load(); setToast('Assistente ativado com sucesso.');
    } catch (error) {
      if (error instanceof AppointmentAssistantApiError && error.code === 'assistant_activation_would_replace_active_flow') setReplaceOpen(true);
      else if (error instanceof AppointmentAssistantApiError && error.status === 409) { setOperationError('O assistente foi alterado em outra sessão. Recarregue antes de ativar.'); }
      else setOperationError('Não foi possível ativar o assistente. Tente novamente.');
    } finally { setActivating(false); }
  };
  const openBuilder = () => { if (snapshot?.assistant.flow_id) { setBuilderOpen(false); router.push(`/dashboard/flow-builder?flow_id=${encodeURIComponent(snapshot.assistant.flow_id)}`); } };
  const connectCalendar = () => {
    window.location.href = getGoogleCalendarConnectUrl(`/dashboard/assistants/appointments/${installationId}`);
  };

  if (loading) return <main className="appointment-page" aria-label="Carregando assistente"><div className="appointment-skeleton appointment-skeleton-title" />{[1, 2, 3].map((item) => <div className="appointment-skeleton appointment-skeleton-card" key={item} />)}</main>;
  if (loadError || !snapshot || !form) return <main className="appointment-page"><section className="appointment-load-error" role="alert"><AlertTriangle /><h1>Não foi possível carregar o assistente.</h1><button onClick={() => void load()}>Tentar novamente</button></section></main>;
  const readOnly = !snapshot.actions.can_edit;
  const reviewAdvanced = snapshot.management.mode === 'unknown' || snapshot.management.mode === 'inconsistent';
  const activateLabel = snapshot.assistant.status === 'changes_pending' ? 'Ativar alterações' : snapshot.assistant.status === 'active' ? 'Ativo' : 'Ativar Assistente';

  return <main className="appointment-page">
    <header className="appointment-header"><div><p className="appointment-eyebrow">Wazza</p><h1>Configure seu Assistente de Agendamento</h1><p>Defina os serviços, horários e integrações usados pelo seu assistente.</p></div><span className={`appointment-status status-${snapshot.assistant.status}`}><CheckCircle2 aria-hidden="true" />{STATUS_LABELS[snapshot.assistant.status]}</span></header>
    {snapshot.assistant.status === 'customized' && <section className="appointment-alert" role="alert"><strong>Este assistente foi personalizado no modo avançado.</strong><span>Para evitar substituir alterações feitas no editor avançado, a configuração simples não pode ser aplicada automaticamente.</span>{snapshot.actions.can_open_builder && <button onClick={() => setBuilderOpen(true)}>Abrir no modo avançado</button>}</section>}
    {reviewAdvanced && <section className="appointment-alert danger" role="alert"><strong>Esta instalação precisa ser revisada no modo avançado.</strong>{snapshot.actions.can_open_builder && <button onClick={() => setBuilderOpen(true)}>Abrir no modo avançado</button>}</section>}
    {snapshot.notices.map((notice) => <div className={`appointment-notice ${notice.severity}`} role="status" key={notice.code}><AlertTriangle aria-hidden="true" />{NOTICE_MESSAGES[notice.code] || 'Este assistente requer atenção antes de continuar.'}</div>)}
    {conflict && <div className="appointment-notice error" role="alert"><span>Esta configuração foi alterada em outra sessão.</span><button onClick={() => void load()}>Recarregar</button></div>}
    {operationError && <div className="appointment-notice error" role="alert">{operationError}</div>}

    <section className="appointment-card"><h2>Sua empresa</h2><label>Nome da clínica<input value={form.clinic_name} maxLength={160} minLength={2} required disabled={readOnly} onChange={(e) => change({ ...form, clinic_name: e.target.value })} /></label>{form.clinic_name.length > 0 && form.clinic_name.trim().length < 2 && <small className="field-error">Informe pelo menos 2 caracteres.</small>}</section>
    <section className="appointment-card"><div className="appointment-card-title"><div><h2>Serviços</h2><p>Defina o que seus clientes podem agendar.</p></div><button className="secondary" disabled={readOnly || form.services.length >= 50} onClick={() => change({ ...form, services: [...form.services, { id: serviceId('Novo serviço', form.services), label: 'Novo serviço', duration_minutes: 30 }] })}><Plus />Adicionar serviço</button></div><div className="service-list">{form.services.map((service, index) => <div className="service-row" key={service.id}><label>Nome do serviço<input maxLength={120} disabled={readOnly} value={service.label} onChange={(e) => change({ ...form, services: form.services.map((item, position) => position === index ? { ...item, label: e.target.value } : item) })} /></label><label>Duração<div className="duration-input"><input aria-describedby={`duration-${index}`} type="number" min={5} max={480} step={1} disabled={readOnly} value={service.duration_minutes} onChange={(e) => change({ ...form, services: form.services.map((item, position) => position === index ? { ...item, duration_minutes: Number(e.target.value) } : item) })} /><span id={`duration-${index}`}>min</span></div></label><button className="icon-button" aria-label={`Remover ${service.label}`} disabled={readOnly || form.services.length === 1} onClick={() => change({ ...form, services: form.services.filter((_, position) => position !== index) })}><Trash2 /></button></div>)}</div></section>
    <section className="appointment-card"><h2>Agenda</h2>
      <div role="radiogroup" aria-label="Provider da agenda">
        <label className="toggle-label"><input type="radio" name="calendar-provider" checked={form.calendar.provider === 'wazza_native'} disabled={readOnly} onChange={() => change({ ...form, google_calendar_connection_id: null, calendar: { ...form.calendar, provider: 'wazza_native' } })} /><span><strong>Agenda Wazza</strong><small>Use a agenda integrada do Wazza. Não requer conexão externa.</small></span></label>
        <label className="toggle-label"><input type="radio" name="calendar-provider" checked={form.calendar.provider === 'google_calendar'} disabled={readOnly} onChange={() => change({ ...form, calendar: { ...form.calendar, provider: 'google_calendar' } })} /><span><strong>Google Calendar</strong><small>Use seu Google Calendar existente.</small></span></label>
      </div>
      {form.calendar.provider === 'google_calendar' && <><div className={`calendar-state ${snapshot.calendar.status !== 'connected' ? 'attention' : ''}`}><CalendarDays /><div><strong>Google Calendar</strong><span>{snapshot.calendar.status === 'inactive' ? 'Google Calendar precisa ser reconectado' : CALENDAR_TEXT[snapshot.calendar.status]}</span></div>{snapshot.calendar.status !== 'connected' && <button className="secondary" disabled={readOnly} onClick={connectCalendar}>{snapshot.calendar.status === 'inactive' ? 'Reconectar' : 'Conectar Google Calendar'}</button>}</div>{snapshot.calendar.available_connections.length > 0 && <label>Agenda do Google<select aria-label="Agenda do Google" disabled={readOnly} value={form.google_calendar_connection_id || ''} onChange={(e) => change({ ...form, google_calendar_connection_id: e.target.value })}>{!form.google_calendar_connection_id && <option value="">Selecionar agenda</option>}{snapshot.calendar.connection_id && snapshot.calendar.status !== 'connected' && <option value={snapshot.calendar.connection_id} disabled>Conexão atual indisponível</option>}{snapshot.calendar.available_connections.map((connection) => <option key={connection.id} value={connection.id}>{connection.label}</option>)}</select></label>}</>}
      {form.calendar.provider === 'wazza_native' && <label>Timezone<input disabled={readOnly} value={form.calendar.timezone || ''} onChange={(e) => change({ ...form, calendar: { ...form.calendar, timezone: e.target.value } })} /></label>}
      <div className="schedule"><div><h3><Clock3 />Horários de funcionamento</h3><span className="timezone">{form.calendar.timezone || snapshot.scheduling?.timezone || 'Horários indisponíveis'}</span></div>{Object.entries(form.calendar.business_hours || snapshot.scheduling?.business_hours || {}).map(([day, ranges]) => <div className="schedule-row" key={day}><strong>{DAYS[day] || day}</strong><span>{ranges.length ? ranges.map((range) => `${range.start}–${range.end}`).join(', ') : 'Fechado'}</span></div>)}</div>
    </section>
    <section className="appointment-card"><h2>Atendimento humano</h2><label className="toggle-label"><input type="checkbox" checked={form.handoff.enabled} disabled={readOnly} onChange={(e) => change({ ...form, handoff: { ...form.handoff, enabled: e.target.checked } })} />Transferir para atendimento humano quando necessário</label>{form.handoff.enabled && <label>Motivo padrão da transferência<textarea maxLength={500} required disabled={readOnly} value={form.handoff.reason || ''} onChange={(e) => change({ ...form, handoff: { ...form.handoff, reason: e.target.value } })} /></label>}</section>
    <div className="appointment-actions"><div>{dirty && <span role="status">Alterações não salvas</span>}{dirty && <small>Salve as alterações antes de ativar.</small>}{form.calendar.provider === 'google_calendar' && !form.google_calendar_connection_id && <small>Conecte e selecione um Google Calendar nas configurações antes de salvar.</small>}</div><button className="secondary" disabled={readOnly || !dirty || saving || !valid} onClick={() => void save()}>{saving ? 'Salvando…' : 'Salvar alterações'}</button><button className="primary" disabled={dirty || !snapshot.actions.can_activate || activating || snapshot.assistant.status === 'active' || snapshot.assistant.status === 'customized' || reviewAdvanced} onClick={() => void activate()}>{activating ? 'Ativando…' : activateLabel}</button></div>
    <section className="advanced-section"><div><h2>Modo avançado</h2><p>Personalize comportamentos e etapas além desta configuração.</p></div>{snapshot.actions.can_open_builder && <button className="secondary" onClick={() => setBuilderOpen(true)}>Abrir no modo avançado</button>}</section>
    {toast && <div className="appointment-toast" role="status">{toast}<button aria-label="Fechar notificação" onClick={() => setToast('')}>×</button></div>}
    {replaceOpen && <div className="appointment-dialog-backdrop" onMouseDown={() => !activating && setReplaceOpen(false)}><div ref={dialogRef} className="appointment-dialog" role="dialog" aria-modal="true" aria-labelledby="replace-title" onMouseDown={(e) => e.stopPropagation()}><h2 id="replace-title">Já existe outro assistente ativo</h2><p>Ativar este assistente substituirá o assistente atualmente ativo neste workspace.</p><footer><button className="secondary" disabled={activating} onClick={() => setReplaceOpen(false)}>Cancelar</button><button className="primary" disabled={activating} onClick={() => void activate(true)}>Ativar mesmo assim</button></footer></div></div>}
    {builderOpen && <div className="appointment-dialog-backdrop" onMouseDown={() => setBuilderOpen(false)}><div ref={dialogRef} className="appointment-dialog" role="dialog" aria-modal="true" aria-labelledby="builder-title" onMouseDown={(e) => e.stopPropagation()}><h2 id="builder-title">Abrir modo avançado?</h2><p>O editor avançado permite personalizações estruturais que podem fazer este assistente deixar de ser gerenciado por esta tela.</p><footer><button className="secondary" onClick={() => setBuilderOpen(false)}>Cancelar</button><button className="primary" onClick={openBuilder}>Continuar</button></footer></div></div>}
  </main>;
}
