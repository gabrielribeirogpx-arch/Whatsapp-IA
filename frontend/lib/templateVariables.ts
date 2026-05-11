export type TemplateVariableCategory = 'Contato' | 'Empresa' | 'Pedido' | 'Agendamento' | 'Financeiro' | 'Sistema';

export type TemplateVariableDefinition = {
  key: string;
  label: string;
  description: string;
  example: string;
  category: TemplateVariableCategory;
};

export const TEMPLATE_VARIABLES: TemplateVariableDefinition[] = [
  { key: 'first_name', label: 'Primeiro nome', description: 'Primeiro nome do contato.', example: 'Gabriel', category: 'Contato' },
  { key: 'full_name', label: 'Nome completo', description: 'Nome completo do contato.', example: 'Gabriel Ribeiro', category: 'Contato' },
  { key: 'phone', label: 'Telefone', description: 'Telefone principal do contato.', example: '+55 16 99999-9999', category: 'Contato' },
  { key: 'email', label: 'E-mail', description: 'E-mail do contato.', example: 'cliente@email.com', category: 'Contato' },
  { key: 'city', label: 'Cidade', description: 'Cidade do contato.', example: 'São Paulo', category: 'Contato' },
  { key: 'company', label: 'Empresa', description: 'Empresa relacionada ao contato/pedido.', example: 'Wazza API', category: 'Empresa' },
  { key: 'order_number', label: 'Número do pedido', description: 'Identificador único do pedido.', example: '#4821', category: 'Pedido' },
  { key: 'appointment_date', label: 'Data do agendamento', description: 'Data agendada para atendimento.', example: '12/05/2026', category: 'Agendamento' },
  { key: 'appointment_time', label: 'Horário do agendamento', description: 'Horário agendado para atendimento.', example: '14:30', category: 'Agendamento' },
  { key: 'payment_link', label: 'Link de pagamento', description: 'URL para pagamento.', example: 'https://pay.exemplo.com/abc', category: 'Financeiro' },
  { key: 'due_date', label: 'Data de vencimento', description: 'Data limite para pagamento.', example: '20/05/2026', category: 'Financeiro' },
  { key: 'amount', label: 'Valor', description: 'Valor associado ao template.', example: 'R$ 149,90', category: 'Financeiro' },
  { key: 'protocol_number', label: 'Número do protocolo', description: 'Código de protocolo interno.', example: '2026-00123', category: 'Sistema' }
];

export const TEMPLATE_VARIABLES_BY_LABEL = new Map(TEMPLATE_VARIABLES.map((item) => [item.label.toLowerCase(), item]));
