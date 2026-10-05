import { useEffect, useMemo, useState } from "react";
import ReactFlow, { Background, Controls, type Edge, type Node } from "reactflow";
import "reactflow/dist/style.css";
import { api } from "../api/client";
import { useRun } from "../RunContext";
import { Empty, Panel } from "../components/ui";
import type { RunGraph } from "../api/types";

export default function GraphExplorer() {
  const { jobId } = useRun();
  const [graph, setGraph] = useState<RunGraph | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!jobId) return;
    api.graph(jobId).then(setGraph).catch((e) => setErr(String(e)));
  }, [jobId]);

  const { nodes, edges } = useMemo(() => buildFlow(graph), [graph]);

  if (!jobId) return <Empty msg="Select a job to explore its architecture graph." />;
  if (err) return <Panel><p className="text-red-400 text-sm">{err}</p></Panel>;
  if (!graph) return <Empty msg="Loading graph..." />;
  if (!graph.available)
    return (
      <Panel title="Architecture graph">
        <p className="text-slate-400 text-sm">{graph.note}</p>
        <p className="text-slate-500 text-xs mt-2">
          The graph is stored in the graph store (Neo4j / in-memory) for reasoning
          queries. Enable graph embedding in run artifacts to visualize it here.
        </p>
      </Panel>
    );

  return (
    <div className="h-[75vh] border border-slate-800 rounded-lg overflow-hidden">
      <ReactFlow nodes={nodes} edges={edges} fitView>
        <Background />
        <Controls />
      </ReactFlow>
    </div>
  );
}

function buildFlow(graph: RunGraph | null): { nodes: Node[]; edges: Edge[] } {
  if (!graph) return { nodes: [], edges: [] };
  const modules = graph.nodes.filter((n) => n.kind === "module");
  const cols = Math.ceil(Math.sqrt(modules.length || 1));
  const nodes: Node[] = modules.map((n, i) => ({
    id: n.id,
    data: { label: n.name },
    position: { x: (i % cols) * 220, y: Math.floor(i / cols) * 120 },
    style: {
      background: "#0f172a",
      color: "#e2e8f0",
      border: "1px solid #334155",
      borderRadius: 8,
      fontSize: 12,
      padding: 6,
    },
  }));
  const modIds = new Set(modules.map((m) => m.id));
  const edges: Edge[] = graph.edges
    .filter((e) => e.kind === "IMPORTS" && modIds.has(e.source) && modIds.has(e.target))
    .map((e, i) => ({
      id: `e${i}`,
      source: e.source,
      target: e.target,
      animated: false,
      style: { stroke: "#475569" },
    }));
  return { nodes, edges };
}