import type { AppointmentAssistantConfiguration, AppointmentConfigurator, AppointmentServiceConfiguration } from './api';

export const STATUS_LABELS = {
  needs_configuration: 'Configuração necessária', ready_to_activate: 'Pronto para ativar', active: 'Ativo',
  changes_pending: 'Alterações pendentes', customized: 'Personalizado no modo avançado',
  integration_error: 'Integração requer atenção', configuration_error: 'Configuração requer atenção',
} as const;

export const NOTICE_MESSAGES: Record<string, string> = {
  assistant_configuration_required: 'Complete os dados do assistente antes de ativá-lo.',
  assistant_flow_customized: 'Este assistente foi personalizado no modo avançado.',
  assistant_calendar_connection_required: 'Configure uma agenda para ativar o assistente.',
  assistant_calendar_connection_inactive: 'Reconecte o Google Calendar para continuar.',
  assistant_management_unknown: 'Esta instalação precisa ser revisada no modo avançado.',
  assistant_management_inconsistent: 'Esta instalação precisa ser revisada no modo avançado.',
  assistant_activation_required: 'As configurações salvas ainda precisam ser ativadas.',
  assistant_appointment_policy_invalid: 'Os horários do workspace precisam ser revisados.',
};

export function serviceId(label: string, existing: readonly AppointmentServiceConfiguration[]): string {
  const base = label.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '').slice(0, 58) || 'servico';
  let candidate = base; let suffix = 2;
  while (existing.some((item) => item.id === candidate)) candidate = `${base}_${suffix++}`;
  return candidate;
}

export function configurationFrom(snapshot: AppointmentConfigurator): AppointmentAssistantConfiguration {
  const connectionId = snapshot.calendar.connection_id
    || (snapshot.calendar.available_connections.length === 1 ? snapshot.calendar.available_connections[0].id : '');
  return {
    schema_version: 1,
    clinic_name: snapshot.configuration.clinic_name || '',
    services: snapshot.configuration.services.length ? snapshot.configuration.services.map((item) => ({ ...item })) : [{ id: 'consulta', label: 'Consulta', duration_minutes: 30 }],
    google_calendar_connection_id: snapshot.calendar.provider === 'google_calendar' ? connectionId : null,
    calendar: {
      provider: snapshot.calendar.provider,
      timezone: snapshot.scheduling?.timezone || '',
      business_hours: snapshot.scheduling?.business_hours || {},
      resource_name: 'Profissional principal',
    },
    handoff: snapshot.configuration.handoff ? { ...snapshot.configuration.handoff } : { enabled: true, reason: 'Solicitação do paciente' },
  };
}
