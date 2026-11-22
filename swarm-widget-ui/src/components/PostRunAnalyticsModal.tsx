import React, { useState } from 'react';
import { X, ChevronDown, ChevronRight, FileText, Sparkles } from 'lucide-react';
import { AnalyzerReport } from '../types/swarm';

interface PostRunAnalyticsModalProps {
  report: AnalyzerReport | null;
  onClose: () => void;
}

export const PostRunAnalyticsModal: React.FC<PostRunAnalyticsModalProps> = ({
  report,
  onClose,
}) => {
  const [expandedModIndices, setExpandedModIndices] = useState<Set<number>>(new Set());

  if (!report) return null;

  const toggleMod = (idx: number) => {
    setExpandedModIndices((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  const bottleneckLines = (report.bottlenecks || '')
    .split('\n')
    .map((line) => line.replace(/^[-*•]\s*/, '').trim())
    .filter(Boolean);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm">
      <div className="flex max-h-[85vh] w-full max-w-xl flex-col rounded-2xl border border-zinc-800 bg-[#111114] text-zinc-100 shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-zinc-800 px-5 py-4">
          <div>
            <h2 className="text-sm font-bold text-white">Swarm Analyzer Report</h2>
            <p className="mt-0.5 font-mono text-[11px] text-zinc-500">
              {report.chat_id} • ${report.cost_usd.toFixed(4)} • {report.duration_sec}s
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded p-1 text-zinc-500 transition hover:bg-zinc-800 hover:text-white"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Scrollable Body */}
        <div className="flex-1 space-y-4 overflow-y-auto p-5">
          {report.user_feedback && (
            <div className="rounded-xl border border-zinc-800/80 bg-[#0d0d10] px-3.5 py-2.5">
              <span className="font-mono text-[10px] uppercase text-zinc-500">
                Your Feedback
              </span>
              <p className="mt-1 whitespace-pre-wrap text-xs leading-relaxed text-zinc-300">
                {report.user_feedback}
              </p>
            </div>
          )}

          {/* Efficiency Score + Bottlenecks */}
          <div className="grid grid-cols-3 gap-3">
            <div className="flex flex-col items-center justify-center rounded-xl border border-zinc-800 bg-[#0A0A0C] p-3.5">
              <span className="font-mono text-[10px] uppercase text-zinc-500">Efficiency</span>
              <span className="mt-1 font-mono text-2xl font-bold text-white">
                {report.efficiency_score || 'N/A'}
              </span>
            </div>

            <div className="col-span-2 rounded-xl border border-zinc-800 bg-[#0A0A0C] p-3.5">
              <span className="font-mono text-[10px] uppercase text-zinc-500">Bottlenecks</span>
              {bottleneckLines.length > 1 ? (
                <ul className="mt-1.5 space-y-1 text-xs leading-relaxed text-zinc-300">
                  {bottleneckLines.map((line, idx) => (
                    <li key={idx} className="flex items-start gap-1.5">
                      <span className="text-[#FF6B00]">•</span>
                      <span>{line}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-1.5 whitespace-pre-wrap text-xs leading-relaxed text-zinc-300">
                  {report.bottlenecks || 'No major bottlenecks detected.'}
                </p>
              )}
            </div>
          </div>

          {/* Recommendations */}
          <div className="rounded-xl border border-zinc-800 bg-[#0A0A0C] p-3.5">
            <span className="font-mono text-[10px] uppercase text-zinc-500">Recommendations</span>
            <p className="mt-1.5 whitespace-pre-wrap text-xs leading-relaxed text-zinc-300">
              {report.recommendations || 'None.'}
            </p>
          </div>

          {/* Applied Modifications (AGENTS.md / Skills) */}
          <div className="space-y-2">
            <span className="font-mono text-[10px] uppercase text-zinc-500">
              Applied Memory &amp; Skill Updates ({report.modifications.length})
            </span>

            {report.modifications.length === 0 ? (
              <div className="rounded-xl border border-zinc-800/70 bg-[#0A0A0C] px-3.5 py-3 font-mono text-[11px] text-zinc-500">
                No changes were written to AGENTS.md or skills.
              </div>
            ) : (
              report.modifications.map((mod, idx) => {
                const isExpanded = expandedModIndices.has(idx);
                return (
                  <div
                    key={`${mod.target_file}_${idx}`}
                    className="rounded-xl border border-zinc-800 bg-[#0A0A0C] p-3"
                  >
                    <button
                      type="button"
                      onClick={() => toggleMod(idx)}
                      className="flex w-full items-start justify-between gap-2 text-left"
                    >
                      <div className="flex items-start gap-2">
                        {mod.type === 'UpsertSkill' ? (
                          <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#FF6B00]" />
                        ) : (
                          <FileText className="mt-0.5 h-3.5 w-3.5 shrink-0 text-zinc-400" />
                        )}
                        <div>
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-xs font-bold text-zinc-200">
                              {mod.target_file}
                            </span>
                            <span className="rounded border border-zinc-800 bg-zinc-900 px-1.5 py-0.5 font-mono text-[9px] uppercase text-zinc-400">
                              {mod.type === 'UpsertSkill' ? 'Skill' : 'Memory'}
                            </span>
                          </div>
                          <p className="mt-0.5 text-xs text-zinc-400">{mod.summary}</p>
                        </div>
                      </div>
                      <span className="mt-0.5 text-zinc-500">
                        {isExpanded ? (
                          <ChevronDown className="h-3.5 w-3.5" />
                        ) : (
                          <ChevronRight className="h-3.5 w-3.5" />
                        )}
                      </span>
                    </button>

                    {isExpanded && mod.content && (
                      <pre className="mt-2.5 max-h-56 overflow-auto whitespace-pre-wrap rounded border border-zinc-900 bg-black p-2.5 font-mono text-[11px] text-zinc-300">
                        {mod.content}
                      </pre>
                    )}
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
