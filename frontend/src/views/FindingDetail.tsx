import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api } from "../api/client";
import { useRun } from "../RunContext";
import { Empty, Panel, SeverityBadge, StatusPill } from "../components/ui";
import type { Finding } from "../api/types";

export default function FindingDetail() {
  const { findingId } = useParams();
  const { jobId } = useRun();
  const [f, setF] = useState<Finding | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!jobId || !findingId) return;
    api.finding(jobId, findingId).then((d) => setF(d as Finding)).catch((e) => setErr(String(e)));
  }, [jobId, findingId]);

  if (err) return <Panel><p className="text-red-400 text-sm">{err}</p></Panel>;
  if (!f) return <Empty msg="Loading finding..." />;

  return (
    <div className="max-w-3xl grid gap-4">
      <Link to="/tech-debt" className="text-sky-400 text-sm hover:underline">
        &larr; back to tech debt
      </Link>
      <Panel>
        <div className="flex items-center gap-3 mb-2">
          <SeverityBadge severity={f.severity} />
          <StatusPill status={f.status} />
          <span className="text-xs text-slate-500">{f.agent} / {f.category}</span>
          <span className="ml-auto text-xs text-slate-500">
            confidence {(f.confidence * 100).toFixed(0)}%
          </span>
        </div>
        <h1 className="text-lg font-semibold">{f.title}</h1>
        <p className="text-slate-300 mt-2 text-sm">{f.description}</p>
        {f.recommendation && (
          <p className="text-emerald-300 mt-3 text-sm">
            <span className="text-slate-500">Recommendation: </span>
            {f.recommendation}
          </p>
        )}
        {f.affected_components.length > 0 && (
          <p className="text-xs text-slate-500 mt-3">
            Affects: {f.affected_components.join(", ")}
          </p>
        )}
      </Panel>

      <Panel title="Evidence (provenance)">
        {f.evidence.length === 0 ? (
          <Empty msg="No evidence records." />
        ) : (
          <ul className="grid gap-2 text-sm">
            {f.evidence.map((e, i) => (
              <li key={i} className="border border-slate-800 rounded p-2">
                <div className="flex gap-2 items-center">
                  <span className="text-xs bg-slate-700 px-2 py-0.5 rounded">
                    {e.source_type}
                  </span>
                  <span className="font-mono text-slate-300">{e.source}</span>
                  {e.location && <span className="text-slate-500">{e.location}</span>}
                </div>
                {e.excerpt && (
                  <pre className="text-xs text-slate-400 mt-1 whitespace-pre-wrap">
                    {e.excerpt}
                  </pre>
                )}
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel title="Deterministic signals">
        <pre className="text-xs text-slate-400">
          {JSON.stringify(f.deterministic_signals, null, 2)}
        </pre>
      </Panel>
    </div>
  );
}