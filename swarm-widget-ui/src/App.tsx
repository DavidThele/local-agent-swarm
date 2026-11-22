import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Paperclip,
  Minimize2,
  History,
  Terminal,
  Plus,
  GripHorizontal,
  FolderOpen,
  Check,
  X,
  FileCode2,
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
import { SwarmCanvas, FEEDBACK_NODE_ID } from './components/SwarmCanvas';
import { TerminalDrawer } from './components/TerminalDrawer';
import { MascotOverlay } from './components/MascotOverlay';
import { PostRunAnalyticsModal } from './components/PostRunAnalyticsModal';
import { DevTestControls } from './components/DevTestControls';
import './styles/mascot.css';

const MAIN_COLUMN_WIDTH = 920;
const DRAWER_WIDTH = 400;

const postNativeWindowMsg = (payload: Record<string, unknown>) => {
  const handler = (
    window as unknown as {
      webkit?: { messageHandlers?: { windowBridge?: { postMessage: (msg: string) => void } } };
    }
  ).webkit?.messageHandlers?.windowBridge;
  if (handler) {
    handler.postMessage(JSON.stringify(payload));
    return true;
  }
  return false;
};

const isNativeWindow =
  typeof window !== 'undefined' &&
  Boolean(
    (window as unknown as { webkit?: { messageHandlers?: { windowBridge?: unknown } } }).webkit
      ?.messageHandlers?.windowBridge
  );

export const App: React.FC = () => {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [currentSession, setCurrentSession] = useState<SessionSummary>({
    chat_id: '',
    title: 'New Session',
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

  // Workspace Editing State
  const [isEditingWorkspace, setIsEditingWorkspace] = useState(false);
  const [workspaceDraft, setWorkspaceDraft] = useState('');
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);

  // Task Initiation & Acorn Collapse States
  const [promptText, setPromptText] = useState('');
  const [attachments, setAttachments] = useState<string[]>([]);
  const [isPromptCollapsedToAcorn, setIsPromptCollapsedToAcorn] = useState(false);
  const [burySequenceTrigger, setBurySequenceTrigger] = useState(0);
  const [rootSpawnClientPos, setRootSpawnClientPos] = useState<{ x: number; y: number } | null>(
    null
  );

  // @ File Autocomplete States
  const promptInputRef = useRef<HTMLInputElement>(null);
  const [mentionRange, setMentionRange] = useState<{
    start: number;
    end: number;
    query: string;
  } | null>(null);
  const [mentionSuggestions, setMentionSuggestions] = useState<string[]>([]);
  const [mentionActiveIdx, setMentionActiveIdx] = useState(0);

  // Post-Run Feedback & Analyzer States
  const [feedbackText, setFeedbackText] = useState('');
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analyzerError, setAnalyzerError] = useState<string | null>(null);

  // Event Buffer: Agents start immediately on Deploy; events buffer until Byte finishes burying the acorn
  const isAwaitingBuryRef = useRef<boolean>(false);
  const bufferedEventsRef = useRef<SwarmSocketEvent[]>([]);
  const flushTimersRef = useRef<number[]>([]);

  // Browser-preview floating window drag state (unused in native macOS window mode)
  const [windowPos, setWindowPos] = useState<{ x: number; y: number }>({ x: 80, y: 60 });
  const dragRef = useRef<{ startX: number; startY: number; origX: number; origY: number } | null>(
    null
  );

  const hasRootNode = agents.some((a) => a.type === 'Main');

  const clearFlushTimers = useCallback(() => {
    flushTimersRef.current.forEach((id) => window.clearTimeout(id));
    flushTimersRef.current = [];
  }, []);

  const applySwarmEvent = useCallback((event: SwarmSocketEvent) => {
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
  }, []);

  useEffect(() => {
    swarmBridge.fetchSessions().then(setSessions).catch(console.error);
    swarmBridge
      .fetchConfig()
      .then((cfg) => {
        setCurrentSession((prev) => ({
          ...prev,
          workspace_root: cfg.workspace_root,
          chroma_status: cfg.chroma_status,
          connected_tools: cfg.connected_tools,
        }));
      })
      .catch(console.error);

    const unsubscribe = swarmBridge.connect((event: SwarmSocketEvent) => {
      if (isAwaitingBuryRef.current) {
        bufferedEventsRef.current.push(event);
      } else {
        applySwarmEvent(event);
      }
    });

    return () => {
      unsubscribe();
      clearFlushTimers();
    };
  }, [applySwarmEvent, clearFlushTimers]);

  // Expand native macOS window strictly to the right when Terminal Drawer toggles
  useEffect(() => {
    if (!isNativeWindow) return;
    postNativeWindowMsg({
      type: 'resize_right',
      width: MAIN_COLUMN_WIDTH + (isDrawerOpen ? DRAWER_WIDTH : 0),
    });
  }, [isDrawerOpen]);

  const completedCount = agents.filter((a) => a.status === 'completed').length;
  const progressPercent =
    agents.length === 0 ? 15 : Math.min(100, Math.round((completedCount / agents.length) * 100));

  const activeHitlAgentId = blockers.length > 0 ? blockers[0].agent_id : null;
  const failedAgent = agents.find((a) => a.status === 'failed') || null;
  const isFeedbackMode = selectedAgentId === FEEDBACK_NODE_ID;
  const selectedAgent =
    !isFeedbackMode && selectedAgentId
      ? agents.find((a) => a.agent_id === selectedAgentId) || null
      : null;
  const showFeedbackNode =
    hasRootNode &&
    currentSession.overall_status === 'Success' &&
    agents.length > 0 &&
    agents.every((a) => a.status === 'completed');

  // Query workspace files whenever an active @mention token is being typed
  useEffect(() => {
    if (!mentionRange) {
      setMentionSuggestions([]);
      setMentionActiveIdx(0);
      return;
    }

    let cancelled = false;
    const timer = window.setTimeout(() => {
      swarmBridge
        .listWorkspaceFiles(mentionRange.query)
        .then((files) => {
          if (cancelled) return;
          const filtered = files.filter((f) => !attachments.includes(f));
          setMentionSuggestions(filtered);
          setMentionActiveIdx(0);
        })
        .catch(() => {
          if (!cancelled) setMentionSuggestions([]);
        });
    }, 60);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [mentionRange, attachments, currentSession.workspace_root]);

  const detectMentionAtCursor = (text: string, cursorPos: number | null) => {
    if (cursorPos === null) {
      setMentionRange(null);
      return;
    }
    const beforeCursor = text.slice(0, cursorPos);
    const match = beforeCursor.match(/(?:^|\s)@([^\s]*)$/);
    if (!match) {
      setMentionRange(null);
      return;
    }
    const query = match[1];
    const start = cursorPos - query.length - 1; // index of '@'
    setMentionRange({ start, end: cursorPos, query });
  };

  const handleSelectMentionFile = (filePath: string) => {
    if (!mentionRange) return;
    const before = promptText.slice(0, mentionRange.start);
    const after = promptText.slice(mentionRange.end);
    const joined =
      before.endsWith(' ') && after.startsWith(' ')
        ? before + after.slice(1)
        : (before + after).replace(/^\s+/, '');
    setPromptText(joined);
    setAttachments((prev) => (prev.includes(filePath) ? prev : [...prev, filePath]));
    setMentionRange(null);
    setMentionSuggestions([]);

    const nextCaret = Math.min(mentionRange.start, joined.length);
    window.requestAnimationFrame(() => {
      promptInputRef.current?.focus();
      promptInputRef.current?.setSelectionRange(nextCaret, nextCaret);
    });
  };

  const handlePickFiles = async () => {
    try {
      const res = await swarmBridge.pickFiles();
      if (!res.cancelled && res.files.length > 0) {
        setAttachments((prev) => {
          const next = [...prev];
          for (const f of res.files) {
            if (!next.includes(f)) next.push(f);
          }
          return next;
        });
      }
    } catch (err) {
      console.error('File picker failed:', err);
    }
  };

  const handleRunAnalyzer = async (feedback: string) => {
    if (!currentSession.chat_id || isAnalyzing) return;
    setIsAnalyzing(true);
    setAnalyzerError(null);
    try {
      const report = await swarmBridge.runAnalyzer(currentSession.chat_id, feedback);
      setAnalyzerReport(report);
      setShowReportModal(true);
    } catch (err) {
      setAnalyzerError(err instanceof Error ? err.message : 'Analyzer failed');
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleCreateNewSession = async () => {
    clearFlushTimers();
    isAwaitingBuryRef.current = false;
    bufferedEventsRef.current = [];

    const fresh = await swarmBridge.createNewSession();
    setCurrentSession(fresh);
    setAgents([]);
    setLogs([]);
    setBlockers([]);
    setAnalyzerReport(null);
    setFeedbackText('');
    setAnalyzerError(null);
    setSelectedAgentId(null);
    setRootSpawnClientPos(null);
    setIsDrawerOpen(false);
    swarmBridge.fetchSessions().then(setSessions).catch(console.error);
  };

  const handleApplyWorkspace = async () => {
    if (!workspaceDraft.trim()) return;
    try {
      setWorkspaceError(null);
      const res = await swarmBridge.setWorkspace(workspaceDraft.trim());
      setCurrentSession((prev) => ({ ...prev, workspace_root: res.workspace_root }));
      setIsEditingWorkspace(false);
    } catch (err) {
      setWorkspaceError(err instanceof Error ? err.message : 'Invalid directory');
    }
  };

  const handleBrowseWorkspace = async () => {
    try {
      setWorkspaceError(null);
      const res = await swarmBridge.pickWorkspace();
      if (!res.cancelled) {
        setCurrentSession((prev) => ({ ...prev, workspace_root: res.workspace_root }));
        setIsEditingWorkspace(false);
      }
    } catch (err) {
      setWorkspaceError(err instanceof Error ? err.message : 'Picker failed');
    }
  };

  // Step 1: Fire agent logic IMMEDIATELY on Deploy Swarm, while buffering UI updates until Byte buries the acorn
  const handleDeploySwarm = (e: React.FormEvent) => {
    e.preventDefault();
    const submittedPrompt = promptText.trim();
    if (!submittedPrompt || isPromptCollapsedToAcorn) return;
    const submittedAttachments = [...attachments];

    // Clear input & attachments immediately upon sending
    setPromptText('');
    setAttachments([]);
    setMentionRange(null);
    setMentionSuggestions([]);

    clearFlushTimers();
    bufferedEventsRef.current = [];
    isAwaitingBuryRef.current = true;

    setAgents([]);
    setLogs([]);
    setBlockers([]);
    setAnalyzerReport(null);
    setFeedbackText('');
    setAnalyzerError(null);
    setSelectedAgentId(null);
    setHighlightErrorInDrawer(false);
    setIsPromptCollapsedToAcorn(true);
    setBurySequenceTrigger((c) => c + 1);

    // Start the backend swarm immediately in the background
    swarmBridge
      .deploySwarm(submittedPrompt, submittedAttachments, {
        workspace_root: currentSession.workspace_root,
        chat_id: currentSession.chat_id || undefined,
      })
      .then(() => swarmBridge.fetchSessions().then(setSessions).catch(() => {}))
      .catch(console.error);
  };

  // Step 2: Acorn is buried -> Pop up Main Orchestrator at burial spot, then smoothly flush buffered events
  const handleAcornBuryComplete = useCallback(
    (buryClientPos: { x: number; y: number }) => {
      setRootSpawnClientPos(buryClientPos);
      setIsPromptCollapsedToAcorn(false);
      isAwaitingBuryRef.current = false;

      const queued = [...bufferedEventsRef.current];
      bufferedEventsRef.current = [];

      // Separate immediate root/session events from subsequent background activity
      const immediate: SwarmSocketEvent[] = [];
      const staggered: SwarmSocketEvent[] = [];

      queued.forEach((ev) => {
        if (
          ev.type === 'SESSION_UPDATED' ||
          (ev.type === 'AGENT_SPAWNED' && ev.payload.type === 'Main')
        ) {
          immediate.push(ev);
        } else {
          staggered.push(ev);
        }
      });

      // Pop up Main Orchestrator immediately at the exact acorn burial coordinate
      immediate.forEach((ev) => applySwarmEvent(ev));

      // Smoothly replay any background work that already occurred while the acorn was being buried
      let cumulativeDelay = 180;
      staggered.forEach((ev) => {
        const timerId = window.setTimeout(() => {
          applySwarmEvent(ev);
        }, cumulativeDelay);
        flushTimersRef.current.push(timerId);
        cumulativeDelay += ev.type === 'AGENT_SPAWNED' ? 200 : 75;
      });
    },
    [applySwarmEvent]
  );

  const handleSelectAgentOnCanvas = (agentId: string) => {
    setSelectedAgentId(agentId);
    setHighlightErrorInDrawer(false);
    setIsDrawerOpen(true);
  };

  const handleSelectFeedbackNode = () => {
    setSelectedAgentId(FEEDBACK_NODE_ID);
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
    if (isNativeWindow) return; // Native macOS titlebar handles window dragging
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

  const rootStyle: React.CSSProperties = isNativeWindow
    ? {
        position: 'relative',
        width: '100%',
        height: '100%',
      }
    : {
        position: 'fixed',
        left: `${windowPos.x}px`,
        top: `${isMinimized ? Math.max(72, windowPos.y) : windowPos.y}px`,
        width: isMinimized
          ? '360px'
          : `${MAIN_COLUMN_WIDTH + (isDrawerOpen ? DRAWER_WIDTH : 0)}px`,
        height: isMinimized ? '10px' : '680px',
      };

  return (
    <div className="relative h-screen w-screen overflow-hidden bg-[#0A0A0C] text-zinc-100 select-none">
      <div
        id="swarm-widget-root"
        style={rootStyle}
        className={`flex flex-col ${
          !isNativeWindow && isMinimized
            ? `overflow-visible rounded-full border border-zinc-700 bg-[#111114] ${
                activeHitlAgentId || failedAgent ? 'peekaboo-bar-alert' : ''
              }`
            : isNativeWindow
            ? 'overflow-hidden bg-[#0A0A0C]'
            : 'overflow-visible rounded-2xl border border-zinc-800 bg-[#0A0A0C] shadow-[0_25px_70px_rgba(0,0,0,0.95)]'
        }`}
      >
        <MascotOverlay
          isMinimized={!isNativeWindow && isMinimized}
          isCanvasPanning={isCanvasPanning}
          burySequenceTrigger={burySequenceTrigger}
          hasRootNode={hasRootNode}
          activeHitlAgentId={activeHitlAgentId}
          failedAgentId={failedAgent?.agent_id || null}
          onBuryComplete={handleAcornBuryComplete}
          onInspectFailedNode={handleInspectFailedNode}
          onExpandFromKnock={handleExpandFromKnock}
        />

        {!isNativeWindow && isMinimized ? (
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
          <div
            className={`flex h-full w-full overflow-hidden ${
              isNativeWindow ? '' : 'rounded-2xl'
            }`}
          >
            <div
              style={isNativeWindow ? undefined : { width: `${MAIN_COLUMN_WIDTH}px` }}
              className={`flex h-full flex-col overflow-hidden ${
                isNativeWindow ? 'flex-1 min-w-0' : 'shrink-0'
              }`}
            >
              {/* Minimal Monochrome Top Bar */}
              <header
                onMouseDown={handleDragMouseDown}
                className={`flex h-11 shrink-0 items-center justify-between border-b border-zinc-800/80 bg-[#0A0A0C] px-3.5 ${
                  isNativeWindow ? '' : 'cursor-grab active:cursor-grabbing'
                }`}
              >
                <div className="flex items-center gap-2">
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

                  <button
                    onClick={handleCreateNewSession}
                    className="rounded p-1.5 text-zinc-500 transition hover:bg-zinc-800 hover:text-[#FF6B00]"
                    title="New Session"
                  >
                    <Plus className="h-3.5 w-3.5" />
                  </button>

                  {isEditingWorkspace ? (
                    <div className="flex items-center gap-1">
                      <input
                        type="text"
                        autoFocus
                        value={workspaceDraft}
                        onChange={(e) => setWorkspaceDraft(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') handleApplyWorkspace();
                          if (e.key === 'Escape') setIsEditingWorkspace(false);
                        }}
                        placeholder="/path/to/workspace"
                        className="h-6 w-56 rounded border border-zinc-700 bg-[#111114] px-2 font-mono text-[11px] text-white focus:border-[#FF6B00] focus:outline-none"
                      />
                      <button
                        onClick={handleApplyWorkspace}
                        className="rounded p-1 text-zinc-300 hover:bg-zinc-800 hover:text-[#FF6B00]"
                        title="Apply directory"
                      >
                        <Check className="h-3 w-3" />
                      </button>
                      <button
                        onClick={handleBrowseWorkspace}
                        className="rounded p-1 text-zinc-400 hover:bg-zinc-800 hover:text-white"
                        title="Browse in Finder"
                      >
                        <FolderOpen className="h-3 w-3" />
                      </button>
                      <button
                        onClick={() => {
                          setIsEditingWorkspace(false);
                          setWorkspaceError(null);
                        }}
                        className="rounded p-1 text-zinc-500 hover:bg-zinc-800 hover:text-white"
                      >
                        <X className="h-3 w-3" />
                      </button>
                      {workspaceError && (
                        <span className="font-mono text-[10px] text-[#a85454]">
                          {workspaceError}
                        </span>
                      )}
                    </div>
                  ) : (
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => {
                          setWorkspaceDraft(currentSession.workspace_root);
                          setWorkspaceError(null);
                          setIsEditingWorkspace(true);
                        }}
                        className="max-w-[260px] truncate rounded px-1.5 py-0.5 font-mono text-[11px] text-zinc-400 transition hover:bg-zinc-900 hover:text-zinc-100"
                        title="Click to edit working directory"
                      >
                        {currentSession.workspace_root}
                      </button>
                      <button
                        onClick={handleBrowseWorkspace}
                        className="rounded p-1 text-zinc-600 transition hover:bg-zinc-900 hover:text-zinc-200"
                        title="Choose working directory in Finder"
                      >
                        <FolderOpen className="h-3 w-3" />
                      </button>
                    </div>
                  )}
                </div>

                {!isNativeWindow && (
                  <div className="flex items-center gap-1 text-zinc-700">
                    <GripHorizontal className="h-3.5 w-3.5" />
                  </div>
                )}

                <div className="flex items-center gap-2 pr-2">
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

                  {!isNativeWindow && (
                    <button
                      onClick={() => setIsMinimized(true)}
                      className="rounded p-1.5 text-zinc-500 transition hover:text-zinc-200"
                      title="Minimize to Slim Progress Bar"
                    >
                      <Minimize2 className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
              </header>

              {/* Simulation Harness (only renders in mock mode) */}
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

              {/* Canvas + Collapsible History Sidebar */}
              <div className="relative flex flex-1 overflow-hidden">
                {isSidebarOpen && (
                  <aside className="flex w-56 shrink-0 flex-col border-r border-zinc-800 bg-[#0d0d10]">
                    <div className="flex items-center justify-between border-b border-zinc-800 px-3 py-2">
                      <span className="font-mono text-[10px] uppercase text-zinc-500">
                        Sessions
                      </span>
                      <button
                        onClick={handleCreateNewSession}
                        className="flex items-center gap-1 font-mono text-[10px] text-zinc-300 hover:text-[#FF6B00]"
                      >
                        <Plus className="h-3 w-3" /> New
                      </button>
                    </div>
                    <div className="flex-1 space-y-1 overflow-y-auto p-2">
                      {sessions.map((s) => (
                        <button
                          key={s.chat_id}
                          onClick={async () => {
                            clearFlushTimers();
                            isAwaitingBuryRef.current = false;
                            bufferedEventsRef.current = [];
                            const data = await swarmBridge.loadSession(s.chat_id);
                            setRootSpawnClientPos(null);
                            setCurrentSession(data.session);
                            setAgents(data.agents);
                            setLogs(data.logs);
                            setBlockers([]);
                            setAnalyzerReport(data.report || null);
                            setFeedbackText('');
                            setAnalyzerError(null);
                            setSelectedAgentId(null);
                          }}
                          className={`w-full rounded-lg border p-2 text-left transition ${
                            currentSession.chat_id === s.chat_id
                              ? 'border-[#FF6B00]/60 bg-[#161412]'
                              : 'border-zinc-800/60 bg-[#111114] hover:border-zinc-700'
                          }`}
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
                    rootSpawnClientPos={rootSpawnClientPos}
                    showFeedbackNode={showFeedbackNode}
                    hasAnalyzerReport={Boolean(analyzerReport)}
                    onSelectAgent={handleSelectAgentOnCanvas}
                    onSelectFeedbackNode={handleSelectFeedbackNode}
                    onPanStateChange={setIsCanvasPanning}
                  />
                </div>
              </div>

              {/* Bottom Task Input Dock */}
              <div
                data-mascot-target="task-input-box"
                className="relative border-t border-zinc-800/80 bg-[#0A0A0C] px-4 py-3"
              >
                {/* @ File Autocomplete Dropdown */}
                {mentionRange && !isPromptCollapsedToAcorn && (
                  <div className="absolute bottom-full left-4 right-4 z-40 mb-1.5 max-h-56 overflow-y-auto rounded-xl border border-zinc-800 bg-[#111114] p-1 shadow-2xl">
                    <div className="flex items-center justify-between px-2.5 py-1 font-mono text-[10px] text-zinc-500">
                      <span>Attach file from workspace</span>
                      <span>↑↓ navigate • ↵ select • esc close</span>
                    </div>
                    {mentionSuggestions.length === 0 ? (
                      <div className="px-2.5 py-2 font-mono text-[11px] text-zinc-500">
                        No matching files for &ldquo;@{mentionRange.query}&rdquo;
                      </div>
                    ) : (
                      mentionSuggestions.map((filePath, idx) => (
                        <button
                          key={filePath}
                          type="button"
                          onMouseDown={(ev) => {
                            ev.preventDefault();
                            handleSelectMentionFile(filePath);
                          }}
                          onMouseEnter={() => setMentionActiveIdx(idx)}
                          className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left font-mono text-[11px] transition ${
                            idx === mentionActiveIdx
                              ? 'bg-zinc-800 text-white'
                              : 'text-zinc-300 hover:bg-zinc-800/60'
                          }`}
                        >
                          <FileCode2 className="h-3.5 w-3.5 shrink-0 text-zinc-500" />
                          <span className="truncate">{filePath}</span>
                        </button>
                      ))
                    )}
                  </div>
                )}

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
                          className="inline-flex items-center gap-1.5 rounded-md border border-zinc-800 bg-[#141418] px-2 py-0.5 font-mono text-[10px] text-zinc-300"
                        >
                          <FileCode2 className="h-3 w-3 shrink-0 text-zinc-500" />
                          <span className="max-w-[240px] truncate" title={item}>
                            {item}
                          </span>
                          <button
                            type="button"
                            onClick={() =>
                              setAttachments((prev) => prev.filter((a) => a !== item))
                            }
                            className="rounded p-0.5 text-zinc-500 transition hover:bg-zinc-800 hover:text-white"
                            title={`Remove ${item}`}
                            aria-label={`Remove ${item}`}
                          >
                            <X className="h-2.5 w-2.5" />
                          </button>
                        </span>
                      ))}
                    </div>
                  )}

                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={handlePickFiles}
                      title="Attach files via Finder"
                      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-zinc-800 bg-[#111114] text-zinc-400 transition hover:border-zinc-600 hover:text-white"
                    >
                      <Paperclip className="h-4 w-4" />
                    </button>

                    <input
                      ref={promptInputRef}
                      type="text"
                      value={promptText}
                      onChange={(e) => {
                        const val = e.target.value;
                        setPromptText(val);
                        detectMentionAtCursor(val, e.target.selectionStart);
                      }}
                      onClick={(e) =>
                        detectMentionAtCursor(
                          e.currentTarget.value,
                          e.currentTarget.selectionStart
                        )
                      }
                      onKeyUp={(e) => {
                        if (
                          e.key === 'ArrowLeft' ||
                          e.key === 'ArrowRight' ||
                          e.key === 'Home' ||
                          e.key === 'End'
                        ) {
                          detectMentionAtCursor(
                            e.currentTarget.value,
                            e.currentTarget.selectionStart
                          );
                        }
                      }}
                      onKeyDown={(e) => {
                        if (!mentionRange) return;
                        if (e.key === 'Escape') {
                          e.preventDefault();
                          setMentionRange(null);
                          setMentionSuggestions([]);
                          return;
                        }
                        if (mentionSuggestions.length === 0) return;
                        if (e.key === 'ArrowDown') {
                          e.preventDefault();
                          setMentionActiveIdx((i) => (i + 1) % mentionSuggestions.length);
                        } else if (e.key === 'ArrowUp') {
                          e.preventDefault();
                          setMentionActiveIdx(
                            (i) => (i - 1 + mentionSuggestions.length) % mentionSuggestions.length
                          );
                        } else if (e.key === 'Enter' || e.key === 'Tab') {
                          e.preventDefault();
                          const chosen = mentionSuggestions[mentionActiveIdx];
                          if (chosen) handleSelectMentionFile(chosen);
                        }
                      }}
                      onBlur={() => {
                        window.setTimeout(() => {
                          setMentionRange(null);
                        }, 120);
                      }}
                      placeholder="Define autonomous swarm task... (type @ to attach files)"
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

            <TerminalDrawer
              isOpen={isDrawerOpen}
              isFeedbackMode={isFeedbackMode}
              selectedAgent={selectedAgent}
              allLogs={logs}
              activeBlockers={blockers}
              highlightError={highlightErrorInDrawer}
              analyzerReport={analyzerReport}
              isAnalyzing={isAnalyzing}
              analyzerError={analyzerError}
              feedbackText={feedbackText}
              onFeedbackTextChange={setFeedbackText}
              onRunAnalyzer={handleRunAnalyzer}
              onOpenAnalyzerModal={() => setShowReportModal(true)}
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