import React, { useEffect, useRef, useState } from 'react';
import { X, Terminal as TerminalIcon, Filter, AlertTriangle } from 'lucide-react';
import { AgentNodeData, CommandEvent, HITLBlocker } from '../types/swarm';
import { HitlActionCenter } from './HitlActionCenter';

interface TerminalDrawerProps {
  isOpen: boolean;
  selectedAgent: AgentNodeData | null;
  allLogs: CommandEvent[];
  activeBlockers: HITLBlocker[];
  highlightError: boolean;
  onClose: () => void;
  onClearAgentFilter: () => void;
  onResolveHitl: (
    blockerId: string,
    agentId: string,
    resolution: { action: 'approve' | 'deny' | 'answer' | 'resume'; value?: string }
  ) => void;
}

export const TerminalDrawer: React.FC<TerminalDrawerProps> = ({
  isOpen,
  selectedAgent,
  allLogs,
  activeBlockers,
  highlightError,
  onClose,
  onClearAgentFilter,
  onResolveHitl,
}) => {
  const [showAllLogs, setShowAllLogs] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  const displayedLogs =
    selectedAgent && !showAllLogs
      ? allLogs.filter((l) => l.agent_id === selectedAgent.agent_id)
      : allLogs;

  const relevantBlockers = selectedAgent
    ? activeBlockers.filter((b) => b.agent_id === selectedAgent.agent_id)
    : activeBlockers;

  useEffect(() => {
    if (isOpen) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [displayedLogs.length, isOpen]);

  if (!isOpen) return null;

  return (
    <aside className="flex h-full w-[400px] shrink-0 flex-col border-l border-zinc-800 bg-[#0A0A0C] text-zinc-200">
      <div className="flex items-center justify-between border-b border-zinc-800 bg-[#111114] px-4 py-3">
        <div className="flex items-center gap-2">
          <TerminalIcon className="h-4 w-4 text-zinc-400" />
          <span className="font-mono text-xs font-bold text-zinc-100">
            {selectedAgent && !showAllLogs ? selectedAgent.agent_id : 'Swarm Log Stream'}
          </span>
        </div>

        <div className="flex items-center gap-1.5">
          {selectedAgent && (
            <button
              onClick={() => {
                setShowAllLogs(!showAllLogs);
                if (!showAllLogs) onClearAgentFilter();
              }}
              className="flex items-center gap-1 rounded border border-zinc-800 bg-zinc-900 px-2 py-1 font-mono text-[10px] text-zinc-400 hover:text-zinc-200"
            >
              <Filter className="h-3 w-3" />
              {showAllLogs ? 'All' : 'Isolated'}
            </button>
          )}
          <button
            onClick={onClose}
            className="rounded p-1 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-200"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      {relevantBlockers.map((blk) => (
        <HitlActionCenter key={blk.blocker_id} blocker={blk} onResolve={onResolveHitl} />
      ))}

      {selectedAgent?.status === 'failed' && selectedAgent.error_line && (
        <div
          className={`mx-3 mt-2.5 rounded-lg border p-3 font-mono text-xs ${
            highlightError
              ? 'border-[#8a3a3a] bg-[#1a1111] text-zinc-200'
              : 'border-zinc-800 bg-[#111114] text-zinc-400'
          }`}
        >
          <div className="mb-1 flex items-center gap-1.5 font-bold text-[#a85454]">
            <AlertTriangle className="h-3.5 w-3.5" />
            <span>STDERR FAULT</span>
          </div>
          <div className="break-all rounded bg-[#0A0A0C] p-2 text-[11px] text-zinc-300">
            {selectedAgent.error_line}
          </div>
        </div>
      )}

      <div className="flex-1 space-y-2.5 overflow-y-auto p-3.5 font-mono text-xs">
        {displayedLogs.map((log) => (
          <div
            key={log.id}
            className={`rounded-lg border p-2.5 ${
              log.is_error
                ? 'border-[#7f3737] bg-[#140e0e]'
                : 'border-zinc-800/80 bg-[#111114]'
            }`}
          >
            <div className="mb-1.5 flex items-center justify-between text-[10px] text-zinc-500">
              <div className="flex items-center gap-2">
                <span className="font-bold text-zinc-300">{log.agent_id}</span>
                <span className="text-zinc-500">&lt;{log.command_type}&gt;</span>
              </div>
              <span>{log.timestamp}</span>
            </div>

            <pre className="overflow-x-auto whitespace-pre-wrap rounded bg-[#0A0A0C] p-2 text-[11px] text-zinc-200">
              {log.payload}
            </pre>

            {log.result_output && (
              <pre
                className={`mt-1.5 overflow-x-auto whitespace-pre-wrap border-l-2 pl-2 text-[11px] ${
                  log.is_error
                    ? 'border-[#8a3a3a] text-[#b86b6b]'
                    : 'border-zinc-700 text-zinc-400'
                }`}
              >
                {log.result_output}
              </pre>
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </aside>
  );
};