import React from 'react';
import { mockBridgeInstance, USE_MOCK_BRIDGE } from '../services/swarmBridge';

interface DevTestControlsProps {
  onForceMinimizeWithHitl: () => void;
}

export const DevTestControls: React.FC<DevTestControlsProps> = ({ onForceMinimizeWithHitl }) => {
  if (!USE_MOCK_BRIDGE) return null;

  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-zinc-800/80 bg-[#0d0d10] px-3 py-1 font-mono text-[10px] text-zinc-400">
      <span>TEST HARNESS</span>
      <div className="flex flex-wrap items-center gap-1.5">
        <button
          onClick={() =>
            mockBridgeInstance.emit({
              type: 'HITL_REQUIRED',
              payload: {
                blocker_id: `blk_q_${Date.now()}`,
                agent_id: 'worker_fs4',
                blocker_type: 'Question',
                prompt_text: 'Select target schema adapter:',
                options: ['Zustand', 'Redux', 'Context'],
                timestamp: new Date().toLocaleTimeString(),
              },
            })
          }
          className="rounded border border-zinc-800 bg-zinc-900 px-2 py-0.5 hover:border-zinc-600 hover:text-white"
        >
          +Question
        </button>
        <button
          onClick={() => {
            const errLine =
              'FATAL: MaxIterationCapExceeded (10/10) — SyntaxError in build/bundle.js:142';
            mockBridgeInstance.emit({
              type: 'AGENT_UPDATED',
              payload: {
                agent_id: 'worker_cdp2',
                status: 'failed',
                current_iteration: 10,
                error_line: errLine,
              },
            });
          }}
          className="rounded border border-zinc-800 bg-zinc-900 px-2 py-0.5 hover:border-zinc-600 hover:text-white"
        >
          +FatalError
        </button>
        <button
          onClick={onForceMinimizeWithHitl}
          className="rounded border border-zinc-800 bg-zinc-900 px-2 py-0.5 hover:border-zinc-600 hover:text-white"
        >
          +PeekabooKnock
        </button>
      </div>
    </div>
  );
};