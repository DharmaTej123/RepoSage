import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useRun } from "../RunContext";
import { useResults } from "../components/useResults";
import { Empty, Panel, SeverityBadge, StatusPill } from "../components/ui";

type SortKey = "score" | "severity";

export default function TechDebt() {
  const { jobId } = useRun();
  const { data } = useResults(jobId);
  const [filter, setFilter] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("score");

  const ranked = (data?.artifacts?.tech_debt_report?.items || []) as any[];
  const findingsById = useMemo(() => {
    const m: Record<string, any> = {};
    data?.findings.forEach((f) => (m[f.id] = f));
    return m;
  }, [data]);

  const rows = useMemo(() => {
    let r = [...ranked];
    if (filter)
      r = r.filter(
        (x) =>
          x.title?.toLowerCase().includes(filter.toLowerCase()) ||
          x.category?.toLowerCase().includes(filter.toLowerCase())
      );
    r.sort((a, b) =>
      sortKey === "score" ? (b.score || 0) - (a.score || 0) : (a.severity || "").localeCompare(b.severity || "")
    );
    return r;
  }, [ranked, filter, sortKey]);

  if (!jobId) return <Empty msg="Select a job to view the tech-debt report." />;
  if (!data) return <Empty msg="Loading..." />;

  return (
    <Panel title="Technical-debt report (ranked by reproducible priority score)">
      <div className="flex gap-3 mb-3">
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="filter by title / category"
          className="bg-slate-900 border border-slate-700 rounded px-2 py-1 w-64 text-sm"
        />
        <select
          value={sortKey}
          onChange={(e) => setSortKey(e.target.value as SortKey)}
          className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-sm"
        >
          <option value="score">Sort: score</option>
          <option value="severity">Sort: severity</option>
        </select>
      </div>
      {rows.length === 0 ? (
        <Empty msg="No tech-debt items." />
      ) : (
        <table className="w-full text-sm">
          <thead className="text-slate-500 text-left">
            <tr>
              <th className="py-2">Score</th>
              <th>Title</th>
              <th>Severity</th>
              <th>Status</th>
              <th>Top signals</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((x) => (
              <tr key={x.finding_id} className="border-t border-slate-800">
                <td className="py-2 font-mono text-emerald-400">
                  {(x.score ?? 0).toFixed(3)}
                </td>
                <td className="pr-3">{x.title}</td>
                <td><SeverityBadge severity={x.severity} /></td>
                <td><StatusPill status={x.status} /></td>
                <td className="text-slate-400 text-xs">
                  {topSignals(x.contributing_signals)}
                </td>
                <td>
                  {findingsById[x.finding_id] && (
                    <Link
                      to={`/findings/${x.finding_id}`}
                      className="text-sky-400 hover:underline text-xs"
                    >
                      details
                    </Link>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="text-xs text-slate-500 mt-3">
        Scores are deterministic (weighted signal combination). Contributing signals
        are shown so each ranking is auditable.
      </p>
    </Panel>
  );
}

function topSignals(sig: Record<string, number> | undefined): string {
  if (!sig) return "";
  return Object.entries(sig)
    .filter(([, v]) => v > 0)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([k, v]) => `${k} ${v.toFixed(2)}`)
    .join(", ");
}