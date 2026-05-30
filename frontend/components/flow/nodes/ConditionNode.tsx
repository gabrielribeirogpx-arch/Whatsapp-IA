'use client';

import { useEffect, useMemo } from 'react';
import { NodeProps } from 'reactflow';
import CompactFlowNode from './CompactFlowNode';

type ConditionBranch = { id?: string; label?: string; handleId?: string };

type ConditionNodeData = {
  label?: string;
  condition?: string;
  conditions?: unknown;
  rules?: unknown;
  branches?: unknown;
  running?: boolean;
  isStart?: boolean;
  onToggleStart?: (nodeId: string) => void;
  hasValidationError?: boolean;
};

const toRuleLabels = (value: unknown): string[] => {
  if (Array.isArray(value)) {
    return value
      .map((item) => {
        if (typeof item === 'string') return item;
        if (item && typeof item === 'object') {
          const record = item as Record<string, unknown>;
          return String(record.label || record.value || record.keyword || record.condition || '').trim();
        }
        return '';
      })
      .filter(Boolean);
  }

  return String(value || '')
    .split(',')
    .map((rule) => rule.trim())
    .filter(Boolean);
};

const toConditionBranches = (value: unknown): ConditionBranch[] => {
  if (!Array.isArray(value)) return [];

  return value
    .map<ConditionBranch | null>((item, index) => {
      if (typeof item === 'string') {
        return { id: item, label: item, handleId: item };
      }

      if (item && typeof item === 'object') {
        const record = item as Record<string, unknown>;
        const label = String(record.label || record.name || record.title || `Saída ${index + 1}`);
        return {
          id: String(record.id || record.handleId || record.key || label),
          label,
          handleId: String(record.handleId || record.id || record.key || label),
        };
      }

      return null;
    })
    .filter((branch): branch is ConditionBranch => !!branch);
};

export default function ConditionNode({ id, data, selected }: NodeProps) {
  const nodeData = (data || {}) as ConditionNodeData;
  const rules = useMemo(
    () => toRuleLabels(nodeData.rules).concat(toRuleLabels(nodeData.conditions), toRuleLabels(nodeData.condition)),
    [nodeData.condition, nodeData.conditions, nodeData.rules],
  );
  const uniqueRules = useMemo(() => Array.from(new Set(rules)).filter(Boolean), [rules]);
  const branches = useMemo(() => {
    const parsedBranches = toConditionBranches(nodeData.branches);
    return parsedBranches.length
      ? parsedBranches
      : [{ id: 'true', label: 'Sim', handleId: 'true' }, { id: 'false', label: 'Não', handleId: 'false' }];
  }, [nodeData.branches]);

  useEffect(() => {
    console.debug('[NODE RERENDER]', { node_id: id, node_type: 'condition', selected, rule_count: uniqueRules.length, branch_count: branches.length });
  });

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
      summary={`${uniqueRules.length || branches.length} regras`}
      chips={uniqueRules.length ? uniqueRules.slice(0, 3) : branches.map((branch) => branch.label || branch.handleId || 'Saída')}
      isStart={nodeData.isStart}
      hasValidationError={nodeData.hasValidationError}
      onToggleStart={nodeData.onToggleStart}
      sourceHandles={branches.map((branch, index) => ({ id: branch.handleId || branch.id, label: branch.label, color: index === 0 ? '#16a34a' : '#dc2626' }))}
    />
  );
}
