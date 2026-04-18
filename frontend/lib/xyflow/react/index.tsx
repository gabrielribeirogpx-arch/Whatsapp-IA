import { CSSProperties, ReactNode } from 'react';

export type Node = {
  id: string;
  type?: string;
  data?: Record<string, unknown>;
  position: { x: number; y: number };
};

export type Edge = {
  id: string;
  source: string;
  target: string;
  label?: string;
};

type ReactFlowProps = {
  nodes: Node[];
  edges: Edge[];
  fitView?: boolean;
  children?: ReactNode;
};

const nodeStyle: CSSProperties = {
  border: '1px solid #d1d5db',
  borderRadius: 8,
  background: '#fff',
  padding: '8px 10px',
  minWidth: 120,
  boxShadow: '0 1px 2px rgba(0,0,0,0.06)',
};

export default function ReactFlow({ nodes, edges, children }: ReactFlowProps) {
  return (
    <div className="xyflow-fallback-canvas" aria-label="Flow Builder">
      {nodes.map((node) => (
        <div
          key={node.id}
          className="xyflow-fallback-node"
          style={{ ...nodeStyle, left: node.position.x, top: node.position.y }}
        >
          {(node.data?.label as string | undefined) || `Node ${node.id}`}
        </div>
      ))}

      <div className="xyflow-fallback-legend">
        <span>Nós: {nodes.length}</span>
        <span>Conexões: {edges.length}</span>
      </div>

      {children}
    </div>
  );
}

export function Background() {
  return null;
}

export function Controls() {
  return null;
}
