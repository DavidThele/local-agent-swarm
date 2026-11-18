import React from 'react';
import { X } from 'lucide-react';
import { AnalyzerReport } from '../types/swarm';

interface PostRunAnalyticsModalProps {
  report: AnalyzerReport | null;
  onClose: () => void;
}

export const PostRunAnalyticsModal: React.FC<PostRunAnalyticsModalProps> = ({ report, onClose }) => {
  if (!report) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm">
      <div className="w-full max-w-lg rounded-2xl border border-zinc-800 bg-[#111114] p-5 text-zinc-100 shadow-2xl">
        <div className="flex items-center justify-between border-b border-zinc-800 pb-3">
          <div>
            <h2 className="text-sm font-bold text-white">Swarm Analyzer Report</h2>
            <p className="font-mono text-[11px] text-zinc-500">
              {report.total_tokens.toLocaleString()} tokens • {report.total_duration_sec}s
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded p-1 text-zinc-500 hover:bg-zinc-800 hover:text-white"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="mt-4 grid grid-cols-3 gap-3">
          <div className="flex flex-col items-center justify-center rounded-xl border border-zinc-800 bg-[#0A0A0C] p-3">
            <span className="font-mono text-[10px] uppercase text-zinc-500">Efficiency</span>
            <span className="mt-1 font-mono text-2xl font-bold text-white">
              {report.efficiency_score}%
            </span>
          </div>

          <div className="col-span-2 rounded-xl border border-zinc-800 bg-[#0A0A0C] p-3">
            <span className="font-mono text-[10px] uppercase text-zinc-500">Bottlenecks</span>
            <ul className="mt-1.5 space-y-1 text-[11px] text-zinc-300">
              {report.bottlenecks.map((b, idx) => (
                <li key={idx} className="flex items-start gap-1.5">
                  <span className="text-[#FF6B00]">•</span>
                  <span>{b}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>

        <div className="mt-4 space-y-2">
          <span className="font-mono text-[10px] uppercase text-zinc-500">
            Memory &amp; Skill Commits
          </span>
          {report.memory_upgrades.map((up, i) => (
            <div key={i} className="rounded-xl border border-zinc-800 bg-[#0A0A0C] p-3">
              <div className="font-mono text-xs font-bold text-zinc-200">{up.target_file}</div>
              <p className="mt-0.5 text-xs text-zinc-400">{up.summary}</p>
              <pre className="mt-2 overflow-x-auto rounded border border-zinc-900 bg-black p-2 font-mono text-[11px] text-zinc-300">
                {up.diff_preview}
              </pre>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};