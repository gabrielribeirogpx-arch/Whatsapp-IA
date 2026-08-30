export const DATA_COLLECTION_TYPE_OPTIONS = [
  { value: 'text', label: 'Texto' },
  { value: 'number', label: 'Número' },
  { value: 'email', label: 'E-mail' },
  { value: 'phone', label: 'Telefone' },
  { value: 'date', label: 'Data' },
  { value: 'time', label: 'Hora' },
  { value: 'cpf', label: 'CPF' },
  { value: 'cnpj', label: 'CNPJ' },
  { value: 'url', label: 'URL' },
  { value: 'currency', label: 'Moeda' },
  { value: 'boolean', label: 'Sim/Não' },
  { value: 'choice', label: 'Escolha' },
  { value: 'appointment_period', label: 'Período de agendamento' },
] as const;

export type DataCollectionType = typeof DATA_COLLECTION_TYPE_OPTIONS[number]['value'];

export const DATA_COLLECTION_TYPE_LABELS: Record<DataCollectionType, string> =
  Object.fromEntries(DATA_COLLECTION_TYPE_OPTIONS.map(({ value, label }) => [value, label])) as Record<DataCollectionType, string>;

export const getDataCollectionTypeLabel = (value: unknown): string => {
  const dataType = String(value || 'text');
  return DATA_COLLECTION_TYPE_LABELS[dataType as DataCollectionType] || dataType;
};
