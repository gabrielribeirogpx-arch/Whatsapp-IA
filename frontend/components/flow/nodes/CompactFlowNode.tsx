'use client';

import { memo, useEffect, useMemo } from 'react';
import type { CSSProperties } from 'react';
import { Handle, Position } from 'reactflow';

type SourceHandle = {
  id?: string;
  label?: string;
  color?: string;
  optionValue?: string;
};

type CompactFlowNodeProps = {
  id: string;
  selected?: boolean;
  running?: boolean;
  title: string;
  emoji: string;
  badge: string;
  badgeTone: { background: string; color: string };
  accent: string;
  summary: string;
  meta?: string;
  chips?: string[];
  sourceHandles?: SourceHandle[];
  isStart?: boolean;
  hasValidationError?: boolean;
  onToggleStart?: (nodeId: string) => void;
  isConnectable?: boolean;
  analytics?: { entered?: number; conversions?: number; dropoff?: number; dropoff_rate?: number } | null;
};

function CompactFlowNode({
  id,
  selected,
  running,
  title,
  emoji,
  badge,
  badgeTone,
  accent,
  summary,
  meta,
  chips = [],
  sourceHandles,
  isStart,
  hasValidationError,
  onToggleStart,
  isConnectable = true,
  analytics,
}: CompactFlowNodeProps) {
  const handles = useMemo(() => (sourceHandles?.length ? sourceHandles : [{ id: undefined, color: accent }]), [accent, sourceHandles]);
  const handleStep = handles.length > 1 ? 24 : 0;
  const firstHandleTop = handles.length > 1 ? 68 - ((handles.length - 1) * handleStep) / 2 : 55;

  useEffect(() => {
    console.debug('[NODE RERENDER]', { node_id: id, title, selected, handle_count: handles.length, isConnectable });
  });

  return (
    <div
      className={`flow-node flow-node-compact ${selected ? 'is-selected' : ''} ${running ? 'running' : ''}`}
      style={{
        '--flow-node-accent': accent,
        border: hasValidationError ? '2px solid #dc2626' : undefined,
        boxShadow: hasValidationError ? '0 0 0 4px rgba(220,38,38,0.15)' : analytics ? `0 0 0 ${Math.min(12, 3 + Math.log10(Number(analytics.entered || 1)) * 4)}px ${Number(analytics.dropoff_rate || 0) > 30 ? 'rgba(245,158,11,0.22)' : 'rgba(34,197,94,0.18)'}` : undefined,
      } as CSSProperties}
    >
      <div className="flow-node-header-bar" style={{ background: accent }} />
      <Handle
        type="target"
        position={Position.Left}
        className="flow-node-handle flow-node-target-handle"
        isConnectable={isConnectable}
        style={{
          '--flow-handle-color': accent,
          '--flow-handle-transform': 'translate(0, -50%)',
          pointerEvents: isConnectable ? 'auto' : 'none',
        } as CSSProperties}
      />

      <div className="flow-node-compact-header">
        <span className="flow-node-emoji" aria-hidden="true">{emoji}</span>
        <div className="flow-node-compact-title-wrap">
          <span className="flow-node-title">{title}</span>
          {meta ? <span className="flow-node-compact-meta">{meta}</span> : null}
        </div>
        <span className="flow-node-badge" style={badgeTone}>{badge}</span>
        <button
          type="button"
          className={`flow-node-start-button nodrag ${isStart ? 'is-start' : ''}`}
          title={isStart ? 'Bloco inicial' : 'Marcar como início'}
          onClick={(event) => {
            event.stopPropagation();
            onToggleStart?.(id);
          }}
        >
          {isStart ? '▶ Início' : '▶'}
        </button>
      </div>

      {analytics ? (
        <div style={{ margin: "8px 12px 0", display: "flex", gap: 6, flexWrap: "wrap", fontSize: 10, fontWeight: 700, color: "#0f172a" }}>
          <span style={{ borderRadius: 999, background: "#dcfce7", padding: "3px 7px" }}>{analytics.entered || 0} entradas</span>
          {Number(analytics.conversions || 0) > 0 ? <span style={{ borderRadius: 999, background: "#dbeafe", padding: "3px 7px" }}>{analytics.conversions} conversões</span> : null}
          {Number(analytics.dropoff || 0) > 0 ? <span style={{ borderRadius: 999, background: "#fef3c7", padding: "3px 7px" }}>{analytics.dropoff} abandono</span> : null}
        </div>
      ) : null}

      <div className="flow-node-compact-body">
        <p className="flow-node-summary">{summary || 'Clique para configurar no painel lateral'}</p>
        {chips.length > 0 ? (
          <div className="flow-node-chip-row">
            {chips.slice(0, 3).map((chip) => (
              <span key={chip} className="flow-node-chip">{chip}</span>
            ))}
            {chips.length > 3 ? <span className="flow-node-chip flow-node-chip-muted">+{chips.length - 3}</span> : null}
          </div>
        ) : null}
      </div>

      {handles.map((handle, index) => (
        <Handle
          key={handle.id || 'default'}
          id={handle.id}
          type="source"
          position={Position.Right}
          title={handle.label}
          className="flow-node-handle flow-node-source-handle nodrag nopan"
          isConnectable={isConnectable}
          data-option-value={handle.optionValue}
          style={{
            top: firstHandleTop + index * handleStep,
            right: -8,
            width: 14,
            height: 14,
            background: '#fff',
            border: `2px solid ${handle.color || accent}`,
            boxShadow: '0 4px 10px rgba(15, 23, 42, 0.18), 0 0 0 2px rgba(255, 255, 255, 0.9)',
            transition: 'transform 120ms ease, box-shadow 120ms ease, border-color 120ms ease',
            '--flow-handle-transform': 'translate(0, -50%)',
            borderRadius: '50%',
            cursor: 'crosshair',
            pointerEvents: isConnectable ? 'auto' : 'none',
            zIndex: 30,
          } as CSSProperties}
        />
      ))}
    </div>
  );
}

export const truncateText = (value: unknown, maxLength: number, fallback = 'Não configurado') => {
  const text = String(value || '').trim();
  if (!text) return fallback;
  return text.length > maxLength ? `${text.slice(0, maxLength).trim()}...` : text;
};

export const fileNameFromUrl = (value: unknown, fallback: string) => {
  const text = String(value || '').trim();
  if (!text) return fallback;
  return text.split('/').pop()?.split('?')[0] || text;
};

export default memo(CompactFlowNode);
