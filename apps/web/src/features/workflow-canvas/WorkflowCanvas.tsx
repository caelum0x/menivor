"use client";

import * as React from "react";
import {
  addEdge,
  Background,
  Controls,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Loader2, Play, Plus, Save } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ErrorText, errorMessage, useRequestOptions } from "@/src/features/ad-studio/shared";
import { cn } from "@/lib/utils";
import {
  createWorkflow,
  getWorkflow,
  listWorkflows,
  runWorkflow,
  saveWorkflow,
  scheduleWorkflow,
  type NodeType,
  type Workflow,
  type WorkflowRun,
} from "./api";
import { defaultData, fromFlow, NODE_TYPES, nextNodeId, precheck, toFlow, type StepNode } from "./graph";
import { Inspector } from "./Inspector";
import { NODE_META, nodeTypes } from "./nodes";
import { RunPanel } from "./RunPanel";
import { SchedulePanel } from "./SchedulePanel";

function Palette({ onAdd }: { onAdd: (kind: NodeType) => void }) {
  return (
    <div className="flex flex-wrap gap-1.5" aria-label="Add a step">
      {NODE_TYPES.map((kind) => {
        const Icon = NODE_META[kind].icon;
        return (
          <button
            key={kind}
            type="button"
            className="neu-raised flex items-center gap-1.5 rounded-full px-3 py-1 text-xs text-muted-foreground hover:text-foreground"
            onClick={() => onAdd(kind)}
          >
            <Icon className="size-3.5" aria-hidden /> {NODE_META[kind].label}
          </button>
        );
      })}
    </div>
  );
}

function Editor() {
  const requestOptions = useRequestOptions();
  const [workflows, setWorkflows] = React.useState<Workflow[] | null>(null);
  const [current, setCurrent] = React.useState<Workflow | null>(null);
  const [name, setName] = React.useState("");
  const [nodes, setNodes, onNodesChange] = useNodesState<StepNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const [runs, setRuns] = React.useState<WorkflowRun[]>([]);
  const [problem, setProblem] = React.useState("");
  const [notice, setNotice] = React.useState("");
  const [error, setError] = React.useState("");
  const [busy, setBusy] = React.useState<"" | "save" | "run" | "schedule" | "new">("");

  const open = React.useCallback(
    async (wf: Workflow) => {
      setCurrent(wf);
      setName(wf.name);
      const flow = toFlow(wf.graph);
      setNodes(flow.nodes);
      setEdges(flow.edges);
      setSelectedId(null);
      setProblem("");
      setNotice("");
      try {
        const detail = await getWorkflow(wf.id, await requestOptions());
        setRuns(detail.runs);
      } catch {
        setRuns([]);
      }
    },
    [requestOptions, setEdges, setNodes],
  );

  React.useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const data = await listWorkflows(await requestOptions());
        if (!alive) return;
        setWorkflows(data.workflows);
        if (data.workflows[0]) await open(data.workflows[0]);
      } catch (err) {
        if (alive) setError(errorMessage(err));
      }
    })();
    return () => {
      alive = false;
    };
  }, [open, requestOptions]);

  const graph = React.useMemo(() => fromFlow(nodes, edges), [nodes, edges]);
  React.useEffect(() => setProblem(precheck(graph)), [graph]);

  const onConnect = React.useCallback((c: Connection) => setEdges((eds) => addEdge(c, eds)), [setEdges]);

  const addNode = (kind: NodeType) => {
    setNodes((list) => {
      const id = nextNodeId(list);
      const last = list[list.length - 1];
      const position = last ? { x: last.position.x + 220, y: last.position.y } : { x: 40, y: 120 };
      return [...list, { id, type: "step", position, data: { ...defaultData(kind), kind } }];
    });
  };

  const patchNode = (id: string, patch: Partial<StepNode["data"]>) =>
    setNodes((list) => list.map((n) => (n.id === id ? { ...n, data: { ...n.data, ...patch } } : n)));

  const save = async (): Promise<Workflow | null> => {
    if (!current) return null;
    setBusy("save");
    setError("");
    try {
      const saved = await saveWorkflow(current.id, { name, graph }, await requestOptions());
      setCurrent(saved);
      setWorkflows((list) => (list ?? []).map((w) => (w.id === saved.id ? saved : w)));
      setNotice("Saved.");
      return saved;
    } catch (err) {
      setError(errorMessage(err));
      setNotice("");
      return null;
    } finally {
      setBusy("");
    }
  };

  const run = async () => {
    if (!current) return;
    const saved = await save();
    if (!saved) return;
    setBusy("run");
    try {
      const out = await runWorkflow(saved.id, await requestOptions());
      setRuns((list) => [out, ...list]);
      setNotice("Run started. Free steps are done; the rest wait for your approval.");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy("");
    }
  };

  const createNew = async () => {
    setBusy("new");
    setError("");
    try {
      const wf = await createWorkflow("New workflow", await requestOptions());
      setWorkflows((list) => [wf, ...(list ?? [])]);
      await open(wf);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy("");
    }
  };

  const saveSchedule = async (value: { enabled: boolean; weekday: number | null; hour: number }) => {
    if (!current) return;
    setBusy("schedule");
    setError("");
    try {
      const wf = await scheduleWorkflow(current.id, value, await requestOptions());
      setCurrent(wf);
      setNotice(value.enabled ? "Schedule saved." : "Schedule turned off.");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy("");
    }
  };

  const selected = nodes.find((n) => n.id === selectedId) ?? null;

  return (
    <div className="grid gap-4 lg:grid-cols-[200px_minmax(0,1fr)_260px]">
      <aside className="glass-subtle space-y-3 rounded-2xl p-3" aria-label="Workflows">
        <Button size="sm" variant="secondary" className="w-full" onClick={createNew} disabled={busy === "new"}>
          <Plus aria-hidden /> New workflow
        </Button>
        {workflows === null ? (
          <Loader2 className="size-4 animate-spin text-muted-foreground" aria-label="Loading" />
        ) : workflows.length === 0 ? (
          <p className="text-xs text-muted-foreground">No workflows yet.</p>
        ) : (
          <ul className="space-y-1">
            {workflows.map((w) => (
              <li key={w.id}>
                <button
                  type="button"
                  onClick={() => void open(w)}
                  className={cn(
                    "w-full truncate rounded-lg px-2 py-1.5 text-left text-sm",
                    current?.id === w.id ? "neu-pressed text-foreground" : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {w.name}
                </button>
              </li>
            ))}
          </ul>
        )}
      </aside>

      <section className="min-w-0 space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <Input
            aria-label="Workflow name"
            className="max-w-xs"
            value={name}
            maxLength={200}
            onChange={(e) => setName(e.target.value)}
            disabled={!current}
          />
          <Button size="sm" variant="ghost" onClick={() => void save()} disabled={!current || busy !== ""}>
            <Save aria-hidden /> Save
          </Button>
          <Button size="sm" className="ml-auto" onClick={() => void run()} disabled={!current || busy !== "" || !!problem}>
            {busy === "run" ? <Loader2 className="animate-spin" aria-hidden /> : <Play aria-hidden />} Run now
          </Button>
        </div>
        <Palette onAdd={addNode} />
        <div className="glass-subtle h-[460px] overflow-hidden rounded-2xl" data-testid="canvas">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={(_, n) => setSelectedId(n.id)}
            onPaneClick={() => setSelectedId(null)}
            deleteKeyCode={["Backspace", "Delete"]}
            colorMode="dark"
            fitView
            proOptions={{ hideAttribution: true }}
          >
            <Background gap={24} size={1} />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>
        {problem ? (
          <p className="text-sm text-amber-300" role="status">
            {problem}
          </p>
        ) : null}
        <ErrorText message={error} />
        {notice && !error ? (
          <p className="text-sm text-muted-foreground" role="status">
            {notice}
          </p>
        ) : null}
      </section>

      <aside className="space-y-4">
        <div className="glass-subtle rounded-2xl p-3">
          <Inspector node={selected} onChange={patchNode} />
        </div>
        {current ? (
          <div className="glass-subtle rounded-2xl p-3">
            <SchedulePanel schedule={current.schedule} busy={busy === "schedule"} onSave={(v) => void saveSchedule(v)} />
          </div>
        ) : null}
        {runs[0] ? (
          <div className="glass-subtle rounded-2xl p-3">
            <RunPanel run={runs[0]} />
          </div>
        ) : null}
      </aside>
    </div>
  );
}

/** Workflow canvas: brief -> script -> images -> video -> captions -> approve -> publish, saved and scheduled. */
export function WorkflowCanvas() {
  return (
    <ReactFlowProvider>
      <Editor />
    </ReactFlowProvider>
  );
}
