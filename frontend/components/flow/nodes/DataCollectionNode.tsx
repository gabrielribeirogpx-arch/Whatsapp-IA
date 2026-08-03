'use client';

import { useEffect } from 'react';
import { NodeProps, useUpdateNodeInternals } from 'reactflow';
import CompactFlowNode from './CompactFlowNode';
import { DATA_COLLECTION_HANDLES } from '@/lib/dataCollectionHandles';

const HANDLE_PRESENTATION = {
  success: { label: '✓ Sucesso', color: '#16a34a' },
  invalid: { label: 'Inválido', color: '#dc2626' },
  cancel: { label: 'Cancelar', color: '#64748b' },
  timeout: { label: 'Timeout', color: '#d97706' },
} as const;
const OPTIONAL_TITLE = 'Esta saída é opcional. Caso nenhuma conexão seja criada, o Wazza executará automaticamente o comportamento padrão.';
const CLASSIC_HANDLES = DATA_COLLECTION_HANDLES.map((id) => ({
  id,
  ...HANDLE_PRESENTATION[id],
  ...(id === 'success' ? {} : { optional: true, title: OPTIONAL_TITLE }),
}));

const RETRY_HANDLES = CLASSIC_HANDLES.filter((handle) => handle.id !== 'invalid');
const ATTEMPTS_EXHAUSTED_HANDLE = {
  id: 'invalid',
  label: 'Tentativas esgotadas',
  color: '#dc2626',
  optional: true,
  title: 'Executada apenas após atingir o número máximo de tentativas configurado. Caso nenhuma conexão seja criada, o Wazza executará automaticamente o comportamento padrão.',
};

const TYPE_LABELS: Record<string, string> = {
  text: 'Texto', number: 'Número', email: 'E-mail', phone: 'Telefone', date: 'Data',
  time: 'Hora', cpf: 'CPF', cnpj: 'CNPJ', url: 'URL', currency: 'Moeda',
  boolean: 'Sim/Não', choice: 'Escolha',
};

type DataCollectionNodeData = {
  variable_name?: string;
  data_type?: string;
  required?: boolean;
  max_attempts?: number;
  auto_retry_invalid?: boolean;
  attempts_exceeded_behavior?: string;
  timeout_seconds?: number;
  running?: boolean;
  isStart?: boolean;
  onToggleStart?: (nodeId: string) => void;
  hasValidationError?: boolean;
};

const formatTimeout = (seconds: number) => {
  if (!seconds) return '';
  if (seconds % 60 === 0) return `${seconds / 60} min`;
  return `${seconds} s`;
};

export default function DataCollectionNode({ id, data, selected, isConnectable }: NodeProps) {
  const updateNodeInternals = useUpdateNodeInternals();
  const nodeData = (data || {}) as DataCollectionNodeData;
  const dataType = String(nodeData.data_type || 'text');
  const variableName = String(nodeData.variable_name || '').trim();
  const attempts = Number(nodeData.max_attempts || 3);
  const timeout = Number(nodeData.timeout_seconds || 0);
  const autoRetry = nodeData.auto_retry_invalid === true;
  const followsFlowAfterRetry = autoRetry && nodeData.attempts_exceeded_behavior !== 'end';
  const handles = autoRetry
    ? [...RETRY_HANDLES, ...(followsFlowAfterRetry ? [ATTEMPTS_EXHAUSTED_HANDLE] : [])]
    : CLASSIC_HANDLES;
  const structuralSignature = [variableName, dataType, nodeData.required, attempts, timeout, autoRetry, nodeData.attempts_exceeded_behavior].join('|');

  useEffect(() => {
    const frame = requestAnimationFrame(() => updateNodeInternals(id));
    return () => cancelAnimationFrame(frame);
  }, [id, structuralSignature, updateNodeInternals]);

  const summaryParts = [
    nodeData.required === false ? 'Opcional' : 'Obrigatório',
    autoRetry ? `${attempts} tentativa${attempts === 1 ? '' : 's'} automáticas` : 'Retry manual',
    autoRetry ? (followsFlowAfterRetry ? 'Esgotadas: segue o fluxo' : 'Esgotadas: encerra') : '',
    formatTimeout(timeout),
  ].filter(Boolean);

  return (
    <CompactFlowNode
      id={id}
      selected={selected}
      running={nodeData.running}
      title="Coleta de Dados"
      emoji="📥"
      badge={dataType.toUpperCase()}
      badgeTitle={`Tipo: ${TYPE_LABELS[dataType] || dataType}`}
      badgeTone={{ background: '#ecfdf5', color: '#047857' }}
      accent="linear-gradient(90deg,#10b981,#14b8a6)"
      summary={summaryParts.join(' · ')}
      metrics={[
        { label: 'Variável', value: variableName || 'Variável não definida', title: variableName || 'Variável não definida' },
        { label: 'Tipo', value: TYPE_LABELS[dataType] || dataType },
      ]}
      choiceLayout
      isStart={nodeData.isStart}
      hasValidationError={nodeData.hasValidationError}
      onToggleStart={nodeData.onToggleStart}
      statusLabel="Aguarda resposta"
      statusActive={!nodeData.hasValidationError}
      isConnectable={isConnectable}
      sourceHandles={handles}
    />
  );
}
