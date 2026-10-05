import { useMemo, useState } from "react";
import { useRun } from "../RunContext";
import { useResults } from "../components/useResults";
import { Empty, Panel, SeverityBadge } from "../components/ui";

export default function ModuleDetail() {
  const { jobId } = useRun();
  const { data } = useResults(jobId);
  const [module, setModule] = useState("");

  const modules = useMemo(() => {
    const set = new Set<string>();
    data?.findings.forEach((f) => f.affected_components.forEach((c) => set.add(c)));
    (data?.artifacts?.onboarding?.reading_order || []).forEach((r: any) =>
      set.add(r.module)
    );
    return Array.from(set).sort();
  }, [data]);

  const selected = module || modules[0] || "";

  const findings = data?.findings.filter((f) =>
    f.affected_components.includes(selected)
  ) || [];

  const reading = (data?.artifacts?.onboarding?.reading_order || []).find(
    (r: any) => r.module === selected
  );
  const contributor = (data?.artifacts?.onboarding?.historical_contributors || []).find(
    (c: any) => c.module === selected
  );

  if (!jobId) return <Empty msg="Select a job to inspect a module." />;
  if (!data) return <Empty msg="Loading..." />;

  return (
    <div className="max-w-3xl grid gap-4">
      <Panel title="Module">
        <select
          value={selected}
          onChange={(e) => setModule(e.target.value)}
          className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-sm w-full"
        >
          {modules.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </Panel>

      <div className="grid grid-cols-2 gap-4">
        <Panel title="Centrality">
          {reading ? (
            <p className="text-sm text-slate-300">{reading.reason}</p>
          ) : (
            <Empty msg="Not in top-centrality set." />
          )}
        </Panel>
        <Panel title="Historical contribution">
          {contributor ? (
            <div className="text-sm">
              <div className="text-slate-200">{contributor.primary_contributor}</div>
              <div className="text-slate-500 text-xs">
                {(contributor.share * 100).toFixed(0)}% of recent commits
              </div>
              <div className="text-slate-500 text-xs mt-1">{contributor.note}</div>
            </div>
          ) : (
            <Empty msg="No ownership data." />
          )}
        </Panel>
      </div>

      <Panel title="Findings & risk explanation">
        {findings.length === 0 ? (
          <Empty msg="No findings for this module." />
        ) : (
          <ul className="grid gap-2 text-sm">
            {findings.map((f) => (
              <li key={f.id} className="border border-slate-800 rounded p-2">
                <div className="flex gap-2 items-center">
                  <SeverityBadge severity={f.severity} />
                  <span className="text-slate-200">{f.title}</span>
                </div>
                <p className="text-slate-400 text-xs mt-1">{f.description}</p>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}