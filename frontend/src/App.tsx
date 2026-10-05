import { useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import Dashboard from "./views/Dashboard";
import GraphExplorer from "./views/GraphExplorer";
import TechDebt from "./views/TechDebt";
import FindingDetail from "./views/FindingDetail";
import AgentTrace from "./views/AgentTrace";
import Copilot from "./views/Copilot";
import ModuleDetail from "./views/ModuleDetail";
import { RunContext } from "./RunContext";

const tabs = [
  { to: "/dashboard", label: "Dashboard" },
  { to: "/graph", label: "Graph" },
  { to: "/tech-debt", label: "Tech Debt" },
  { to: "/trace", label: "Agent Trace" },
  { to: "/copilot", label: "Copilot" },
  { to: "/module", label: "Module" },
];

export default function App() {
  const [jobId, setJobId] = useState<string>(
    () => localStorage.getItem("reposage.jobId") || ""
  );
  const update = (id: string) => {
    setJobId(id);
    localStorage.setItem("reposage.jobId", id);
  };

  return (
    <RunContext.Provider value={{ jobId, setJobId: update }}>
      <div className="min-h-screen">
        <header className="border-b border-slate-800 px-6 py-3 flex items-center gap-6">
          <span className="font-semibold text-lg text-emerald-400">RepoSage</span>
          <nav className="flex gap-1 text-sm">
            {tabs.map((t) => (
              <NavLink
                key={t.to}
                to={t.to}
                className={({ isActive }) =>
                  `px-3 py-1.5 rounded ${
                    isActive ? "bg-slate-800 text-white" : "text-slate-400 hover:text-white"
                  }`
                }
              >
                {t.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2 text-sm">
            <label className="text-slate-500">Job</label>
            <input
              value={jobId}
              onChange={(e) => update(e.target.value)}
              placeholder="job id"
              className="bg-slate-900 border border-slate-700 rounded px-2 py-1 w-56"
            />
          </div>
        </header>
        <main className="p-6">
          <Routes>
            <Route path="/" element={<Navigate to="/dashboard" replace />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/graph" element={<GraphExplorer />} />
            <Route path="/tech-debt" element={<TechDebt />} />
            <Route path="/findings/:findingId" element={<FindingDetail />} />
            <Route path="/trace" element={<AgentTrace />} />
            <Route path="/copilot" element={<Copilot />} />
            <Route path="/module" element={<ModuleDetail />} />
          </Routes>
        </main>
      </div>
    </RunContext.Provider>
  );
}