'use client';

import { Handle, NodeProps, Position } from 'reactflow';

type ListRow = { id?: string; title?: string; label?: string; description?: string; handleId?: string };
type ListSection = { title?: string; rows?: ListRow[] };
type ListNodeData = { label?: string; body_text?: string; sections?: ListSection[]; running?: boolean; isStart?: boolean; onChange?: (nodeId: string, patch: Record<string, unknown>) => void; onToggleStart?: (nodeId: string) => void };
const toHandleId = (value: string, fallback: string) => value.toLowerCase().trim().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '') || fallback;

export default function ListNode({ id, data, selected }: NodeProps) {
  const nodeData = (data || {}) as ListNodeData;
  const sections = nodeData.sections?.length ? nodeData.sections : [{ title: 'Opções', rows: [{ id: `${id}-row-1`, title: 'Opção 1', handleId: 'option_1' }] }];
  const rows = sections.flatMap((section, sectionIndex) => (section.rows || []).map((row, rowIndex) => ({ ...row, sectionIndex, rowIndex, title: row.title || row.label || `Opção ${rowIndex + 1}`, handleId: row.handleId || row.id || toHandleId(row.title || row.label || '', `row_${sectionIndex + 1}_${rowIndex + 1}`) })));
  const updateRow = (row: typeof rows[number], title: string) => {
    const next = sections.map((section, sectionIndex) => sectionIndex !== row.sectionIndex ? section : { ...section, rows: (section.rows || []).map((item, rowIndex) => rowIndex !== row.rowIndex ? item : { ...item, title, label: title, handleId: toHandleId(title, `row_${sectionIndex + 1}_${rowIndex + 1}`) }) });
    nodeData.onChange?.(id, { sections: next });
  };

  return (
    <div className={`flow-node ${selected ? 'is-selected' : ''} ${nodeData.running ? 'running' : ''}`} style={{ minWidth: 285, position: 'relative' }}>
      <div className="flow-node-header-bar" style={{ background: 'linear-gradient(90deg, #0f766e, #14b8a6)' }} />
      <Handle type="target" position={Position.Left} />
      <div className="flow-node-header" style={{ paddingTop: 14 }}>
        <div className="flow-node-type-dot" style={{ background: '#0f766e' }} />
        <span className="flow-node-title">{nodeData.label || 'Lista'}</span>
        <span className="flow-node-badge" style={{ background: '#ccfbf1', color: '#0f766e' }}>LIST</span>
        <button type="button" title={nodeData.isStart ? 'Bloco inicial' : 'Marcar como início'} onClick={(e) => { e.stopPropagation(); nodeData.onToggleStart?.(id); }} style={{ marginLeft: 'auto', background: nodeData.isStart ? '#16A34A' : 'transparent', border: nodeData.isStart ? 'none' : '1px solid #D1D5DB', borderRadius: 6, padding: '2px 6px', cursor: 'pointer', fontSize: 10, fontWeight: 600, color: nodeData.isStart ? '#fff' : '#9CA3AF' }}>{nodeData.isStart ? '▶ Início' : '▶'}</button>
      </div>
      <div className="flow-node-body" style={{ display: 'grid', gap: 8 }}>
        <textarea className="flow-node-field nodrag" value={nodeData.body_text || ''} onChange={(e) => nodeData.onChange?.(id, { body_text: e.target.value })} placeholder="Texto da lista" style={{ minHeight: 52, resize: 'vertical' }} />
        {rows.map((row) => <input key={`${row.sectionIndex}-${row.rowIndex}`} className="flow-node-field nodrag" value={row.title} onChange={(e) => updateRow(row, e.target.value)} placeholder={`Item ${row.rowIndex + 1}`} />)}
        <button type="button" className="flow-sidebar-button nodrag" onClick={() => nodeData.onChange?.(id, { sections: [{ ...sections[0], rows: [...(sections[0].rows || []), { id: `${id}-row-${rows.length + 1}`, title: `Opção ${rows.length + 1}`, handleId: `option_${rows.length + 1}` }] }, ...sections.slice(1)] })} style={{ width: '100%', justifyContent: 'center', fontSize: 12 }}>+ Adicionar item</button>
      </div>
      {rows.map((row, index) => <Handle key={row.handleId} id={row.handleId} type="source" position={Position.Right} style={{ top: 132 + index * 38, right: -6, width: 10, height: 10, background: '#fff', border: '2px solid #0f766e' }} />)}
    </div>
  );
}
