import { useState } from "react";
import { api } from "../api/client";
import { useRun } from "../RunContext";
import { Empty, Panel } from "../components/ui";
import type { QueryAnswer } from "../api/types";

interface Msg {
  question: string;
  answer: QueryAnswer | null;
  pending: boolean;
  error?: string;
}

const SUGGESTIONS = [
  "What depends on PaymentService?",
  "What is the blast radius of changing pkg.utils?",
  "Who has historically worked on this module?",
  "What should I read first?",
];

export default function Copilot() {
  const { jobId } = useRun();
  const [q, setQ] = useState("");
  const [msgs, setMsgs] = useState<Msg[]>([]);

  async function ask(question: string) {
    if (!question.trim() || !jobId) return;
    const idx = msgs.length;
    setMsgs((m) => [...m, { question, answer: null, pending: true }]);
    setQ("");
    try {
      const a = await api.query(jobId, question);
      setMsgs((m) => m.map((x, i) => (i === idx ? { ...x, answer: a, pending: false } : x)));
    } catch (e) {
      setMsgs((m) =>
        m.map((x, i) => (i === idx ? { ...x, pending: false, error: String(e) } : x))
      );
    }
  }

  if (!jobId) return <Empty msg="Select a job to ask the copilot about the repository." />;

  return (
    <div className="max-w-3xl grid gap-4">
      <Panel title="Repository copilot">
        <div className="flex flex-wrap gap-2 mb-3">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              onClick={() => ask(s)}
              className="text-xs border border-slate-700 rounded px-2 py-1 text-slate-300 hover:bg-slate-800"
            >
              {s}
            </button>
          ))}
        </div>
        <div className="flex gap-2">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && ask(q)}
            placeholder="Ask about dependencies, ownership, risk, reading order..."
            className="flex-1 bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm"
          />
          <button
            onClick={() => ask(q)}
            className="bg-emerald-600 hover:bg-emerald-500 rounded px-4"
          >
            Ask
          </button>
        </div>
      </Panel>

      <div className="grid gap-3">
        {msgs.map((m, i) => (
          <div key={i} className="grid gap-2">
            <div className="text-right text-sm text-slate-300">
              <span className="bg-slate-800 rounded px-3 py-1.5 inline-block">
                {m.question}
              </span>
            </div>
            <Panel>
              {m.pending && <span className="text-slate-500 text-sm">Thinking...</span>}
              {m.error && <span className="text-red-400 text-sm">{m.error}</span>}
              {m.answer && (
                <>
                  {m.answer.insufficient_evidence && (
                    <div className="text-amber-400 text-xs mb-2">
                      Guardrail: insufficient evidence to answer reliably.
                    </div>
                  )}
                  <pre className="text-sm text-slate-200 whitespace-pre-wrap">
                    {m.answer.answer}
                  </pre>
                  {m.answer.sources.length > 0 && (
                    <div className="mt-3 border-t border-slate-800 pt-2">
                      <div className="text-xs text-slate-500 mb-1">Sources</div>
                      <ul className="text-xs text-slate-400 grid gap-1">
                        {m.answer.sources.map((s, j) => (
                          <li key={j}>
                            <span className="bg-slate-800 rounded px-1.5 py-0.5 mr-2">
                              {s.source_type}
                            </span>
                            <span className="font-mono">{s.source}</span>
                            {s.location && <span className="ml-2">{s.location}</span>}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </>
              )}
            </Panel>
          </div>
        ))}
      </div>
    </div>
  );
}