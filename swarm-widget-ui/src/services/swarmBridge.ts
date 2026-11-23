import {
  AgentNodeData,
  AnalyzerReport,
  CommandEvent,
  HITLBlocker,
  SessionSummary,
  SwarmSocketEvent,
} from '../types/swarm';

function shouldUseMockBridge(): boolean {
  if (typeof window === 'undefined') return true;
  const params = new URLSearchParams(window.location.search);
  if (params.get('live') === '1') return false;
  if (params.get('mock') === '1') return true;
  // Running directly from FastAPI server (:8765) defaults to Live; Vite (:5173) defaults to Mock
  return window.location.port !== '8765';
}

export const USE_MOCK_BRIDGE = shouldUseMockBridge();

const apiOrigin =
  typeof window !== 'undefined' && window.location.port === '8765'
    ? window.location.origin
    : 'http://127.0.0.1:8765';

const wsOrigin = apiOrigin.replace(/^http/, 'ws');

export const BACKEND_CONFIG = {
  REST_BASE_URL: `${apiOrigin}/api`,
  WS_URL: `${wsOrigin}/ws/swarm`,
};

export type EventSubscriber = (event: SwarmSocketEvent) => void;

export interface ISwarmBridge {
  connect(onEvent: EventSubscriber): () => void;
  fetchConfig(): Promise<{
    workspace_root: string;
    chroma_status: 'Connected' | 'Indexing' | 'Offline';
    connected_tools: string[];
  }>;
  setWorkspace(workspaceRoot: string): Promise<{ workspace_root: string }>;
  pickWorkspace(): Promise<{ cancelled: boolean; workspace_root: string }>;
  listWorkspaceFiles(query?: string): Promise<string[]>;
  pickFiles(): Promise<{ cancelled: boolean; files: string[] }>;
  createNewSession(): Promise<SessionSummary>;
  fetchSessions(): Promise<SessionSummary[]>;
  loadSession(chatId: string): Promise<{
    session: SessionSummary;
    agents: AgentNodeData[];
    logs: CommandEvent[];
    report?: AnalyzerReport;
  }>;
  deploySwarm(
    prompt: string,
    attachments: string[],
    options?: { workspace_root?: string; chat_id?: string }
  ): Promise<{ chat_id: string }>;
  runAnalyzer(chatId: string, userFeedback: string): Promise<AnalyzerReport>;
  resolveHitl(
    blockerId: string,
    agentId: string,
    resolution: { action: 'approve' | 'deny' | 'answer' | 'resume'; value?: string }
  ): Promise<void>;
  cancelAgent(agentId: string, reason?: string): Promise<{ cancelled_agent_ids: string[] }>;
}

class LiveSwarmBridge implements ISwarmBridge {
  private ws: WebSocket | null = null;
  private subscribers: Set<EventSubscriber> = new Set();

  connect(onEvent: EventSubscriber): () => void {
    this.subscribers.add(onEvent);
    if (!this.ws || this.ws.readyState === WebSocket.CLOSED) {
      this.ws = new WebSocket(BACKEND_CONFIG.WS_URL);
      this.ws.onmessage = (msg) => {
        try {
          const parsed: SwarmSocketEvent = JSON.parse(msg.data);
          this.subscribers.forEach((sub) => sub(parsed));
        } catch (err) {
          console.error('[LiveSwarmBridge] Invalid WS payload:', err);
        }
      };
    }
    return () => {
      this.subscribers.delete(onEvent);
    };
  }

  async fetchConfig() {
    const res = await fetch(`${BACKEND_CONFIG.REST_BASE_URL}/config`);
    return res.json();
  }

  async setWorkspace(workspaceRoot: string) {
    const res = await fetch(`${BACKEND_CONFIG.REST_BASE_URL}/workspace`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace_root: workspaceRoot }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Invalid directory' }));
      throw new Error(err.detail || 'Invalid directory');
    }
    return res.json();
  }

  async pickWorkspace() {
    const res = await fetch(`${BACKEND_CONFIG.REST_BASE_URL}/workspace/pick`, { method: 'POST' });
    return res.json();
  }

  async listWorkspaceFiles(query = ''): Promise<string[]> {
    const params = new URLSearchParams();
    if (query) params.set('q', query);
    const res = await fetch(`${BACKEND_CONFIG.REST_BASE_URL}/workspace/files?${params.toString()}`);
    if (!res.ok) return [];
    const data = await res.json();
    return Array.isArray(data.files) ? data.files : [];
  }

  async pickFiles(): Promise<{ cancelled: boolean; files: string[] }> {
    const res = await fetch(`${BACKEND_CONFIG.REST_BASE_URL}/workspace/pick-files`, {
      method: 'POST',
    });
    if (!res.ok) {
      throw new Error('File picker failed');
    }
    return res.json();
  }

  async createNewSession(): Promise<SessionSummary> {
    const res = await fetch(`${BACKEND_CONFIG.REST_BASE_URL}/sessions/new`, { method: 'POST' });
    return res.json();
  }

  async fetchSessions(): Promise<SessionSummary[]> {
    const res = await fetch(`${BACKEND_CONFIG.REST_BASE_URL}/sessions`);
    return res.json();
  }

  async loadSession(chatId: string) {
    const res = await fetch(`${BACKEND_CONFIG.REST_BASE_URL}/sessions/${chatId}`);
    return res.json();
  }

  async deploySwarm(
    prompt: string,
    attachments: string[],
    options?: { workspace_root?: string; chat_id?: string }
  ): Promise<{ chat_id: string }> {
    const res = await fetch(`${BACKEND_CONFIG.REST_BASE_URL}/swarm/deploy`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompt,
        attachments,
        workspace_root: options?.workspace_root,
        chat_id: options?.chat_id,
      }),
    });
    return res.json();
  }

  async runAnalyzer(chatId: string, userFeedback: string): Promise<AnalyzerReport> {
    const res = await fetch(`${BACKEND_CONFIG.REST_BASE_URL}/swarm/analyze`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        chat_id: chatId,
        user_feedback: userFeedback,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Analyzer request failed' }));
      throw new Error(err.detail || 'Analyzer request failed');
    }
    return res.json();
  }

  async resolveHitl(
    blockerId: string,
    agentId: string,
    resolution: { action: 'approve' | 'deny' | 'answer' | 'resume'; value?: string }
  ): Promise<void> {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(
        JSON.stringify({
          type: 'HITL_RESPONSE',
          payload: { blocker_id: blockerId, agent_id: agentId, ...resolution },
        })
      );
    } else {
      await fetch(`${BACKEND_CONFIG.REST_BASE_URL}/swarm/hitl`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ blocker_id: blockerId, agent_id: agentId, ...resolution }),
      });
    }
  }

  async cancelAgent(
    agentId: string,
    reason = 'Cancelled by user.'
  ): Promise<{ cancelled_agent_ids: string[] }> {
    const res = await fetch(`${BACKEND_CONFIG.REST_BASE_URL}/swarm/cancel`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ agent_id: agentId, reason }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Cancel request failed' }));
      throw new Error(err.detail || 'Cancel request failed');
    }
    return res.json();
  }
}

class MockSwarmBridge implements ISwarmBridge {
  private subscribers: Set<EventSubscriber> = new Set();
  private timers: number[] = [];
  private mockWorkspaceRoot = '~/dev/local-swarm';

  private mockSessions: SessionSummary[] = [
    {
      chat_id: 'chat_98f2a1',
      title: 'Refactor Auth Middleware & JWT Rotation',
      workspace_root: '~/dev/core-api',
      overall_status: 'Success',
      total_cost_usd: 0.42,
      timestamp: '14m ago',
      chroma_status: 'Connected',
      connected_tools: ['Zsh', 'FileIO', 'ChromeCDP', 'ChromaDB'],
    },
    {
      chat_id: 'chat_31b9c4',
      title: 'Scrape Competitor Pricing Matrix via CDP',
      workspace_root: '~/dev/market-intel',
      overall_status: 'Failed',
      total_cost_usd: 0.19,
      timestamp: '2h ago',
      chroma_status: 'Connected',
      connected_tools: ['Zsh', 'FileIO', 'ChromeCDP', 'ChromaDB'],
    },
  ];

  connect(onEvent: EventSubscriber): () => void {
    this.subscribers.add(onEvent);
    return () => {
      this.subscribers.delete(onEvent);
    };
  }

  public emit(event: SwarmSocketEvent) {
    this.subscribers.forEach((cb) => cb(event));
  }

  private schedule(delayMs: number, fn: () => void) {
    const id = window.setTimeout(fn, delayMs);
    this.timers.push(id);
  }

  public clearTimers() {
    this.timers.forEach((t) => clearTimeout(t));
    this.timers = [];
  }

  async fetchConfig() {
    return {
      workspace_root: this.mockWorkspaceRoot,
      chroma_status: 'Connected' as const,
      connected_tools: ['Zsh', 'FileIO', 'ChromeCDP', 'ChromaDB'],
    };
  }

  async setWorkspace(workspaceRoot: string) {
    this.mockWorkspaceRoot = workspaceRoot;
    return { workspace_root: workspaceRoot };
  }

  async pickWorkspace() {
    return { cancelled: false, workspace_root: this.mockWorkspaceRoot };
  }

  async listWorkspaceFiles(query = ''): Promise<string[]> {
    const mockFiles = [
      'README.md',
      'AGENTS.md',
      'swarm_server.py',
      'swarm_gui.py',
      'pipelines/swarm_analyzer.py',
      'infrastructure/agent_loop.py',
      'swarm-widget-ui/src/App.tsx',
      'swarm-widget-ui/src/components/SwarmCanvas.tsx',
      'swarm-widget-ui/src/components/TerminalDrawer.tsx',
    ];
    const q = query.trim().toLowerCase();
    return q ? mockFiles.filter((f) => f.toLowerCase().includes(q)) : mockFiles;
  }

  async pickFiles(): Promise<{ cancelled: boolean; files: string[] }> {
    return { cancelled: false, files: ['swarm_server.py'] };
  }

  async createNewSession(): Promise<SessionSummary> {
    this.clearTimers();
    return {
      chat_id: '',
      title: 'New Session',
      workspace_root: this.mockWorkspaceRoot,
      overall_status: 'Idle',
      total_cost_usd: 0.0,
      timestamp: 'Now',
      chroma_status: 'Connected',
      connected_tools: ['Zsh', 'FileIO', 'ChromeCDP', 'ChromaDB'],
    };
  }

  async fetchSessions(): Promise<SessionSummary[]> {
    return Promise.resolve([...this.mockSessions]);
  }

  async loadSession(chatId: string) {
    const found = this.mockSessions.find((s) => s.chat_id === chatId) || this.mockSessions[0];
    return Promise.resolve({
      session: found,
      agents: [
        {
          agent_id: 'orch_main',
          parent_id: null,
          type: 'Main' as const,
          status: (found.overall_status === 'Success' ? 'completed' : 'failed') as 'completed' | 'failed',
          current_iteration: 4,
          max_iterations: 30,
          cost_usd: 0.14,
          instructions: found.title,
          dod: 'All unit tests pass and git working tree is clean.',
        },
        {
          agent_id: 'sub_backend',
          parent_id: 'orch_main',
          type: 'Sub' as const,
          status: (found.overall_status === 'Success' ? 'completed' : 'failed') as 'completed' | 'failed',
          current_iteration: 6,
          max_iterations: 30,
          cost_usd: 0.16,
          instructions: 'Update token verification module and run pytest.',
          dod: 'pytest exits with code 0.',
        },
        {
          agent_id: 'worker_x9',
          parent_id: 'sub_backend',
          type: 'Worker' as const,
          status: (found.overall_status === 'Success' ? 'completed' : 'failed') as 'completed' | 'failed',
          current_iteration: found.overall_status === 'Success' ? 5 : 10,
          max_iterations: 10,
          cost_usd: 0.12,
          instructions: 'Execute pytest suite and patch JWT expiry bug.',
          dod: 'Zero test failures.',
          error_line:
            found.overall_status === 'Failed'
              ? 'FATAL: ConnectionRefusedError: [Errno 61] Connect call failed (127.0.0.1, 6379)'
              : undefined,
        },
      ],
      logs: [
        {
          id: 'log_1',
          timestamp: '13:40:02',
          agent_id: 'orch_main',
          command_type: 'SearchDB' as const,
          payload: '<SearchDB query="JWT auth middleware patterns" top_k="5" />',
          result_output: 'Found 3 semantic matches in AGENTS.md and skills/auth_flow.md',
        },
        {
          id: 'log_2',
          timestamp: '13:40:09',
          agent_id: 'worker_x9',
          command_type: 'Zsh' as const,
          payload: '<Zsh>pytest tests/auth/ -v</Zsh>',
          result_output:
            found.overall_status === 'Success'
              ? '=== 14 passed in 0.84s ==='
              : 'FATAL: ConnectionRefusedError: [Errno 61] Connect call failed (127.0.0.1, 6379)',
          is_error: found.overall_status === 'Failed',
        },
      ],
    });
  }

  async deploySwarm(
    prompt: string,
    attachments: string[],
    options?: { workspace_root?: string; chat_id?: string }
  ): Promise<{ chat_id: string }> {
    this.clearTimers();
    const chatId = options?.chat_id || `chat_${Math.random().toString(36).substring(2, 8)}`;

    this.emit({
      type: 'SESSION_UPDATED',
      payload: {
        chat_id: chatId,
        title: prompt.slice(0, 46) + (prompt.length > 46 ? '...' : ''),
        workspace_root: options?.workspace_root || this.mockWorkspaceRoot,
        overall_status: 'Running',
        total_cost_usd: 0.02,
      },
    });

    this.emit({
      type: 'AGENT_SPAWNED',
      payload: {
        agent_id: 'orch_root',
        parent_id: null,
        type: 'Main',
        status: 'booting',
        current_iteration: 1,
        max_iterations: 30,
        cost_usd: 0.02,
        instructions: prompt,
        dod: 'Verify full build, pass tests, and commit schema migrations cleanly.',
      },
    });

    this.emit({
      type: 'COMMAND_LOGGED',
      payload: {
        id: `cmd_${Date.now()}_1`,
        timestamp: new Date().toLocaleTimeString(),
        agent_id: 'orch_root',
        command_type: 'SearchDB',
        payload: `<SearchDB query="${prompt.slice(0, 32)}" collection="workspace_memory" />`,
        result_output: `Retrieved 4 chunks from ~/.agents/chroma (Attachments: ${attachments.length})`,
      },
    });

    this.schedule(1400, () => {
      this.emit({
        type: 'AGENT_UPDATED',
        payload: { agent_id: 'orch_root', status: 'waiting', current_iteration: 2, cost_usd: 0.05 },
      });

      this.emit({
        type: 'COMMAND_LOGGED',
        payload: {
          id: `cmd_${Date.now()}_2`,
          timestamp: new Date().toLocaleTimeString(),
          agent_id: 'orch_root',
          command_type: 'SpawnAgent',
          payload: `<SpawnAgent id="sub_api" role="SubOrchestrator" />\n<SpawnAgent id="sub_ui" role="SubOrchestrator" />\n<WaitForAgents ids="sub_api,sub_ui" />`,
          result_output: 'Spawned 2 Sub-Orchestrator threads.',
        },
      });

      this.emit({
        type: 'AGENT_SPAWNED',
        payload: {
          agent_id: 'sub_api',
          parent_id: 'orch_root',
          type: 'Sub',
          status: 'executing',
          current_iteration: 1,
          max_iterations: 30,
          cost_usd: 0.03,
          instructions: 'Audit backend endpoints & database migrations.',
          dod: 'Schema validated and API integration tests green.',
        },
      });

      this.emit({
        type: 'AGENT_SPAWNED',
        payload: {
          agent_id: 'sub_ui',
          parent_id: 'orch_root',
          type: 'Sub',
          status: 'booting',
          current_iteration: 1,
          max_iterations: 30,
          cost_usd: 0.02,
          instructions: 'Verify frontend bundle and E2E headless browser checks.',
          dod: 'Zero TypeScript or console errors in Chrome CDP.',
        },
      });
    });

    this.schedule(2900, () => {
      this.emit({
        type: 'AGENT_UPDATED',
        payload: { agent_id: 'sub_api', status: 'waiting', current_iteration: 2, cost_usd: 0.06 },
      });
      this.emit({
        type: 'AGENT_UPDATED',
        payload: { agent_id: 'sub_ui', status: 'waiting', current_iteration: 2, cost_usd: 0.05 },
      });

      this.emit({
        type: 'AGENT_SPAWNED',
        payload: {
          agent_id: 'worker_db9',
          parent_id: 'sub_api',
          type: 'Worker',
          status: 'executing',
          current_iteration: 2,
          max_iterations: 10,
          cost_usd: 0.04,
          instructions: 'Run SQLite/Postgres migration scripts in Zsh.',
          dod: 'Tables created and seeded.',
        },
      });

      this.emit({
        type: 'AGENT_SPAWNED',
        payload: {
          agent_id: 'worker_fs4',
          parent_id: 'sub_api',
          type: 'Worker',
          status: 'executing',
          current_iteration: 3,
          max_iterations: 10,
          cost_usd: 0.03,
          instructions: 'Patch serializer types and write unit tests.',
          dod: 'All serializer tests pass.',
        },
      });

      this.emit({
        type: 'AGENT_SPAWNED',
        payload: {
          agent_id: 'worker_cdp2',
          parent_id: 'sub_ui',
          type: 'Worker',
          status: 'executing',
          current_iteration: 1,
          max_iterations: 10,
          cost_usd: 0.04,
          instructions: 'Inspect DOM layout and verify OAuth login flow via Chrome CDP.',
          dod: 'Dashboard renders cleanly.',
        },
      });
    });

    this.schedule(4800, () => {
      const blocker: HITLBlocker = {
        blocker_id: 'blk_sec_01',
        agent_id: 'worker_db9',
        blocker_type: 'Security',
        prompt_text: 'Command not in cmd_whitelist.md. Approve execution?',
        command_preview: 'docker compose -f docker-compose.dev.yml down -v && ./scripts/reset_db.sh --force',
        timestamp: new Date().toLocaleTimeString(),
      };

      this.emit({
        type: 'COMMAND_LOGGED',
        payload: {
          id: `cmd_${Date.now()}_4`,
          timestamp: new Date().toLocaleTimeString(),
          agent_id: 'worker_db9',
          command_type: 'Zsh',
          payload: `<Zsh>${blocker.command_preview}</Zsh>`,
          result_output: '[SECURITY GREYLIST INTERCEPT] Execution paused awaiting user approval.',
          is_error: true,
        },
      });

      this.emit({
        type: 'HITL_REQUIRED',
        payload: blocker,
      });
    });

    return Promise.resolve({ chat_id: chatId });
  }

  async runAnalyzer(chatId: string, userFeedback: string): Promise<AnalyzerReport> {
    await new Promise((r) => setTimeout(r, 900));
    const report: AnalyzerReport = {
      chat_id: chatId || 'chat_live',
      efficiency_score: '9/10',
      bottlenecks:
        'worker_db9 paused awaiting Zsh greylist approval. sub_ui spent 1 extra turn re-querying DOM selectors before caching.',
      recommendations: userFeedback.trim()
        ? `Incorporated user feedback ("${userFeedback.trim()}") and documented local database reset rules in AGENTS.md.`
        : 'Added local docker-compose reset workflow and port mappings to AGENTS.md.',
      modifications: [
        {
          type: 'UpdateAgentsMd',
          target_file: 'AGENTS.md',
          summary: 'Added local docker-compose reset workflow and port mappings.',
          content:
            '## Database Reset\nPrefer `./scripts/reset_db.sh --safe` to avoid volume wipes.',
        },
      ],
      cost_usd: 0.0042,
      duration_sec: 1.8,
      user_feedback: userFeedback.trim() || undefined,
    };
    this.emit({ type: 'ANALYZER_REPORT', payload: report });
    return report;
  }

  async resolveHitl(
    blockerId: string,
    agentId: string,
    resolution: { action: 'approve' | 'deny' | 'answer' | 'resume'; value?: string }
  ): Promise<void> {
    this.emit({
      type: 'HITL_RESOLVED',
      payload: { blocker_id: blockerId, agent_id: agentId },
    });

    this.emit({
      type: 'COMMAND_LOGGED',
      payload: {
        id: `cmd_${Date.now()}_res`,
        timestamp: new Date().toLocaleTimeString(),
        agent_id: agentId,
        command_type: 'Zsh',
        payload: `<HITLResolution action="${resolution.action}" value="${resolution.value || ''}" />`,
        result_output:
          resolution.action === 'deny'
            ? 'User denied command. Agent pivoting strategy...'
            : 'User approved/answered. Resuming agent execution...',
      },
    });

    this.schedule(1400, () => {
      this.emit({
        type: 'AGENT_UPDATED',
        payload: { agent_id: agentId, status: 'completed', current_iteration: 5, cost_usd: 0.08 },
      });
      this.emit({
        type: 'AGENT_UPDATED',
        payload: { agent_id: 'worker_fs4', status: 'completed', current_iteration: 6, cost_usd: 0.07 },
      });
      this.emit({
        type: 'AGENT_UPDATED',
        payload: { agent_id: 'worker_cdp2', status: 'completed', current_iteration: 4, cost_usd: 0.06 },
      });
    });

    this.schedule(2600, () => {
      this.emit({
        type: 'AGENT_UPDATED',
        payload: { agent_id: 'sub_api', status: 'completed', current_iteration: 4, cost_usd: 0.09 },
      });
      this.emit({
        type: 'AGENT_UPDATED',
        payload: { agent_id: 'sub_ui', status: 'completed', current_iteration: 3, cost_usd: 0.07 },
      });
      this.emit({
        type: 'COMMAND_LOGGED',
        payload: {
          id: `cmd_${Date.now()}_done`,
          timestamp: new Date().toLocaleTimeString(),
          agent_id: 'orch_root',
          command_type: 'MarkDone',
          payload:
            '<MarkDone><Summary>All backend migrations, serializer tests, and Chrome CDP checks completed cleanly with zero errors.</Summary></MarkDone>',
          result_output:
            '[STATUS_DONE] All backend migrations, serializer tests, and Chrome CDP checks completed cleanly with zero errors.',
        },
      });
      this.emit({
        type: 'AGENT_UPDATED',
        payload: { agent_id: 'orch_root', status: 'completed', current_iteration: 5, cost_usd: 0.11 },
      });
      this.emit({
        type: 'SESSION_UPDATED',
        payload: { overall_status: 'Success', total_cost_usd: 0.48 },
      });
    });
  }

  async cancelAgent(
    agentId: string,
    reason = 'Cancelled by user.'
  ): Promise<{ cancelled_agent_ids: string[] }> {
    const mockTree: Record<string, string[]> = {
      orch_root: ['orch_root', 'sub_api', 'sub_ui', 'worker_db9', 'worker_fs4', 'worker_cdp2'],
      sub_api: ['sub_api', 'worker_db9', 'worker_fs4'],
      sub_ui: ['sub_ui', 'worker_cdp2'],
    };
    const targets = mockTree[agentId] || [agentId];
    if (agentId === 'orch_root') {
      this.clearTimers();
    }

    for (const id of targets) {
      const msg =
        id === agentId
          ? `[Error] Agent '${id}' cancelled: ${reason}`
          : `[Error] Agent '${id}' cancelled: Cancelled because parent agent '${agentId}' was cancelled.`;
      this.emit({
        type: 'COMMAND_LOGGED',
        payload: {
          id: `cmd_${Date.now()}_cancel_${id}`,
          timestamp: new Date().toLocaleTimeString(),
          agent_id: id,
          command_type: 'Cancel',
          payload: `<Cancel agent_id="${id}" />`,
          result_output: msg,
          is_error: true,
        },
      });
      this.emit({
        type: 'AGENT_UPDATED',
        payload: {
          agent_id: id,
          status: 'failed',
          active_blocker: null,
          error_line: msg,
        },
      });
    }

    if (agentId === 'orch_root') {
      this.emit({
        type: 'SESSION_UPDATED',
        payload: { overall_status: 'Failed' },
      });
    }
    return { cancelled_agent_ids: targets };
  }
}

export const mockBridgeInstance = new MockSwarmBridge();
export const swarmBridge: ISwarmBridge = USE_MOCK_BRIDGE ? mockBridgeInstance : new LiveSwarmBridge();