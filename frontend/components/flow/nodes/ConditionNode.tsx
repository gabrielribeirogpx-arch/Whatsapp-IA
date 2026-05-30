'use client';

import { NodeProps } from 'reactflow';
import CompactFlowNode from './CompactFlowNode';

type ConditionNodeData = {
  label?: string;
  condition?: string;
  running?: boolean;
  isStart?: boolean;
  onToggleStart?: (nodeId: string) => void;
  hasValidationError?: boolean;
};

export default function ConditionNode({ id, data, selected }: NodeProps) {
  const nodeData = (data || {}) as ConditionNodeData;
  const rules = String(nodeData.condition || '').split(',').map((rule) => rule.trim()).filter(Boolean);

  return (
    <CompactFlowNode
      id={id}
      selected={selected}
      running={nodeData.running}
      title="Condição"
      emoji="🔀"
      badge="IF"
      badgeTone={{ background: '#fef3c7', color: '#92400e' }}
      accent="linear-gradient(90deg, #d97706, #f59e0b)"
      summary={`${rules.length || 2} regras`}
      chips={rules.length ? rules.slice(0, 3) : ['Sim', 'Não']}
      isStart={nodeData.isStart}
      hasValidationError={nodeData.hasValidationError}
      onToggleStart={nodeData.onToggleStart}
      sourceHandles={[{ id: 'true', label: 'Sim', color: '#16a34a' }, { id: 'false', label: 'Não', color: '#dc2626' }]}
    />
  );
}
