import { CSSProperties, ReactNode, useCallback, useState } from 'react';

export type XYPosition = { x: number; y: number };

export type Node = {
  id: string;
  type?: string;
  data?: Record<string, unknown>;
  position: XYPosition;
};

export type Edge = {
  id: string;
  source: string;
  target: string;
  label?: string;
  data?: Record<string, unknown>;
};

export type Connection = {
  source?: string | null;
  target?: string | null;
  sourceHandle?: string | null;
  targetHandle?: string | null;
};

export type OnConnect = (connection: Connection) => void;
export type OnNodesChange = (changes: unknown[]) => void;
export type OnEdgesChange = (changes: unknown[]) => void;

export type NodeProps<TData = Record<string, unknown>> = {
  id: string;
  data: TData;
};

export enum Position {
  Left = 'left',
  Right = 'right',
  Top = 'top',
  Bottom = 'bottom',
}

type HandleProps = {
  type: 'source' | 'target';
  position: Position;
  id?: string;
  style?: CSSProperties;
};

export function Handle({ type, position, id, style }: HandleProps) {
  return <span data-handle-type={type} data-handle-position={position} data-handle-id={id} style={{ display: 'none', ...style }} />;
}

type ReactFlowProps = {
  nodes: Node[];
  edges: Edge[];
  fitView?: boolean;
  children?: ReactNode;
  nodeTypes?: Record<string, (props: NodeProps) => ReactNode>;
  onConnect?: OnConnect;
  onNodesChange?: OnNodesChange;
  onEdgesChange?: OnEdgesChange;
};

const nodeStyle: CSSProperties = {
  border: '1px solid #d1d5db',
  borderRadius: 8,
  background: '#fff',
  padding: '8px 10px',
  minWidth: 120,
  boxShadow: '0 1px 2px rgba(0,0,0,0.06)',
};

export default function ReactFlow({ nodes, edges, children, nodeTypes }: ReactFlowProps) {
  return (
    <div className="xyflow-fallback-canvas" aria-label="Flow Builder">
      {nodes.map((node) => {
        const CustomNode = node.type && nodeTypes ? nodeTypes[node.type] : null;

        return (
          <div
            key={node.id}
            className="xyflow-fallback-node"
            style={{ ...nodeStyle, left: node.position.x, top: node.position.y }}
          >
            {CustomNode ? <CustomNode id={node.id} data={(node.data || {}) as Record<string, unknown>} /> : ((node.data?.label as string | undefined) || `Node ${node.id}`)}
          </div>
        );
      })}

      <div className="xyflow-fallback-legend">
        <span>Nós: {nodes.length}</span>
        <span>Conexões: {edges.length}</span>
      </div>

      {children}
    </div>
  );
}

export function addEdge(connection: Connection, edges: Edge[]): Edge[] {
  if (!connection.source || !connection.target) {
    return edges;
  }

  const id = `${connection.source}-${connection.target}-${Math.random().toString(36).slice(2, 8)}`;
  return [...edges, { id, source: connection.source, target: connection.target }];
}

export function useNodesState(initialNodes: Node[]): [Node[], (updater: Node[] | ((prev: Node[]) => Node[])) => void, OnNodesChange] {
  const [nodes, setNodes] = useState<Node[]>(initialNodes);

  const updateNodes = useCallback((updater: Node[] | ((prev: Node[]) => Node[])) => {
    setNodes((prev) => (typeof updater === 'function' ? (updater as (prev: Node[]) => Node[])(prev) : updater));
  }, []);

  const onNodesChange = useCallback<OnNodesChange>(() => {
    // fallback sem drag and drop real
  }, []);

  return [nodes, updateNodes, onNodesChange];
}

export function useEdgesState(initialEdges: Edge[]): [Edge[], (updater: Edge[] | ((prev: Edge[]) => Edge[])) => void, OnEdgesChange] {
  const [edges, setEdges] = useState<Edge[]>(initialEdges);

  const updateEdges = useCallback((updater: Edge[] | ((prev: Edge[]) => Edge[])) => {
    setEdges((prev) => (typeof updater === 'function' ? (updater as (prev: Edge[]) => Edge[])(prev) : updater));
  }, []);

  const onEdgesChange = useCallback<OnEdgesChange>(() => {
    // fallback sem drag and drop real
  }, []);

  return [edges, updateEdges, onEdgesChange];
}

export function Background() {
  return null;
}

export function Controls() {
  return null;
}
