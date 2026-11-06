// Mirrors polymath.api.schemas (FastAPI). Keep in sync.

export type RunStatus =
  | "planning"
  | "awaiting_approval"
  | "executing"
  | "completed"
  | "budget_exhausted"
  | "rejected"
  | "failed";

export type TaskStatus = "pending" | "running" | "done" | "failed" | "skipped";
export type ClaimStatus = "proposed" | "challenged" | "verified" | "refuted";
export type EvidenceKind = "citation" | "computation" | "formal_proof" | "critique";

export interface TaskInfo {
  id: string;
  type: string;
  description: string;
  deps: string[];
  assigned_role: string;
}

export interface Evidence {
  id: string;
  kind: EvidenceKind;
  summary: string;
  payload: Record<string, unknown>;
}

export interface Claim {
  id: string;
  statement: string;
  confidence: number;
  status: ClaimStatus;
  evidence: Evidence[];
  proposed_by: string | null;
  origin_run_id: string | null;
}

export interface Usage {
  tokens: number;
  usd: number;
}

export interface RunSummary {
  run_id: string;
  problem: string;
  status: RunStatus | null;
  created_at: string;
}

export interface RunDetail {
  run_id: string;
  status: RunStatus | null;
  stop_reason: string;
  problem: string;
  tasks: TaskInfo[];
  task_status: Record<string, TaskStatus>;
  claims: Claim[];
  usage: Usage;
  max_usd: number | null;
  awaiting_approval: boolean;
  answer: string;
  report_markdown: string;
  finished: boolean;
}

export interface BlackboardEvent {
  id: string;
  run_id: string;
  kind: string;
  payload: Record<string, unknown>;
  created_at: string;
}
