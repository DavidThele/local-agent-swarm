import React from 'react';
import { Handle, Position, NodeProps } from '@xyflow/react';
import {
  Crown,
  GitFork,
  Cog,
  ShieldAlert,
  HelpCircle,
  UserCheck,
  Minimize2,
  OctagonX,
} from 'lucide-react';
import { AgentNodeData } from '../types/swarm';

export interface AgentFlowNodeData extends AgentNodeData {
  isExpanded?: boolean;
  isCancelling?: boolean;
  onCollapse?: (agentId: string) => void;
  onCancelAgent?: (agentId: string) => void;
}

export const AgentNodeCard: React.FC<NodeProps> = ({ data }) => {
  const node = data as unknown as AgentFlowNodeData;
  const isExpanded = Boolean(node.isExpanded);
  const hasBlocker = Boolean(node.active_blocker);

  // Desaturated status rings only upon completion or failure (or orange pulse if HITL blocked)
  const circleRingClass =
    node.status === 'failed'
      ? 'border-[#8a3a3a] ring-2 ring-[#8a3a3a]/40 bg-[#141112]'
      : node.status === 'completed'
      ? 'border-[#3b6e52] ring-2 ring-[#3b6e52]/35 bg-[#111513]'
      : hasBlocker
      ? 'border-[#FF6B00] ring-2 ring-[#FF6B00]/40 bg-[#161311]'
      : 'border-zinc-700 bg-[#141418] hover:border-zinc-500';

  const RoleIcon =
    node.type === 'Main' ? Crown : node.type === 'Sub' ? GitFork : Cog;

  // =========================================================================
  // STATE 1: UNEXPANDED (DEFAULT) — Minimalist 52x52 Circle with Vector Icon
  // =========================================================================
  if (!isExpanded) {
    return (
      <div
        data-agent-node={node.agent_id}
        className={`relative flex h-[52px] w-[52px] cursor-pointer items-center justify-center rounded-full border transition-colors ${circleRingClass}`}
      >
        {node.type !== 'Main' && (
          <Handle
            type="target"
            position={Position.Top}
            className="!h-1.5 !w-1.5 !border-0 !bg-zinc-600"
          />
        )}

        <RoleIcon
          className={`h-5 w-5 ${
            hasBlocker
              ? 'text-[#FF6B00]'
              : node.status === 'failed'
              ? 'text-[#a85454]'
              : node.status === 'completed'
              ? 'text-[#568f70]'
              : 'text-zinc-300'
          }`}
          strokeWidth={1.75}
        />

        {node.type !== 'Worker' && (
          <Handle
            type="source"
            position={Position.Bottom}
            className="!h-1.5 !w-1.5 !border-0 !bg-zinc-600"
          />
        )}

        {node.type === 'Main' && (
          <Handle
            id="feedback-out"
            type="source"
            position={Position.Right}
            className="!h-1.5 !w-1.5 !border-0 !bg-transparent"
          />
        )}
      </div>
    );
  }

  // =========================================================================
  // STATE 2: EXPANDED (ON-CLICK) — Detailed Monochrome Glassmorphic Card
  // =========================================================================
  const statusLabel =
    node.status === 'booting'
      ? 'Thinking'
      : node.status === 'executing'
      ? 'Executing'
      : node.status === 'waiting'
      ? 'Waiting'
      : node.status === 'completed'
      ? 'Completed'
      : 'Failed';

  const cardBorderClass =
    node.status === 'failed'
      ? 'border-[#8a3a3a] bg-[#141112]/95'
      : node.status === 'completed'
      ? 'border-[#3b6e52] bg-[#111413]/95'
      : hasBlocker
      ? 'border-[#FF6B00] bg-[#161311]/95'
      : 'border-zinc-700 bg-[#141418]/95';

  return (
    <div
      data-agent-node={node.agent_id}
      className={`relative w-[260px] rounded-xl border p-3.5 text-left backdrop-blur-md shadow-2xl ${cardBorderClass}`}
    >
      {node.type !== 'Main' && (
        <Handle
          type="target"
          position={Position.Top}
          className="!h-2 !w-2 !border-0 !bg-zinc-500"
        />
      )}

      {/* Card Header */}
      <div className="flex items-center justify-between gap-2 border-b border-zinc-800 pb-2">
        <div className="flex items-center gap-2">
          <RoleIcon className="h-4 w-4 text-zinc-300" />
          <span className="font-mono text-xs font-bold text-zinc-100">
            {node.agent_id}
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="rounded border border-zinc-700 bg-zinc-900 px-1.5 py-0.5 font-mono text-[10px] uppercase text-zinc-400">
            {statusLabel}
          </span>
          {node.onCollapse && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                node.onCollapse?.(node.agent_id);
              }}
              className="rounded p-0.5 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-200"
              title="Collapse to minimal circle"
            >
              <Minimize2 className="h-3 w-3" />
            </button>
          )}
        </div>
      </div>

      {/* Instructions & DoD */}
      <p className="mt-2.5 line-clamp-2 text-[11px] leading-relaxed text-zinc-300">
        {node.instructions}
      </p>
      <p className="mt-1 line-clamp-1 font-mono text-[10px] text-zinc-500">
        DoD: {node.dod}
      </p>

      {/* Active HITL Banner */}
      {hasBlocker && node.active_blocker && (
        <div className="mt-2.5 flex items-center gap-1.5 rounded border border-[#FF6B00]/50 bg-[#FF6B00]/10 px-2 py-1 text-[10px] font-medium text-[#FF6B00]">
          {node.active_blocker.blocker_type === 'Security' && (
            <ShieldAlert className="h-3.5 w-3.5 shrink-0" />
          )}
          {node.active_blocker.blocker_type === 'Question' && (
            <HelpCircle className="h-3.5 w-3.5 shrink-0" />
          )}
          {node.active_blocker.blocker_type === 'Action' && (
            <UserCheck className="h-3.5 w-3.5 shrink-0" />
          )}
          <span className="truncate">{node.active_blocker.prompt_text}</span>
        </div>
      )}

      {/* Footer Metrics */}
      <div className="mt-3 flex items-center justify-between border-t border-zinc-800/80 pt-2 font-mono text-[10px] text-zinc-400">
        <span>${node.cost_usd.toFixed(2)}</span>
        <span className={node.status === 'failed' ? 'text-[#a85454]' : 'text-zinc-400'}>
          Iter {node.current_iteration}/{node.max_iterations}
        </span>
      </div>

      {/* Cancel Processing Action (Active Nodes Only) */}
      {node.onCancelAgent &&
        node.status !== 'completed' &&
        node.status !== 'failed' && (
          <button
            type="button"
            disabled={Boolean(node.isCancelling)}
            onClick={(e) => {
              e.stopPropagation();
              node.onCancelAgent?.(node.agent_id);
            }}
            title={
              node.type === 'Main'
                ? 'Cancel entire swarm run'
                : node.type === 'Sub'
                ? 'Cancel this sub-orchestrator and all workers spawned off it'
                : 'Cancel this worker and report error to parent orchestrator'
            }
            className="mt-2.5 flex w-full items-center justify-center gap-1.5 rounded-lg border border-[#8a3a3a]/80 bg-[#1a1010] px-2.5 py-1.5 font-mono text-[10px] font-semibold text-[#c77575] transition hover:border-[#a85454] hover:bg-[#241313] hover:text-[#e39696] disabled:cursor-not-allowed disabled:opacity-50"
          >
            <OctagonX className="h-3 w-3" />
            <span>{node.isCancelling ? 'Cancelling...' : 'Cancel Processing'}</span>
          </button>
        )}

      {node.type !== 'Worker' && (
        <Handle
          type="source"
          position={Position.Bottom}
          className="!h-2 !w-2 !border-0 !bg-zinc-500"
        />
      )}

      {node.type === 'Main' && (
        <Handle
          id="feedback-out"
          type="source"
          position={Position.Right}
          className="!h-2 !w-2 !border-0 !bg-transparent"
        />
      )}
    </div>
  );
};