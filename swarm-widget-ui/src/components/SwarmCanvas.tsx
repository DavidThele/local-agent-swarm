import React, { useMemo, useState } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  Node,
  Edge,
  ReactFlowProvider,
  BackgroundVariant,
} from '@xyflow/react';
import dagre from 'dagre';
import '@xyflow/react/dist/style.css';
import { Crown } from 'lucide-react';
import { AgentNodeData } from '../types/swarm';
import { AgentNodeCard, AgentFlowNodeData } from './AgentNodeCard';

interface SwarmCanvasProps {
  agents: AgentNodeData[];
  selectedAgentId: string | null;
  onSelectAgent: (agentId: string) => void;
  onPanStateChange: (isPanning: boolean) => void;
}

const nodeTypes = {
  agentCard: AgentNodeCard,
};

function computeDagreLayout(
  agents: AgentNodeData[],
  expandedIds: Set<string>,
  selectedAgentId: string | null,
  onCollapse: (id: string) => void
) {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  // Generous spacing so expanding a node from 52px circle to 260px card doesn't collide
  g.setGraph({ rankdir: 'TB', nodesep: 90, ranksep: 110 });

  agents.forEach((agent) => {
    g.setNode(agent.agent_id, { width: 120, height: 80 });
  });

  agents.forEach((agent) => {
    if (agent.parent_id) {
      g.setEdge(agent.parent_id, agent.agent_id);
    }
  });

  dagre.layout(g);

  const nodes: Node[] = agents.map((agent) => {
    const pos = g.node(agent.agent_id);
    const isExpanded = expandedIds.has(agent.agent_id);
    const offsetX = isExpanded ? 130 : 26;
    const offsetY = isExpanded ? 75 : 26;

    const flowData: AgentFlowNodeData = {
      ...agent,
      isExpanded,
      onCollapse,
    };

    return {
      id: agent.agent_id,
      type: 'agentCard',
      position: {
        x: (pos?.x || 0) - offsetX,
        y: (pos?.y || 0) - offsetY,
      },
      data: flowData,
      selected: agent.agent_id === selectedAgentId,
    };
  });

  const edges: Edge[] = agents
    .filter((a) => a.parent_id)
    .map((agent) => {
      const isExecuting = agent.status === 'executing' || agent.status === 'booting';
      const isFailed = agent.status === 'failed';
      return {
        id: `edge_${agent.parent_id}_${agent.agent_id}`,
        source: agent.parent_id!,
        target: agent.agent_id,
        type: 'smoothstep',
        animated: isExecuting,
        className: isExecuting ? 'swarm-edge-active' : '',
        style: {
          stroke: isFailed ? '#7f3737' : isExecuting ? '#71717a' : '#3f3f46',
          strokeWidth: 1.5,
        },
      };
    });

  return { nodes, edges };
}

const SwarmCanvasInner: React.FC<SwarmCanvasProps> = ({
  agents,
  selectedAgentId,
  onSelectAgent,
  onPanStateChange,
}) => {
  const [expandedNodeIds, setExpandedNodeIds] = useState<Set<string>>(new Set());

  const handleCollapse = (agentId: string) => {
    setExpandedNodeIds((prev) => {
      const next = new Set(prev);
      next.delete(agentId);
      return next;
    });
  };

  const { nodes, edges } = useMemo(
    () => computeDagreLayout(agents, expandedNodeIds, selectedAgentId, handleCollapse),
    [agents, expandedNodeIds, selectedAgentId]
  );

  // Strict Camera Lock: No automatic fitView or setCenter when nodes spawn, update, or fail.
  return (
    <div id="swarm-canvas-viewport" className="relative h-full w-full bg-[#0A0A0C]">
      {agents.length === 0 ? (
        <div className="flex h-full flex-col items-center justify-center px-6 text-center">
          <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-full border border-zinc-800 bg-[#111114]">
            <Crown className="h-4 w-4 text-zinc-500" />
          </div>
          <p className="max-w-xs text-xs text-zinc-500">
            Awaiting task deployment.
          </p>
        </div>
      ) : (
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          defaultViewport={{ x: 380, y: 70, zoom: 1 }}
          onMoveStart={() => onPanStateChange(true)}
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
          <Controls
            position="bottom-left"
            className="!border !border-zinc-800 !bg-[#121216] !fill-zinc-400 !shadow-none [&>button]:!border-zinc-800 [&>button]:!bg-[#121216] [&>button:hover]:!bg-zinc-800"
          />
        </ReactFlow>
      )}
    </div>
  );
};

export const SwarmCanvas: React.FC<SwarmCanvasProps> = (props) => (
  <ReactFlowProvider>
    <SwarmCanvasInner {...props} />
  </ReactFlowProvider>
);