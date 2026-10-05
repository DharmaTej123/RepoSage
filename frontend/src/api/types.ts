// Types mirroring the backend Phase 9 response schemas.
export type JobStatus = "pending" | "running" | "complete" | "failed";

export interface Evidence {
  source_type: string;
  source: string;
  location?: string | null;
  excerpt?: string | null;
  metadata?: Record<string, unknown>;
}

export interface Finding {
  id: string;
  agent: string;
  category: string;
  title: string;
  severity: string;
  confidence: number;
  description: string;
  affected_components: string[];
  recommendation?: string | null;
  deterministic_signals: Record<string, unknown>;
  status: string;
  evidence: Evidence[];
}

export interface AnalysisStatus {
  node_status: Record<string, string>;
  incomplete: string[];
  failed: string[];
  skipped: string[];
}

export interface RunResults {
  run_id: string;
  repo_id: string;
  status: JobStatus;
  revision?: string | null;
  findings: Finding[];
  artifacts: Record<string, any>;
  analysis: AnalysisStatus;
}

export interface RunStatus {
  job_id: string;
  run_id: string;
  repo_id: string;
  status: JobStatus;
  revision?: string | null;
  error?: string | null;
  agent_status: Record<string, string>;
  repository?: {
    revision: string;
    size_mb: number;
    language: string;
    manifest_files: string[];
  } | null;
}

export interface SubmitResponse {
  job_id: string;
  run_id: string;
  repo_id: string;
  status: JobStatus;
}

export interface GraphNode {
  id: string;
  kind: string;
  name: string;
  file_path?: string | null;
  metadata?: Record<string, unknown>;
}
export interface GraphEdge {
  source: string;
  target: string;
  kind: string;
}
export interface RunGraph {
  run_id: string;
  revision?: string | null;
  nodes: GraphNode[];
  edges: GraphEdge[];
  available: boolean;
  note?: string | null;
}

export interface QueryAnswer {
  question: string;
  answer: string;
  intent: string;
  has_evidence: boolean;
  insufficient_evidence: boolean;
  sources: { source_type: string; source: string; location?: string | null }[];
}