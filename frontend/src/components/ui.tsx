import type { ReactNode } from "react";

export function Panel({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <div className="bg-slate-900/60 border border-slate-800 rounded-lg p-4">
      {title && <h2 className="text-sm font-semibold text-slate-300 mb-3">{title}</h2>}
      {children}
    </div>
  );
}

const SEV: Record<string, string> = {
  critical: "bg-red-600",
  high: "bg-orange-600",
  medium: "bg-amber-600",
  low: "bg-sky-700",
  info: "bg-slate-600",
};

export function SeverityBadge({ severity }: { severity: string }) {
  return (
    <span className={`text-xs px-2 py-0.5 rounded ${SEV[severity] || "bg-slate-600"}`}>
      {severity}
    </span>
  );
}

const STATUS: Record<string, string> = {
  validated: "text-emerald-400",
  disputed: "text-red-400",
  inferred: "text-amber-400",
  observed: "text-slate-300",
};

export function StatusPill({ status }: { status: string }) {
  return <span className={`text-xs ${STATUS[status] || "text-slate-300"}`}>{status}</span>;
}

export function Empty({ msg }: { msg: string }) {
  return <div className="text-slate-500 text-sm py-8 text-center">{msg}</div>;
}