export type AgentType = 'Main' | 'Sub' | 'Worker';

export type AgentStatus =
  | 'booting'
  | 'executing'
  | 'waiting'
  | 'completed'
  | 'failed';

export type BlockerType = 'Security' | 'Question' | 'Action';

export interface AgentNodeData extends Record<string, unknown> {
  agent_id: string;
  parent_id: string | null;
  type: AgentType;
  status: AgentStatus;
  current_iteration: number;
  max_iterations: number;
  cost_usd: number;
  instructions: string;
  dod: string;
  active_blocker?: HITLBlocker | null;
  error_line?: string;
}

export interface CommandEvent {
  id: string;
  timestamp: string;
  agent_id: string;
  command_type:
    | 'Zsh'
    | 'WriteFile'
    | 'ReadFile'
    | 'Chrome'
    | 'SearchDB'
    | 'SpawnAgent'
    | 'WaitForAgents'
    | 'MarkDone';
  attributes?: Record<string, string>;
  payload: string;
  result_output?: string;
  is_error?: boolean;
}

export interface HITLBlocker {
  blocker_id: string;
  agent_id: string;
  blocker_type: BlockerType;
  prompt_text: string;
  command_preview?: string;
  options?: string[];
  timestamp: string;
}

export interface SessionSummary {
  chat_id: string;
  title: string;
  workspace_root: string;
  overall_status: 'Running' | 'Success' | 'Failed' | 'Idle';
  total_cost_usd: number;
  timestamp: string;
  chroma_status: 'Connected' | 'Indexing' | 'Offline';
  connected_tools: string[];
}

export interface AnalyzerReport {
  chat_id: string;
  efficiency_score: number;
  bottlenecks: string[];
  memory_upgrades: {
    target_file: string;
    summary: string;
    diff_preview: string;
  }[];
  total_tokens: number;
  total_duration_sec: number;
}

export type SwarmSocketEvent =
  | { type: 'SESSION_UPDATED'; payload: Partial<SessionSummary> }
  | { type: 'AGENT_SPAWNED'; payload: AgentNodeData }
  | { type: 'AGENT_UPDATED'; payload: Partial<AgentNodeData> & { agent_id: string } }
  | { type: 'COMMAND_LOGGED'; payload: CommandEvent }
  | { type: 'HITL_REQUIRED'; payload: HITLBlocker }
  | { type: 'HITL_RESOLVED'; payload: { blocker_id: string; agent_id: string } }
  | { type: 'ANALYZER_REPORT'; payload: AnalyzerReport };

export type MascotAnimationState =
  | 'idle'
  | 'run_bezel'
  | 'climb_bezel'
  | 'run_canvas_topdown'
  | 'acorn_catch'
  | 'carry_acorn'
  | 'dig'
  | 'wave_point'
  | 'offscreen_point'
  | 'hardhat_inspect'
  | 'glass_knock'
  | 'peekaboo_snack';