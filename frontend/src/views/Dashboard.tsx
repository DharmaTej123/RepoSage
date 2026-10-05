import { useState } from "react";
import { api } from "../api/client";
import { useRun } from "../RunContext";
import { useResults } from "../components/useResults";
import { Empty, Panel, SeverityBadge } from "../components/ui";

export default function Dashboard() {
  const { jobId, setJobId } = useRun();
  const { data, error, loading } = useResults(jobId);
  const [repoPath, setRepoPath] = useState("");
  const [repoUrl, setRepoUrl] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitErr, setSubmitErr] = useState<string | null>(null);

  async function submit() {
    setSubmitting(true);
    setSubmitErr(null);
    try {
      const body = repoUrl ? { repo_url: repoUrl } : { repo_path: repoPath };
      const res = await api.submitRun(body);
      setJobId(res.job_id);
    } catch (e) {
      setSubmitErr(String(e));
    } finally {
      setSubmitting(false);
    }
  }

  const severityCounts: Record<string, number> = {};
  data?.findings.forEach((f) => {
    severityCounts[f.severity] = (severityCounts[f.severity] || 0) + 1;
  });

  return (
    <div className="grid gap-6 max-w-5xl">
      <Panel title="Analyze a repository">
        <div className="flex flex-wrap gap-3 items-end">
          <div className="flex flex-col gap-1">
            <label className="text-xs text-slate-500">Local repo path</label>
            <input
              value={repoPath}
              onChange={(e) => setRepoPath(e.target.value)}
              placeholder="/path/to/repo"
              className="bg-slate-900 border border-slate-700 rounded px-2 py-1 w-72"
            />
          </div>
          <span className="text-slate-600 pb-1">or</span>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-slate-500">Git URL</label>
            <input
              value={repoUrl}
              onChange={(e) => setRepoUrl(e.target.value)}
              placeholder="https://github.com/org/repo.git"
              className="bg-slate-900 border border-slate-700 rounded px-2 py-1 w-72"
            />
          </div>
          <button
            onClick={submit}
            disabled={submitting || (!repoPath && !repoUrl)}
            className="bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 rounded px-4 py-1.5"
          >
            {submitting ? "Submitting..." : "Analyze"}
          </button>
        </div>
        {submitErr && <p className="text-red-400 text-sm mt-2">{submitErr}</p>}
      </Panel>

      {!jobId && <Empty msg="Submit a repository or enter a job id to view results." />}
      {loading && <Empty msg="Loading run..." />}
      {error && <Panel><p className="text-red-400 text-sm">{error}</p></Panel>}

      {data && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <Stat label="Status" value={data.status} />
            <Stat label="Findings" value={String(data.findings.length)} />
            <Stat label="Revision" value={(data.revision || "-").slice(0, 10)} />
            <Stat
              label="Incomplete analyses"
              value={String(data.analysis.incomplete.length + data.analysis.failed.length)}
            />
          </div>

          <Panel title="Severity breakdown">
            {Object.keys(severityCounts).length === 0 ? (
              <Empty msg="No findings." />
            ) : (
              <div className="flex flex-wrap gap-3">
                {Object.entries(severityCounts).map(([sev, n]) => (
                  <div key={sev} className="flex items-center gap-2">
                    <SeverityBadge severity={sev} />
                    <span className="text-slate-300">{n}</span>
                  </div>
                ))}
              </div>
            )}
          </Panel>

          <Panel title="Analysis completeness">
            <div className="grid gap-2 text-sm">
              {Object.entries(data.analysis.node_status).map(([node, st]) => (
                <div key={node} className="flex justify-between border-b border-slate-800 py-1">
                  <span className="text-slate-300">{node}</span>
                  <span
                    className={
                      st === "complete"
                        ? "text-emerald-400"
                        : st === "failed"
                        ? "text-red-400"
                        : st === "no_finding"
                        ? "text-slate-400"
                        : "text-amber-400"
                    }
                  >
                    {st}
                  </span>
                </div>
              ))}
            </div>
            {(data.analysis.skipped.length > 0 || data.analysis.failed.length > 0) && (
              <p className="text-xs text-slate-500 mt-3">
                Skipped/failed analyses are shown explicitly; their absence is not a
                clean result.
              </p>
            )}
          </Panel>
        </>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-slate-900/60 border border-slate-800 rounded-lg p-4">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="text-xl font-semibold mt-1">{value}</div>
    </div>
  );
}