'use client';

import { memo, ReactNode, useEffect, useMemo } from 'react';
import type { CSSProperties } from 'react';
import { Handle, Position } from 'reactflow';

type SourceHandle = {
  id?: string;
  label?: string;
  title?: string;
  color?: string;
  optionValue?: string;
};

type NodeMetric = {
  label: string;
  value: string | number;
  title?: string;
  icon?: ReactNode;
  tone?: string;
};

export function NodeStatus({ active = true, label }: { active?: boolean; label: string }) {
  return (
    <>
      <span className={`flow-node-status-dot ${active ? 'is-on' : 'is-off'}`} />
      <span>{label}</span>
    </>
  );
}

type CompactFlowNodeProps = {
  id: string;
  selected?: boolean;
  running?: boolean;
  title: string;
  emoji: string;
  badge: string;
  badgeTitle?: string;
  badgeTone: { background: string; color: string };
  accent: string;
  summary: string;
  meta?: string;
  chips?: string[];
  metrics?: NodeMetric[];
  footer?: ReactNode;
  premium?: boolean;
  sourceHandles?: SourceHandle[];
  isStart?: boolean;
  hasValidationError?: boolean;
  onToggleStart?: (nodeId: string) => void;
  isConnectable?: boolean;
  analytics?: { entered?: number; conversions?: number; dropoff?: number; dropoff_rate?: number } | null;
  statusLabel?: string;
  statusActive?: boolean;
  choiceLayout?: boolean;
};

function CompactFlowNode({
  id,
  selected,
  running,
  title,
  emoji,
  badge,
  badgeTitle,
  badgeTone,
  accent,
  summary,
  meta,
  chips = [],
  metrics = [],
  footer,
  premium,
  sourceHandles,
  isStart,
  hasValidationError,
  onToggleStart,
  isConnectable = true,
  analytics,
  statusLabel,
  statusActive = true,
  choiceLayout = false,
}: CompactFlowNodeProps) {
  const handles = useMemo(() => (sourceHandles?.length ? sourceHandles : [{ id: undefined, color: accent }]), [accent, sourceHandles]);
  const handleStep = handles.length > 1 ? 30 : 0;
  const firstHandleTop = handles.length > 1 ? 80 - ((handles.length - 1) * handleStep) / 2 : 64;

  useEffect(() => {
    console.debug('[NODE RERENDER]', { node_id: id, title, selected, handle_count: handles.length, isConnectable });
  });

  return (
    <div
      className={`flow-node flow-node-compact ${choiceLayout ? 'choice-node' : ''} ${premium ? 'flow-node-premium' : ''} ${selected ? 'is-selected' : ''} ${running ? 'running' : ''}`}
      style={{
        '--flow-node-accent': accent,
        border: hasValidationError ? '2px solid #dc2626' : undefined,
        boxShadow: hasValidationError ? '0 12px 30px rgba(220, 38, 38, 0.12)' : undefined,
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
        <div className="flow-node-header-glow" aria-hidden="true" />
        <span className="flow-node-emoji" aria-hidden="true"><span>{emoji}</span></span>
        <div className="flow-node-compact-title-wrap">
          <span className="flow-node-title">{title}</span>
          {meta ? <span className="flow-node-compact-meta">{meta}</span> : null}
        </div>
        <div className="flow-node-header-actions">
          {hasValidationError ? <span role="img" aria-label="Node com configuração inválida" title="Configuração incompleta. Abra o node para corrigir." style={{ color: '#dc2626' }}>⚠</span> : null}
          <span className="flow-node-badge" style={badgeTone} title={badgeTitle}>{badge}</span>
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
        {metrics.length > 0 ? (
          <div className="flow-node-metric-row">
            {metrics.slice(0, 4).map((metric) => (
              <span key={`${metric.label}-${metric.value}`} className="flow-node-metric" title={metric.title}>
                {metric.icon ? <span className="flow-node-metric-icon" aria-hidden="true">{metric.icon}</span> : null}
                <span className="flow-node-metric-copy">
                  <span className="flow-node-metric-label">{metric.label}</span>
                  <strong style={metric.tone ? { color: metric.tone } : undefined}>{metric.value}</strong>
                </span>
              </span>
            ))}
          </div>
        ) : null}
        {choiceLayout && handles.length > 0 ? (
          <div className="choice-option-list" aria-label="Opções de saída">
            {handles.map((handle) => (
              <div
                key={`${handle.id || 'default'}-choice-row`}
                className="choice-option-row nodrag nopan"
                style={{ '--flow-handle-color': handle.color || accent } as CSSProperties}
              >
                <span className="choice-option-content" title={handle.title || handle.label}>{handle.label || 'Opção'}</span>
                <span className="choice-option-handle-slot">
                  <Handle
                    id={handle.id}
                    type="source"
                    position={Position.Right}
                    title={handle.title || handle.label}
                    className="flow-node-handle flow-node-source-handle choice-option-handle nodrag nopan"
                    isConnectable={isConnectable}
                    data-option-value={handle.optionValue}
                    style={{
                      right: -7,
                      width: 12,
                      height: 12,
                      background: '#fff',
                      border: '2px solid #cbd5e1',
                      boxShadow: '0 2px 6px rgba(15, 23, 42, 0.10)',
                      transition: 'transform 160ms ease, box-shadow 160ms ease, border-color 160ms ease',
                      '--flow-handle-transform': 'translate(0, -50%)',
                      borderRadius: '50%',
                      cursor: 'crosshair',
                      pointerEvents: isConnectable ? 'auto' : 'none',
                      zIndex: 30,
                    } as CSSProperties}
                  />
                </span>
              </div>
            ))}
          </div>
        ) : chips.length > 0 ? (
          <div className="flow-node-chip-row">
            {chips.slice(0, 3).map((chip) => (
              <span key={chip} className="flow-node-chip">{chip}</span>
            ))}
            {chips.length > 3 ? <span className="flow-node-chip flow-node-chip-muted">+{chips.length - 3}</span> : null}
          </div>
        ) : null}
      </div>

      {footer || statusLabel ? <div className="flow-node-footer">{footer || <NodeStatus active={statusActive} label={statusLabel || 'Pronto'} />}</div> : null}

      {!choiceLayout && handles.map((handle, index) => (
        <div
          key={`${handle.id || 'default'}-wrap`}
          className="flow-node-source-slot nodrag nopan"
          style={{
            top: firstHandleTop + index * handleStep,
            '--flow-handle-color': handle.color || accent,
          } as CSSProperties}
        >
          {handle.label ? <span className="flow-node-source-label" title={handle.title || handle.label}>{handle.label}</span> : null}
          <Handle
            key={handle.id || 'default'}
            id={handle.id}
            type="source"
            position={Position.Right}
            title={handle.title || handle.label}
            className="flow-node-handle flow-node-source-handle nodrag nopan"
            isConnectable={isConnectable}
            data-option-value={handle.optionValue}
            style={{
              right: -6,
              width: 12,
              height: 12,
              background: '#fff',
              border: '2px solid #cbd5e1',
              boxShadow: '0 2px 6px rgba(15, 23, 42, 0.10)',
              transition: 'transform 160ms ease, box-shadow 160ms ease, border-color 160ms ease',
              '--flow-handle-transform': 'translate(0, -50%)',
              borderRadius: '50%',
              cursor: 'crosshair',
              pointerEvents: isConnectable ? 'auto' : 'none',
              zIndex: 30,
            } as CSSProperties}
          />
        </div>
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
