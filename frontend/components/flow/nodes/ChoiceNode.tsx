'use client';

import { useEffect, useMemo } from 'react';
import { NodeProps, useUpdateNodeInternals } from 'reactflow';
import CompactFlowNode, { truncateText } from './CompactFlowNode';

type ChoiceButton = { id?: string; label?: string; value?: string; handleId?: string; next?: string };
type ChoiceNodeData = {
  label?: string;
  content?: string;
  buttons?: ChoiceButton[];
  display_mode?: 'buttons' | 'list';
  displayMode?: 'buttons' | 'list';
  running?: boolean;
  isStart?: boolean;
  onToggleStart?: (nodeId: string) => void;
  hasValidationError?: boolean;
  options_mode?: 'fixed' | 'dynamic';
  options_variable?: string;
  result_variable?: string;
  label_field?: string;
  icon_field?: string;
  empty_message?: string;
  preview_options?: Array<Record<string, unknown>>;
};

const toHandleId = (value: string, fallback: string) => value.toLowerCase().trim().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '') || fallback;

export default function ChoiceNode({ id, data, selected, isConnectable }: NodeProps) {
  const updateNodeInternals = useUpdateNodeInternals();
  const nodeData = (data || {}) as ChoiceNodeData;
  const displayMode = nodeData.display_mode || nodeData.displayMode || 'buttons';
  const buttons = useMemo(() => (nodeData.buttons || []).map((button, index) => {
    const optionValue = button.value || button.label || button.id || `option_${index + 1}`;
    const label = button.label || button.value || `Opção ${index + 1}`;
    return { ...button, label, value: optionValue, handleId: button.handleId || toHandleId(optionValue, `option_${index + 1}`) };
  }), [nodeData.buttons]);

  const handleSignature = buttons.map((button) => button.handleId).join('|');
  const preview = (nodeData.preview_options || []).slice(0, 2);

  useEffect(() => {
    // React Flow measures handles separately from React's render. Re-measure only
    // after the new option row and its real <Handle> have reached the DOM.
    const frame = requestAnimationFrame(() => updateNodeInternals(id));
    return () => cancelAnimationFrame(frame);
  }, [handleSignature, id, updateNodeInternals]);


  useEffect(() => {
    buttons.forEach((button) => {
      console.debug('[CHOICE HANDLE RENDER]', {
        node_id: id,
        id: button.handleId,
        type: 'source',
        isConnectable,
        option_value: button.value,
      });
    });
  }, [buttons, id, isConnectable]);

  return (
    <CompactFlowNode
      id={id}
      selected={selected}
      running={nodeData.running}
      title={nodeData.options_mode === 'dynamic' ? 'Escolha Dinâmica' : 'Escolha'}
      emoji={nodeData.options_mode === 'dynamic' ? '⚡' : '🧭'}
      badge={nodeData.options_mode === 'dynamic' ? 'DINÂMICO' : displayMode === 'list' ? 'LISTA' : 'BOTÕES'}
      badgeTone={{ background: '#fff7ed', color: '#c2410c' }}
      accent="linear-gradient(90deg, #f97316, #fb923c)"
      summary={nodeData.options_mode === 'dynamic' ? `Origem: ${nodeData.options_variable || 'não definida'} ↓ Resultado: ${nodeData.result_variable || 'selected_slot'}` : truncateText(nodeData.content, 50, 'Escolha uma opção')}
      meta={nodeData.options_mode === 'dynamic' ? `${preview.map((item) => `${String(item[nodeData.icon_field || 'icon'] || '📅')} ${String(item[nodeData.label_field || 'label'] || '')}`).join(' · ') || 'Preview após o primeiro retorno'}${(nodeData.preview_options?.length || 0) > 2 ? ` (+${nodeData.preview_options!.length - 2})` : ''}` : displayMode === 'list' ? 'Lista WhatsApp' : 'Botões WhatsApp'}
      choiceLayout
      isStart={nodeData.isStart}
      hasValidationError={nodeData.hasValidationError}
      onToggleStart={nodeData.onToggleStart}
      analytics={(nodeData as any).analytics}
      statusLabel={nodeData.options_mode === 'dynamic' ? 'Opções via variável' : `${buttons.length} opções de saída`}
      isConnectable={isConnectable}
      sourceHandles={nodeData.options_mode === 'dynamic' ? [
        { id: 'selected', label: 'Selecionado', color: '#f97316' },
        { id: 'empty', label: 'Sem opções', color: '#dc2626' },
      ] : buttons.map((button) => ({ id: button.handleId, label: button.label, color: '#f97316', optionValue: button.value }))}
    />
  );
}
