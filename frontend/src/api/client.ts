import type {
  QueryAnswer,
  RunGraph,
  RunResults,
  RunStatus,
  SubmitResponse,
} from "./types";

const BASE = "/api";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  submitRun: (body: { repo_url?: string; repo_path?: string; objective?: string }) =>
    req<SubmitResponse>("/runs", { method: "POST", body: JSON.stringify(body) }),
  status: (jobId: string) => req<RunStatus>(`/runs/${jobId}/status`),
  results: (jobId: string) => req<RunResults>(`/runs/${jobId}/results`),
  graph: (jobId: string) => req<RunGraph>(`/runs/${jobId}/graph`),
  finding: (jobId: string, findingId: string) =>
    req(`/runs/${jobId}/findings/${findingId}`),
  query: (jobId: string, question: string) =>
    req<QueryAnswer>(`/runs/${jobId}/query`, {
      method: "POST",
      body: JSON.stringify({ question }),
    }),
  history: (repoId: string) => req(`/repos/${repoId}/history`),
};