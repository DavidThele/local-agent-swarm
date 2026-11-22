import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Paperclip,
  Minimize2,
  History,
  Terminal,
  Plus,
  GripHorizontal,
} from 'lucide-react';
import {
  AgentNodeData,
  AnalyzerReport,
  CommandEvent,
  HITLBlocker,
  SessionSummary,
  SwarmSocketEvent,
} from './types/swarm';
import { swarmBridge, mockBridgeInstance } from './services/swarmBridge';
import { SwarmCanvas } from './components/SwarmCanvas';
import { TerminalDrawer } from './components/TerminalDrawer';
import { MascotOverlay } from './components/MascotOverlay';
import { PostRunAnalyticsModal } from './components/PostRunAnalyticsModal';
import { DevTestControls } from './components/DevTestControls';
import './styles/mascot.css';

const MAIN_COLUMN_WIDTH = 920;
const DRAWER_WIDTH = 400;

export const App: React.FC = () => {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [currentSession, setCurrentSession] = useState<SessionSummary>({
    chat_id: 'chat_new',
    title: 'Autonomous Session',
    workspace_root: '~/dev/local-swarm',
    overall_status: 'Idle',
    total_cost_usd: 0.0,
    timestamp: 'Now',
    chroma_status: 'Connected',
    connected_tools: ['Zsh', 'FileIO', 'ChromeCDP', 'ChromaDB'],
  });
  const [agents, setAgents] = useState<AgentNodeData[]>([]);
  const [logs, setLogs] = useState<CommandEvent[]>([]);
  const [blockers, setBlockers] = useState<HITLBlocker[]>([]);
  const [analyzerReport, setAnalyzerReport] = useState<AnalyzerReport | null>(null);

  // UI States
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [highlightErrorInDrawer, setHighlightErrorInDrawer] = useState(false);
  const [isMinimized, setIsMinimized] = useState(false);
  const [showReportModal, setShowReportModal] = useState(false);
  const [isCanvasPanning, setIsCanvasPanning] = useState(false);

  // Task Initiation & Acorn Collapse States
  const [promptText, setPromptText] = useState(
    'Refactor authentication middleware to rotate JWT refresh tokens and verify with pytest.'
  );
  const [attachments, setAttachments] = useState<string[]>(['src/auth/jwt.py']);
  const [isPromptCollapsedToAcorn, setIsPromptCollapsedToAcorn] = useState(false);
  const [burySequenceTrigger, setBurySequenceTrigger] = useState(0);
  const pendingPromptRef = useRef<{ prompt: string; attachments: string[] } | null>(null);

  // Explicit Left-Edge Coordinate Anchor (Opening the drawer only expands the right edge outward)
  const [windowPos, setWindowPos] = useState<{ x: number; y: number }>({ x: 80, y: 60 });
  const dragRef = useRef<{ startX: number; startY: number; origX: number; origY: number } | null>(
    null
  );
  const hasRootNode = agents.some((a) => a.type === 'Main');

  useEffect(() => {
    swarmBridge.fetchSessions().then(setSessions).catch(console.error);

    const unsubscribe = swarmBridge.connect((event: SwarmSocketEvent) => {
      switch (event.type) {
        case 'SESSION_UPDATED':
          setCurrentSession((prev) => ({ ...prev, ...event.payload }));
          break;
        case 'AGENT_SPAWNED':
          setAgents((prev) =>
            prev.some((a) => a.agent_id === event.payload.agent_id)
              ? prev
              : [...prev, event.payload]
          );
          break;
        case 'AGENT_UPDATED':
          setAgents((prev) =>
            prev.map((a) =>
              a.agent_id === event.payload.agent_id ? { ...a, ...event.payload } : a
            )
          );
          break;
        case 'COMMAND_LOGGED':
          setLogs((prev) => [...prev, event.payload]);
          break;
        case 'HITL_REQUIRED':
          setBlockers((prev) => [...prev, event.payload]);
          setAgents((prev) =>
            prev.map((a) =>
              a.agent_id === event.payload.agent_id
                ? { ...a, status: 'waiting', active_blocker: event.payload }
                : a
            )
          );
          break;
        case 'HITL_RESOLVED':
          setBlockers((prev) => prev.filter((b) => b.blocker_id !== event.payload.blocker_id));
          setAgents((prev) =>
            prev.map((a) =>
              a.agent_id === event.payload.agent_id
                ? { ...a, status: 'executing', active_blocker: null }
                : a
            )
          );
          break;
        case 'ANALYZER_REPORT':
          setAnalyzerReport(event.payload);
          setShowReportModal(true);
          break;
      }
    });

    return () => unsubscribe();
  }, []);

  const completedCount = agents.filter((a) => a.status === 'completed').length;
  const progressPercent =
    agents.length === 0 ? 15 : Math.min(100, Math.round((completedCount / agents.length) * 100));

  const activeHitlAgentId = blockers.length > 0 ? blockers[0].agent_id : null;
  const failedAgent = agents.find((a) => a.status === 'failed') || null;
  const selectedAgent = agents.find((a) => a.agent_id === selectedAgentId) || null;

  // Step 1: User clicks "Deploy Swarm" -> Collapse input box into acorn & trigger Byte
  const handleDeploySwarm = (e: React.FormEvent) => {
    e.preventDefault();
    if (!promptText.trim() || isPromptCollapsedToAcorn) return;

    setAgents([]);
    setLogs([]);
    setBlockers([]);
    setAnalyzerReport(null);
    setHighlightErrorInDrawer(false);

    pendingPromptRef.current = { prompt: promptText, attachments: [...attachments] };
    setIsPromptCollapsedToAcorn(true);
    setBurySequenceTrigger((c) => c + 1);
  };

  // Step 2: Callback fired by MascotOverlay ONLY after Byte finishes burying the acorn at canvas center
  const handleAcornBuryComplete = useCallback(() => {
    setIsPromptCollapsedToAcorn(false);
    if (pendingPromptRef.current) {
      swarmBridge.deploySwarm(
        pendingPromptRef.current.prompt,
        pendingPromptRef.current.attachments
      );
      pendingPromptRef.current = null;
    }
  }, []);

  const handleSelectAgentOnCanvas = (agentId: string) => {
    setSelectedAgentId(agentId);
    setHighlightErrorInDrawer(false);
    setIsDrawerOpen(true);
  };

  const handleInspectFailedNode = (agentId: string) => {
    setSelectedAgentId(agentId);
    setHighlightErrorInDrawer(true);
    setIsDrawerOpen(true);
  };

  const handleExpandFromKnock = () => {
    setIsMinimized(false);
    const targetId = activeHitlAgentId || failedAgent?.agent_id || null;
    if (targetId) {
      setSelectedAgentId(targetId);
      setIsDrawerOpen(true);
    }
  };

  const handleDragMouseDown = (e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest('button, input, textarea')) return;
    dragRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      origX: windowPos.x,
      origY: windowPos.y,
    };
    const onMove = (moveEvent: MouseEvent) => {
      if (!dragRef.current) return;
      setWindowPos({
        x: dragRef.current.origX + (moveEvent.clientX - dragRef.current.startX),
        y: dragRef.current.origY + (moveEvent.clientY - dragRef.current.startY),
      });
    };
    const onUp = () => {
      dragRef.current = null;
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  };

  return (
    <div className="relative h-screen w-screen overflow-hidden bg-[#060608] text-zinc-100 select-none">
      {/* =====================================================================
          LEFT-ANCHORED FLOATING OS WIDGET
          Opening the drawer expands width from 920px -> 1320px strictly to the right.
          ===================================================================== */}
      <div
        id="swarm-widget-root"
        style={{
          position: 'fixed',
          left: `${windowPos.x}px`,
          top: `${isMinimized ? Math.max(72, windowPos.y) : windowPos.y}px`,
          width: isMinimized
            ? '360px'
            : `${MAIN_COLUMN_WIDTH + (isDrawerOpen ? DRAWER_WIDTH : 0)}px`,
          height: isMinimized ? '10px' : '680px',
        }}
        className={` flex flex-col ${
          isMinimized
            ? `overflow-visible rounded-full border border-zinc-700 bg-[#111114] ${
                activeHitlAgentId || failedAgent ? 'peekaboo-bar-alert' : ''
              }`
            : 'overflow-visible rounded-2xl border border-zinc-800 bg-[#0A0A0C] shadow-[0_25px_70px_rgba(0,0,0,0.95)]'
        }`}
      >
        {/* Persistent Mascot Physics Layer */}
        <MascotOverlay
          isMinimized={isMinimized}
          isCanvasPanning={isCanvasPanning}
          burySequenceTrigger={burySequenceTrigger}
          hasRootNode={hasRootNode}
          activeHitlAgentId={activeHitlAgentId}
          failedAgentId={failedAgent?.agent_id || null}
          onBuryComplete={handleAcornBuryComplete}
          onInspectFailedNode={handleInspectFailedNode}
          onExpandFromKnock={handleExpandFromKnock}
        />

        {/* ===================================================================
            VIEW STATE 1: MINIMIZED — Exclusively a Slim Progress Bar
            (Byte sits flush on top of this bar via y: -56px)
            =================================================================== */}
        {isMinimized ? (
          <div
            onMouseDown={handleDragMouseDown}
            onClick={handleExpandFromKnock}
            title="Click bar to restore Swarm Command Center"
            className="h-full w-full cursor-pointer overflow-hidden rounded-full bg-zinc-900"
          >
            <div
              className="h-full rounded-full bg-[#FF6B00] transition-all duration-300"
              style={{ width: `${progressPercent}%` }}
            />
          </div>
        ) : (
          /* ===================================================================
             VIEW STATE 2: EXPANDED COMMAND CENTER
             =================================================================== */
          <div className="flex h-full w-full overflow-hidden rounded-2xl">
            {/* Fixed-Width Left Main Column (920px) — Never shifts when Drawer opens */}
            <div
              style={{ width: `${MAIN_COLUMN_WIDTH}px` }}
              className="flex h-full shrink-0 flex-col overflow-hidden"
            >
              {/* Minimal Monochrome Top Bar */}
              <header
                onMouseDown={handleDragMouseDown}
                className="flex h-11 shrink-0 cursor-grab items-center justify-between border-b border-zinc-800/80 bg-[#0A0A0C] px-3.5 active:cursor-grabbing"
              >
                <div className="flex items-center gap-2.5">
                  <button
                    onClick={() => setIsSidebarOpen(!isSidebarOpen)}
                    className={`rounded p-1.5 transition ${
                      isSidebarOpen
                        ? 'bg-zinc-800 text-white'
                        : 'text-zinc-500 hover:text-zinc-200'
                    }`}
                    title="Session History"
                  >
                    <History className="h-3.5 w-3.5" />
                  </button>
                  <span className="font-mono text-[11px] text-zinc-400">
                    {currentSession.workspace_root}
                  </span>
                </div>

                <div className="flex items-center gap-1 text-zinc-700">
                  <GripHorizontal className="h-3.5 w-3.5" />
                </div>

                <div className="flex items-center gap-2 pr-14">
                  {blockers.length > 0 && (
                    <button
                      onClick={() => {
                        setSelectedAgentId(blockers[0].agent_id);
                        setIsDrawerOpen(true);
                      }}
                      className="rounded border border-[#FF6B00] px-2 py-0.5 font-mono text-[10px] font-bold text-[#FF6B00]"
                    >
                      {blockers.length} Blocked
                    </button>
                  )}

                  <button
                    onClick={() => setIsDrawerOpen(!isDrawerOpen)}
                    className={`rounded p-1.5 transition ${
                      isDrawerOpen
                        ? 'bg-zinc-800 text-white'
                        : 'text-zinc-500 hover:text-zinc-200'
                    }`}
                    title="Toggle Terminal Drawer"
                  >
                    <Terminal className="h-3.5 w-3.5" />
                  </button>

                  <button
                    onClick={() => setIsMinimized(true)}
                    className="rounded p-1.5 text-zinc-500 transition hover:text-zinc-200"
                    title="Minimize to Slim Progress Bar"
                  >
                    <Minimize2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </header>

              {/* Simulation Harness */}
              <DevTestControls
                onForceMinimizeWithHitl={() => {
                  setIsMinimized(true);
                  setTimeout(() => {
                    mockBridgeInstance.emit({
                      type: 'HITL_REQUIRED',
                      payload: {
                        blocker_id: `blk_peek_${Date.now()}`,
                        agent_id: 'worker_db9',
                        blocker_type: 'Security',
                        prompt_text: 'Non-whitelisted Zsh command requires approval:',
                        command_preview: 'sudo rm -rf /tmp/swarm_cache/*',
                        timestamp: new Date().toLocaleTimeString(),
                      },
                    });
                  }, 350);
                }}
              />

              {/* Canvas + Optional Collapsible History Sidebar */}
              <div className="relative flex flex-1 overflow-hidden">
                {isSidebarOpen && (
                  <aside className="flex w-56 shrink-0 flex-col border-r border-zinc-800 bg-[#0d0d10]">
                    <div className="flex items-center justify-between border-b border-zinc-800 px-3 py-2">
                      <span className="font-mono text-[10px] uppercase text-zinc-500">
                        Sessions
                      </span>
                      <button
                        onClick={() => {
                          setAgents([]);
                          setLogs([]);
                          setBlockers([]);
                        }}
                        className="flex items-center gap-1 font-mono text-[10px] text-zinc-300 hover:text-[#FF6B00]"
                      >
                        <Plus className="h-3 w-3" /> Reset
                      </button>
                    </div>
                    <div className="flex-1 space-y-1 overflow-y-auto p-2">
                      {sessions.map((s) => (
                        <button
                          key={s.chat_id}
                          onClick={async () => {
                            const data = await swarmBridge.loadSession(s.chat_id);
                            setCurrentSession(data.session);
                            setAgents(data.agents);
                            setLogs(data.logs);
                          }}
                          className="w-full rounded-lg border border-zinc-800/60 bg-[#111114] p-2 text-left hover:border-zinc-700"
                        >
                          <p className="line-clamp-1 text-xs text-zinc-200">{s.title}</p>
                          <div className="mt-1 flex justify-between font-mono text-[10px] text-zinc-500">
                            <span>{s.overall_status}</span>
                            <span>${s.total_cost_usd.toFixed(2)}</span>
                          </div>
                        </button>
                      ))}
                    </div>
                  </aside>
                )}

                <div className="flex-1 overflow-hidden">
                  <SwarmCanvas
                    agents={agents}
                    selectedAgentId={selectedAgentId}
                    onSelectAgent={handleSelectAgentOnCanvas}
                    onPanStateChange={setIsCanvasPanning}
                  />
                </div>
              </div>

              {/* Bottom Task Input Dock (Visually collapses into an acorn on Deploy) */}
              <div
                data-mascot-target="task-input-box"
                className="border-t border-zinc-800/80 bg-[#0A0A0C] px-4 py-3"
              >
                <form
                  onSubmit={handleDeploySwarm}
                  className={`transition-all duration-500 ${
                    isPromptCollapsedToAcorn
                      ? 'scale-50 opacity-0 pointer-events-none'
                      : 'scale-100 opacity-100'
                  }`}
                >
                  {attachments.length > 0 && (
                    <div className="mb-2 flex flex-wrap gap-1.5">
                      {attachments.map((item) => (
                        <span
                          key={item}
                          className="rounded border border-zinc-800 bg-[#111114] px-2 py-0.5 font-mono text-[10px] text-zinc-400"
                        >
                          {item}
                          <button
                            type="button"
                            onClick={() =>
                              setAttachments(attachments.filter((a) => a !== item))
                            }
                            className="ml-1.5 text-zinc-500 hover:text-white"
                          >
                            ×
                          </button>
                        </span>
                      ))}
                    </div>
                  )}

                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => {
                        const next = prompt('Attach file path or chat_id:');
                        if (next && !attachments.includes(next)) {
                          setAttachments([...attachments, next]);
                        }
                      }}
                      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-zinc-800 bg-[#111114] text-zinc-400 hover:border-zinc-600 hover:text-white"
                    >
                      <Paperclip className="h-4 w-4" />
                    </button>

                    <input
                      type="text"
                      value={promptText}
                      onChange={(e) => setPromptText(e.target.value)}
                      placeholder="Define autonomous swarm task..."
                      className="h-9 flex-1 rounded-lg border border-zinc-800 bg-[#111114] px-3 text-xs text-white placeholder-zinc-600 focus:border-zinc-600 focus:outline-none"
                    />

                    <button
                      type="submit"
                      className="h-9 shrink-0 rounded-lg bg-[#FF6B00] px-4 text-xs font-bold text-black transition hover:brightness-110"
                    >
                      Deploy Swarm
                    </button>
                  </div>
                </form>
              </div>
            </div>

            {/* Outward Right-Expanding Terminal Drawer (400px) */}
            <TerminalDrawer
              isOpen={isDrawerOpen}
              selectedAgent={selectedAgent}
              allLogs={logs}
              activeBlockers={blockers}
              highlightError={highlightErrorInDrawer}
              onClose={() => setIsDrawerOpen(false)}
              onClearAgentFilter={() => setSelectedAgentId(null)}
              onResolveHitl={(blockerId, agentId, resolution) =>
                swarmBridge.resolveHitl(blockerId, agentId, resolution)
              }
            />
          </div>
        )}

        {showReportModal && (
          <PostRunAnalyticsModal
            report={analyzerReport}
            onClose={() => setShowReportModal(false)}
          />
        )}
      </div>
    </div>
  );
};

export default App;