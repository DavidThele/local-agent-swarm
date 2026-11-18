import React, { useState } from 'react';
import { ShieldAlert, HelpCircle, UserCheck, Check, X, Send, Play } from 'lucide-react';
import { HITLBlocker } from '../types/swarm';

interface HitlActionCenterProps {
  blocker: HITLBlocker;
  onResolve: (
    blockerId: string,
    agentId: string,
    resolution: { action: 'approve' | 'deny' | 'answer' | 'resume'; value?: string }
  ) => void;
}

export const HitlActionCenter: React.FC<HitlActionCenterProps> = ({ blocker, onResolve }) => {
  const [customInput, setCustomInput] = useState('');

  return (
    <div
      data-mascot-target="hitl-action-box"
      className="mx-3 my-2.5 rounded-xl border border-[#FF6B00] bg-[#111114] p-3.5"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {blocker.blocker_type === 'Security' && <ShieldAlert className="h-4 w-4 text-[#FF6B00]" />}
          {blocker.blocker_type === 'Question' && <HelpCircle className="h-4 w-4 text-[#FF6B00]" />}
          {blocker.blocker_type === 'Action' && <UserCheck className="h-4 w-4 text-[#FF6B00]" />}
          <span className="font-mono text-xs font-bold uppercase tracking-wider text-zinc-100">
            {blocker.agent_id}
          </span>
        </div>
        <span className="rounded border border-zinc-700 bg-zinc-900 px-1.5 py-0.5 font-mono text-[10px] text-[#FF6B00]">
          {blocker.blocker_type}
        </span>
      </div>

      <p className="mt-2 text-xs text-zinc-200">{blocker.prompt_text}</p>

      {blocker.blocker_type === 'Security' && (
        <div className="mt-2.5">
          {blocker.command_preview && (
            <pre className="overflow-x-auto rounded-lg border border-zinc-800 bg-[#0A0A0C] p-2.5 font-mono text-[11px] text-zinc-300">
              $ {blocker.command_preview}
            </pre>
          )}
          <div className="mt-3 flex items-center gap-2">
            <button
              onClick={() => onResolve(blocker.blocker_id, blocker.agent_id, { action: 'approve' })}
              className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-[#FF6B00] px-3 py-1.5 text-xs font-bold text-black transition hover:brightness-110"
            >
              <Check className="h-3.5 w-3.5" />
              Approve
            </button>
            <button
              onClick={() => onResolve(blocker.blocker_id, blocker.agent_id, { action: 'deny' })}
              className="flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-xs font-semibold text-zinc-300 transition hover:bg-zinc-800"
            >
              <X className="h-3.5 w-3.5" />
              Deny
            </button>
          </div>
        </div>
      )}

      {blocker.blocker_type === 'Question' && (
        <div className="mt-2.5 space-y-2">
          <div className="flex flex-wrap gap-1.5">
            {(blocker.options || []).map((opt) => (
              <button
                key={opt}
                onClick={() =>
                  onResolve(blocker.blocker_id, blocker.agent_id, { action: 'answer', value: opt })
                }
                className="rounded-lg border border-zinc-700 bg-zinc-900 px-2.5 py-1 text-xs text-zinc-200 transition hover:border-[#FF6B00] hover:text-[#FF6B00]"
              >
                {opt}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-1.5 pt-1">
            <input
              type="text"
              value={customInput}
              onChange={(e) => setCustomInput(e.target.value)}
              placeholder="Other..."
              className="flex-1 rounded-lg border border-zinc-800 bg-[#0A0A0C] px-2.5 py-1.5 text-xs text-white placeholder-zinc-600 focus:border-[#FF6B00] focus:outline-none"
            />
            <button
              disabled={!customInput.trim()}
              onClick={() =>
                onResolve(blocker.blocker_id, blocker.agent_id, {
                  action: 'answer',
                  value: customInput.trim(),
                })
              }
              className="rounded-lg bg-[#FF6B00] p-1.5 text-black transition hover:brightness-110 disabled:opacity-30"
            >
              <Send className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      )}

      {blocker.blocker_type === 'Action' && (
        <div className="mt-3">
          <button
            onClick={() => onResolve(blocker.blocker_id, blocker.agent_id, { action: 'resume' })}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-[#FF6B00] px-3 py-2 text-xs font-bold text-black transition hover:brightness-110"
          >
            <Play className="h-3.5 w-3.5 fill-current" />
            Resume Execution
          </button>
        </div>
      )}
    </div>
  );
};