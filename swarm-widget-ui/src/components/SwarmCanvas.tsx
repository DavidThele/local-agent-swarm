import React, { useMemo, useRef, useState } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  Node,
  Edge,
  ReactFlowProvider,
  BackgroundVariant,
  useReactFlow,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { AgentNodeData } from '../types/swarm';
import { AgentNodeCard, AgentFlowNodeData } from './AgentNodeCard';
import { RootEdge, clearAnimatedRoots } from './RootEdge';

interface SwarmCanvasProps {
  agents: AgentNodeData[];
  selectedAgentId: string | null;
  rootSpawnClientPos: { x: number; y: number } | null;
  onSelectAgent: (agentId: string) => void;
  onPanStateChange: (isPanning: boolean) => void;
}

const nodeTypes = {
  agentCard: AgentNodeCard,
};

const edgeTypes = {
  rootEdge: RootEdge,
};

function deterministicJitter(id: string, range: number): number {
  let h = 0;
  for (let i = 0; i < id.length; i++) {
    h = (h * 31 + id.charCodeAt(i)) | 0;
  }
  const norm = ((h >>> 0) % 1000) / 1000;
  return (norm - 0.5) * 2 * range;
}

const SwarmCanvasInner: React.FC<SwarmCanvasProps> = ({
  agents,
  selectedAgentId,
  rootSpawnClientPos,
  onSelectAgent,
  onPanStateChange,
}) => {
  const [expandedNodeIds, setExpandedNodeIds] = useState<Set<string>>(new Set());
  const { screenToFlowPosition } = useReactFlow();

  // Persistent world-space center coordinates per agent_id so existing nodes NEVER shift
  const positionsRef = useRef(new Map());

  const handleCollapse = (agentId: string) => {
    setExpandedNodeIds((prev) => {
      const next = new Set(prev);
      next.delete(agentId);
      return next;
    });
  };

  const isEmpty = agents.length === 0;

  const { nodes, edges } = useMemo(() => {
    if (agents.length === 0) {
      positionsRef.current.clear();
      clearAnimatedRoots();
      return { nodes: [] as Node[], edges: [] as Edge[] };
    }

    const activeIds = new Set(agents.map((a) => a.agent_id));
    for (const key of positionsRef.current.keys()) {
      if (!activeIds.has(key)) {
        positionsRef.current.delete(key);
      }
    }

    // Place ONLY newly spawned agents, keeping all existing coordinates immutable
    const unplaced = agents.filter((a) => !positionsRef.current.has(a.agent_id));
    if (unplaced.length > 0) {
      const depthOrder: Record<AgentNodeData['type'], number> = { Main: 0, Sub: 1, Worker: 2 };
      unplaced.sort((a, b) => depthOrder[a.type] - depthOrder[b.type]);

      const byParent = new Map<string, AgentNodeData[]>();
      unplaced.forEach((agent) => {
        const key = agent.parent_id ?? '__ROOT__';
        const list = byParent.get(key) || [];
        list.push(agent);
        byParent.set(key, list);
      });

      const isSpotOccupied = (x: number, y: number) => {
        for (const p of positionsRef.current.values()) {
          if (Math.abs(p.x - x) < 115 && Math.abs(p.y - y) < 85) {
            return true;
          }
        }
        return false;
      };

      byParent.forEach((batch, parentKey) => {
        if (parentKey === '__ROOT__') {
          // Convert exact acorn burial client pixel into React Flow world coordinates
          let rootWorldCenter = { x: 0, y: 0 };
          if (rootSpawnClientPos) {
            rootWorldCenter = screenToFlowPosition({
              x: rootSpawnClientPos.x,
              y: rootSpawnClientPos.y,
            });
          } else {
            // Fallback for loaded history sessions: center-top of visible canvas
            const canvasEl = document.getElementById('swarm-canvas-viewport');
            if (canvasEl) {
              const rect = canvasEl.getBoundingClientRect();
              rootWorldCenter = screenToFlowPosition({
                x: rect.left + rect.width * 0.5,
                y: rect.top + 115,
              });
            }
          }

          batch.forEach((rootAgent, idx) => {
            positionsRef.current.set(rootAgent.agent_id, {
              x: rootWorldCenter.x + idx * 240,
              y: rootWorldCenter.y,
            });
          });
          return;
        }

        const parentPos = positionsRef.current.get(parentKey) || { x: 0, y: 0 };
        const existingSiblings = agents.filter(
          (a) => a.parent_id === parentKey && positionsRef.current.has(a.agent_id)
        );

        const spacingX = batch[0]?.type === 'Sub' ? 260 : 165;
        const dropY = batch[0]?.type === 'Sub' ? 155 : 145;

        batch.forEach((child, idx) => {
          const jitterX = deterministicJitter(child.agent_id + '_x', 18);
          const jitterY = deterministicJitter(child.agent_id + '_y', 16);
          const y = parentPos.y + dropY + jitterY;

          let x: number;
          if (existingSiblings.length === 0) {
            x = parentPos.x + (idx - (batch.length - 1) / 2) * spacingX + jitterX;
          } else {
            const slotIndex = existingSiblings.length + idx;
            const side = slotIndex % 2 === 1 ? 1 : -1;
            const ring = Math.ceil(slotIndex / 2);
            x = parentPos.x + side * ring * spacingX + jitterX;
          }

          let attempts = 0;
          while (isSpotOccupied(x, y) && attempts < 12) {
            attempts++;
            const nudgeDir = attempts % 2 === 1 ? 1 : -1;
            x += nudgeDir * 85;
          }

          positionsRef.current.set(child.agent_id, { x, y });
        });
      });
    }

    const builtNodes: Node[] = agents.map((agent) => {
      const center = positionsRef.current.get(agent.agent_id) || { x: 0, y: 0 };
      const isExpanded = expandedNodeIds.has(agent.agent_id);
      const offsetX = isExpanded ? 130 : 26;
      const offsetY = isExpanded ? 75 : 26;

      const flowData: AgentFlowNodeData = {
        ...agent,
        isExpanded,
        onCollapse: handleCollapse,
      };

      return {
        id: agent.agent_id,
        type: 'agentCard',
        position: {
          x: center.x - offsetX,
          y: center.y - offsetY,
        },
        data: flowData,
        selected: agent.agent_id === selectedAgentId,
      };
    });

    const builtEdges: Edge[] = agents
      .filter((a) => a.parent_id)
      .map((agent) => {
        const isExecuting = agent.status === 'executing' || agent.status === 'booting';
        const isFailed = agent.status === 'failed';
        const isCompleted = agent.status === 'completed';
        return {
          id: `edge_${agent.parent_id}_${agent.agent_id}`,
          source: agent.parent_id!,
          target: agent.agent_id,
          type: 'rootEdge',
          style: {
            stroke: isFailed
              ? '#7f3737'
              : isCompleted
              ? '#3b6e52'
              : isExecuting
              ? '#71717a'
              : '#52525b',
            strokeWidth: 1.75,
          },
        };
      });

    return { nodes: builtNodes, edges: builtEdges };
  }, [agents, expandedNodeIds, selectedAgentId, rootSpawnClientPos, screenToFlowPosition]);

  return (
    <div id="swarm-canvas-viewport" className="relative h-full w-full bg-[#0A0A0C]">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        defaultViewport={{ x: 460, y: 90, zoom: 1 }}
        panOnDrag={!isEmpty}
        zoomOnScroll={!isEmpty}
        zoomOnPinch={!isEmpty}
        zoomOnDoubleClick={!isEmpty}
        panOnScroll={false}
        onMoveStart={() => {
          if (!isEmpty) onPanStateChange(true);
        }}
        onMoveEnd={() => onPanStateChange(false)}
        onNodeClick={(_, node) => {
          setExpandedNodeIds((prev) => {
            const next = new Set(prev);
            next.add(node.id);
            return next;
          });
          onSelectAgent(node.id);
        }}
        minZoom={0.25}
        maxZoom={1.75}
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={24} size={1} color="#222228" />
        {!isEmpty && (
          <Controls
            position="bottom-left"
            showInteractive={false}
            className="!border !border-zinc-800 !bg-[#121216] !fill-zinc-400 !shadow-none [&>button]:!border-zinc-800 [&>button]:!bg-[#121216] [&>button:hover]:!bg-zinc-800"
          />
        )}
      </ReactFlow>
    </div>
  );
};

export const SwarmCanvas: React.FC<SwarmCanvasProps> = (props) => (
  <ReactFlowProvider>
    <SwarmCanvasInner {...props} />
  </ReactFlowProvider>
);