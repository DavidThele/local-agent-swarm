import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  X,
  Terminal as TerminalIcon,
  Filter,
  AlertTriangle,
  ChevronRight,
  ChevronDown,
  CheckCircle2,
  HelpCircle,
  Sparkles,
  Loader2,
  FileBarChart2,
} from 'lucide-react';
import { AgentNodeData, AnalyzerReport, CommandEvent, HITLBlocker } from '../types/swarm';
import { HitlActionCenter } from './HitlActionCenter';

interface TerminalDrawerProps {
  isOpen: boolean;
  isFeedbackMode: boolean;
  selectedAgent: AgentNodeData | null;
  allLogs: CommandEvent[];
  activeBlockers: HITLBlocker[];
  highlightError: boolean;
  analyzerReport: AnalyzerReport | null;
  isAnalyzing: boolean;
  analyzerError: string | null;
  feedbackText: string;
  onFeedbackTextChange: (value: string) => void;
  onRunAnalyzer: (feedback: string) => void;
  onOpenAnalyzerModal: () => void;
  onClose: () => void;
  onClearAgentFilter: () => void;
  onResolveHitl: (
    blockerId: string,
    agentId: string,
    resolution: { action: 'approve' | 'deny' | 'answer' | 'resume'; value?: string }
  ) => void;
}

const KNOWN_XML_TAG_RE =
  /<\/?(?:Zsh|WriteFile|ReadFile|ListDirectory|Chrome|SearchDB|SpawnAgent|WaitForAgents|WaitForUser|MarkDone|Question|ChatTitle|HITLResolution|Summary|Result|Content|Instructions|DoD|Context|Thought|Plan|Answer|Command|Path|Query|Error|Output)\b[^>]*>/gi;

function isXmlFormattingError(log: CommandEvent): boolean {
  const combined = `${log.payload || ''}\n${log.result_output || ''}`;
  if (/xml|malformed|parse error|unclosed tag|invalid syntax|failed to parse/i.test(combined)) {
    return true;
  }
  return false;
}

function extractXmlAttributesPreview(payload: string): string {
  const attrs: string[] = [];
  const attrRe = /\b(path|file|query|id|role|mode|action|url|name)="([^"]+)"/gi;
  let match: RegExpExecArray | null;
  while ((match = attrRe.exec(payload)) !== null) {
    attrs.push(`${match[1]}=${match[2]}`);
  }
  return attrs.join(' ');
}

function stripXmlFormatting(raw: string, preserveXml: boolean): string {
  if (!raw) return '';
  if (preserveXml) return raw.trim();

  let cleaned = raw
    // Convert closing block-ish tags into newlines so inner sections stay readable
    .replace(
      /<\/(?:Summary|Result|Content|Instructions|DoD|Context|Thought|Plan|Answer|Command|Zsh|WriteFile|ReadFile|MarkDone|Question|SpawnAgent|WaitForAgents|SearchDB|Chrome|ListDirectory)>/gi,
      '\n'
    )
    .replace(KNOWN_XML_TAG_RE, '')
    // Strip any remaining simple XML-like tags (e.g. <Tag> or </Tag>) while avoiding code comparisons like a < b
    .replace(/<\/?[A-Z][A-Za-z0-9_]*(\s+[a-zA-Z0-9_-]+="[^"]*")*\s*\/?>/g, '')
    .replace(/^\[STATUS_DONE\]\s*/i, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim();

  if (!cleaned) {
    cleaned = extractXmlAttributesPreview(raw);
  }
  return cleaned;
}

function buildStepPreview(log: CommandEvent, preserveXml: boolean): string {
  const strippedPayload = stripXmlFormatting(log.payload || '', preserveXml);
  const firstLine = strippedPayload
    .split('\n')
    .map((l) => l.trim())
    .find(Boolean);

  if (firstLine) {
    return firstLine.length > 72 ? `${firstLine.slice(0, 72)}...` : firstLine;
  }

  const attrs = extractXmlAttributesPreview(log.payload || '');
  if (attrs) {
    return attrs.length > 72 ? `${attrs.slice(0, 72)}...` : attrs;
  }

  const strippedResult = stripXmlFormatting(log.result_output || '', preserveXml);
  const resLine = strippedResult
    .split('\n')
    .map((l) => l.trim())
    .find(Boolean);
  if (resLine) {
    return resLine.length > 72 ? `${resLine.slice(0, 72)}...` : resLine;
  }

  return log.command_type;
}

function isMarkDoneLog(log: CommandEvent): boolean {
  if (log.command_type === 'MarkDone') return true;
  if (/^\s*<MarkDone\b/i.test(log.payload || '')) return true;
  if (/^\[STATUS_DONE\]/i.test(log.result_output || '')) return true;
  return false;
}

export const TerminalDrawer: React.FC<TerminalDrawerProps> = ({
  isOpen,
  isFeedbackMode,
  selectedAgent,
  allLogs,
  activeBlockers,
  highlightError,
  analyzerReport,
  isAnalyzing,
  analyzerError,
  feedbackText,
  onFeedbackTextChange,
  onRunAnalyzer,
  onOpenAnalyzerModal,
  onClose,
  onClearAgentFilter,
  onResolveHitl,
}) => {
  const [showAllLogs, setShowAllLogs] = useState(false);
  const [toggledSteps, setToggledSteps] = useState<Record<string, boolean>>({});
  const bottomRef = useRef<HTMLDivElement>(null);

  const displayedLogs = useMemo(() => {
    return selectedAgent && !showAllLogs
      ? allLogs.filter((l) => l.agent_id === selectedAgent.agent_id)
      : allLogs;
  }, [allLogs, selectedAgent, showAllLogs]);

  const finalMarkDoneId = useMemo(() => {
    for (let i = displayedLogs.length - 1; i >= 0; i--) {
      if (isMarkDoneLog(displayedLogs[i])) {
        return displayedLogs[i].id;
      }
    }
    return null;
  }, [displayedLogs]);

  const relevantBlockers = selectedAgent
    ? activeBlockers.filter((b) => b.agent_id === selectedAgent.agent_id)
    : activeBlockers;

  useEffect(() => {
    if (isOpen && !isFeedbackMode) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [displayedLogs.length, isOpen, isFeedbackMode]);

  if (!isOpen) return null;

  const toggleStep = (id: string, currentlyExpanded: boolean) => {
    setToggledSteps((prev) => ({ ...prev, [id]: !currentlyExpanded }));
  };

  // =========================================================================
  // FEEDBACK & ANALYZER MODE (Triggered by '?' Node off Main Orchestrator)
  // =========================================================================
  if (isFeedbackMode) {
    return (
      <aside className="flex h-full w-[400px] shrink-0 flex-col border-l border-zinc-800 bg-[#0A0A0C] text-zinc-200">
        <div className="flex items-center justify-between border-b border-zinc-800 bg-[#111114] px-4 py-3">
          <div className="flex items-center gap-2">
            <HelpCircle className="h-4 w-4 text-[#FF6B00]" />
            <span className="font-mono text-xs font-bold text-zinc-100">
              Feedback &amp; Analyzer
            </span>
          </div>
          <button
            onClick={onClose}
            className="rounded p-1 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-200"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-4">
          <div className="rounded-xl border border-zinc-800/80 bg-[#111114] p-3.5">
            <p className="text-xs font-semibold text-zinc-100">
              Audit this run &amp; upgrade swarm memory
            </p>
            <p className="mt-1 text-[11px] leading-relaxed text-zinc-400">
              Share what went well, anything that felt off, or preferences you want codified into{' '}
              <span className="font-mono text-zinc-300">AGENTS.md</span> and reusable skills.
              Feedback is optional.
            </p>
          </div>

          <div className="flex flex-col gap-1.5">
            <label
              htmlFor="swarm-feedback-input"
              className="font-mono text-[10px] uppercase text-zinc-500"
            >
              User Feedback (Optional)
            </label>
            <textarea
              id="swarm-feedback-input"
              rows={6}
              value={feedbackText}
              onChange={(e) => onFeedbackTextChange(e.target.value)}
              disabled={isAnalyzing}
              placeholder="e.g., Prefer uv over pip, skip running e2e tests unless asked, or note a mistake a worker made..."
              className="w-full resize-none rounded-xl border border-zinc-800 bg-[#111114] p-3 text-xs leading-relaxed text-zinc-100 placeholder-zinc-600 focus:border-[#FF6B00]/70 focus:outline-none disabled:opacity-60"
            />
          </div>

          {analyzerError && (
            <div className="rounded-lg border border-[#8a3a3a] bg-[#1a1111] px-3 py-2 font-mono text-[11px] text-[#c77575]">
              {analyzerError}
            </div>
          )}

          <button
            type="button"
            disabled={isAnalyzing}
            onClick={() => onRunAnalyzer(feedbackText)}
            className="flex h-9 w-full items-center justify-center gap-2 rounded-lg bg-[#FF6B00] px-4 text-xs font-bold text-black transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isAnalyzing ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                <span>Analyzing Session...</span>
              </>
            ) : (
              <>
                <Sparkles className="h-3.5 w-3.5" />
                <span>Run Swarm Analyzer</span>
              </>
            )}
          </button>

          {analyzerReport && (
            <button
              type="button"
              onClick={onOpenAnalyzerModal}
              className="flex h-9 w-full items-center justify-center gap-2 rounded-lg border border-zinc-800 bg-[#111114] px-4 font-mono text-[11px] text-zinc-300 transition hover:border-zinc-600 hover:text-white"
            >
              <FileBarChart2 className="h-3.5 w-3.5 text-[#568f70]" />
              <span>View Last Report ({analyzerReport.efficiency_score})</span>
            </button>
          )}
        </div>
      </aside>
    );
  }

  // =========================================================================
  // AGENT / SWARM LOG STREAM MODE (Collapsed Steps + Highlighted MarkDone)
  // =========================================================================
  return (
    <aside className="flex h-full w-[400px] shrink-0 flex-col border-l border-zinc-800 bg-[#0A0A0C] text-zinc-200">
      <div className="flex items-center justify-between border-b border-zinc-800 bg-[#111114] px-4 py-3">
        <div className="flex items-center gap-2">
          <TerminalIcon className="h-4 w-4 text-zinc-400" />
          <span className="font-mono text-xs font-bold text-zinc-100">
            {selectedAgent && !showAllLogs ? selectedAgent.agent_id : 'Swarm Log Stream'}
          </span>
          <span className="rounded bg-zinc-900 px-1.5 py-0.5 font-mono text-[10px] text-zinc-500">
            {displayedLogs.length}
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

      <div className="flex-1 space-y-1.5 overflow-y-auto p-3 font-mono text-xs">
        {displayedLogs.length === 0 ? (
          <div className="flex h-32 items-center justify-center text-[11px] text-zinc-600">
            No steps logged yet.
          </div>
        ) : (
          displayedLogs.map((log) => {
            const isFinalDone = log.id === finalMarkDoneId;
            const isDone = isMarkDoneLog(log);
            const preserveXml = Boolean(log.is_error && isXmlFormattingError(log));
            const defaultExpanded = Boolean(log.is_error || isFinalDone);
            const isExpanded =
              toggledSteps[log.id] !== undefined ? toggledSteps[log.id] : defaultExpanded;

            const preview = buildStepPreview(log, preserveXml);
            const formattedPayload = stripXmlFormatting(log.payload || '', preserveXml);
            const formattedResult = stripXmlFormatting(log.result_output || '', preserveXml);

            const containerClass = log.is_error
              ? 'border-[#7f3737] bg-[#140e0e]'
              : isFinalDone
              ? 'border-[#3b6e52] bg-[#0f1713] shadow-[0_0_0_1px_rgba(59,110,82,0.2)]'
              : 'border-zinc-800/80 bg-[#111114]';

            return (
              <div key={log.id} className={`rounded-lg border transition-colors ${containerClass}`}>
                {/* Compact Collapsible Header Row */}
                <button
                  type="button"
                  onClick={() => toggleStep(log.id, isExpanded)}
                  className="flex w-full items-center gap-2 px-2.5 py-2 text-left hover:bg-white/[0.02]"
                >
                  <span className="shrink-0 text-zinc-500">
                    {isExpanded ? (
                      <ChevronDown className="h-3.5 w-3.5" />
                    ) : (
                      <ChevronRight className="h-3.5 w-3.5" />
                    )}
                  </span>

                  {isFinalDone ? (
                    <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-[#568f70]" />
                  ) : log.is_error ? (
                    <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-[#a85454]" />
                  ) : null}

                  <span
                    className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                      isFinalDone
                        ? 'bg-[#3b6e52]/25 text-[#75b892]'
                        : log.is_error
                        ? 'bg-[#7f3737]/25 text-[#c77575]'
                        : 'bg-zinc-900 text-zinc-300'
                    }`}
                  >
                    {isDone ? 'MarkDone' : log.command_type}
                  </span>

                  {(!selectedAgent || showAllLogs) && (
                    <span className="shrink-0 text-[10px] text-zinc-500">{log.agent_id}</span>
                  )}

                  <span className="min-w-0 flex-1 truncate text-[11px] text-zinc-400">
                    {preview}
                  </span>

                  <span className="shrink-0 text-[10px] text-zinc-600">{log.timestamp}</span>
                </button>

                {/* Expanded Details */}
                {isExpanded && (
                  <div className="border-t border-zinc-800/70 px-2.5 pb-2.5 pt-2">
                    {preserveXml && (
                      <div className="mb-1.5 text-[10px] font-semibold text-[#c77575]">
                        Raw XML preserved (formatting error detected)
                      </div>
                    )}

                    {formattedPayload && (
                      <pre
                        className={`overflow-x-auto whitespace-pre-wrap rounded p-2 text-[11px] leading-relaxed ${
                          isFinalDone
                            ? 'bg-[#0a100d] text-zinc-100'
                            : 'bg-[#0A0A0C] text-zinc-200'
                        }`}
                      >
                        {formattedPayload}
                      </pre>
                    )}

                    {formattedResult && formattedResult !== formattedPayload && (
                      <pre
                        className={`mt-1.5 overflow-x-auto whitespace-pre-wrap border-l-2 pl-2 text-[11px] leading-relaxed ${
                          log.is_error
                            ? 'border-[#8a3a3a] text-[#b86b6b]'
                            : isFinalDone
                            ? 'border-[#3b6e52] text-[#8dc7a6]'
                            : 'border-zinc-700 text-zinc-400'
                        }`}
                      >
                        {formattedResult}
                      </pre>
                    )}
                  </div>
                )}
              </div>
            );
          })
        )}
        <div ref={bottomRef} />
      </div>
    </aside>
  );
};
