import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useRun } from "../RunContext";
import { Empty, Panel } from "../components/ui";
import type { RunStatus } from "../api/types";

export default function AgentTrace() {
  const { jobId } = useRun();
  const [status, setStatus] = useState<RunStatus | null>(null);

  useEffect(() => {
    if (!jobId) return;
    api.status(jobId).then(setStatus).catch(() => setStatus(null));
  }, [jobId]);

  if (!jobId) return <Empty msg="Select a job to view its agent trace." />;
  if (!status) return <Empty msg="Loading trace..." />;

  const nodes = Object.entries(status.agent_status || {});

  return (
    <Panel title="Agent / node trace">
      {nodes.length === 0 ? (
        <Empty msg="No node status recorded yet." />
      ) : (
        <div className="grid gap-2">
          {nodes.map(([node, st]) => (
            <div
              key={node}
              className="flex items-center gap-3 border border-slate-800 rounded p-2 text-sm"
            >
              <span className={`w-2 h-2 rounded-full ${dot(st)}`} />
              <span className="font-medium text-slate-200 w-40">{node}</span>
              <span className="text-slate-400">{st}</span>
            </div>
          ))}
        </div>
      )}
      <p className="text-xs text-slate-500 mt-3">
        Detailed metrics (latency, retries, tool calls, tokens) are recorded per node
        in the backend agent_metrics table; deterministic and LLM work are tracked
        separately (llm_tokens = 0 for deterministic nodes).
      </p>
    </Panel>
  );
}

function dot(st: string): string {
  if (st === "complete") return "bg-emerald-500";
  if (st === "failed") return "bg-red-500";
  if (st === "skipped" || st === "not_applicable") return "bg-slate-500";
  if (st === "no_finding") return "bg-sky-500";
  return "bg-amber-500";
}