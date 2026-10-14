export type TargetType = 'dashboard' | 'form_app' | 'mixed';

export interface InputRequest {
  brief: string;
  api_spec_url: string | Record<string, any>;
  target: TargetType;
  style_hints?: string[];
  required_flows?: string[];
  max_iterations?: number;
}

export interface EvidenceItem {
  type: string;
  ref: string;
}

export interface ProofOfWork {
  agent: string;
  task_id: string;
  claim: string;
  evidence: EvidenceItem[];
  reasoning: string;
  timestamp: string;
}

export interface TraceEntry {
  run_id: string;
  seq: number;
  timestamp: string;
  agent: string;
  event_type: string;
  payload: Record<string, any>;
}

export interface GateResult {
  passed?: boolean;
  evidence?: string;
  flows_passed?: number;
  flows_total?: number;
  critical?: number;
  serious?: number;
  lighthouse_accessibility?: number;
  lighthouse_performance?: number;
  documented_mismatches?: number;
}

export interface QualityReport {
  run_id: string;
  status: 'accepted' | 'partial' | 'failed';
  iterations: {
    total: number;
    by_agent: Record<string, number>;
  };
  gates: {
    build: GateResult;
    tests: GateResult;
    accessibility: GateResult;
    quality: GateResult;
    integration: GateResult;
  };
  revisions?: Array<{
    by: string;
    to: string;
    reason: string;
    resolved: boolean;
  }>;
  unresolved: Array<{
    issue: string;
    evidence: string;
  }>;
  preview_url?: string;
}

export interface RunRecord {
  run_id: string;
  status: 'running' | 'accepted' | 'partial' | 'failed' | 'unknown';
  created_at: string;
  completed_at?: string;
  report?: QualityReport | null;
  preview_url?: string | null;
  error?: string | null;
}
