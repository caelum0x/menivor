/**
 * Pure helpers: API graph <-> React Flow nodes/edges, and a client-side pre-check that
 * mirrors the backend rules (the API stays the source of truth and re-checks on Save).
 */

import type { Edge, Node } from "@xyflow/react";

import type { ApiEdge, ApiNode, NodeData, NodeType, WorkflowGraph } from "./api";

export const NODE_TYPES: readonly NodeType[] = ["brief", "script", "images", "video", "captions", "approve", "publish"];
export const SPEND_TYPES: ReadonlySet<NodeType> = new Set(["images", "video"]);
export const PLATFORMS = ["tiktok", "instagram", "youtube_shorts"] as const;
export const MAX_NODES = 30;

export interface StepData extends NodeData {
  kind: NodeType;
  [key: string]: unknown;
}

export type StepNode = Node<StepData, "step">;

export function defaultData(kind: NodeType): NodeData {
  switch (kind) {
    case "brief":
      return { request: "" };
    case "script":
      return { seconds: 30 };
    case "images":
    case "video":
      return { count: 1 };
    case "captions":
      return { style: "clean" };
    case "publish":
      return { platforms: ["tiktok"] };
    default:
      return {};
  }
}

export function toFlow(graph: WorkflowGraph): { nodes: StepNode[]; edges: Edge[] } {
  const nodes: StepNode[] = graph.nodes.map((n) => ({
    id: n.id,
    type: "step",
    position: { x: n.position?.x ?? 0, y: n.position?.y ?? 0 },
    data: { ...defaultData(n.type), ...n.data, kind: n.type },
  }));
  const edges: Edge[] = graph.edges.map((e) => ({
    id: e.id ?? `${e.source}->${e.target}`,
    source: e.source,
    target: e.target,
  }));
  return { nodes, edges };
}

export function fromFlow(nodes: StepNode[], edges: Edge[]): WorkflowGraph {
  const apiNodes: ApiNode[] = nodes.map((n) => {
    const { kind, ...rest } = n.data;
    const data: NodeData = {};
    for (const key of ["request", "seconds", "count", "style", "platforms"] as const) {
      if (rest[key] !== undefined) (data as Record<string, unknown>)[key] = rest[key];
    }
    return { id: n.id, type: kind, position: { x: Math.round(n.position.x), y: Math.round(n.position.y) }, data };
  });
  const apiEdges: ApiEdge[] = edges.map((e) => ({ source: e.source, target: e.target }));
  return { nodes: apiNodes, edges: apiEdges };
}

export function nextNodeId(nodes: { id: string }[]): string {
  let i = nodes.length + 1;
  const ids = new Set(nodes.map((n) => n.id));
  while (ids.has(`n${i}`)) i += 1;
  return `n${i}`;
}

/** The first rule the graph breaks, as the same plain sentence the API uses; "" when it looks fine. */
export function precheck(graph: WorkflowGraph): string {
  const { nodes, edges } = graph;
  if (!nodes.length) return "Add a Brief to start the workflow.";
  if (nodes.length > MAX_NODES) return `A workflow has at most ${MAX_NODES} steps.`;
  const briefs = nodes.filter((n) => n.type === "brief");
  if (briefs.length !== 1) return "Use exactly one Brief.";
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const parents = new Map<string, Set<string>>();
  for (const n of nodes) parents.set(n.id, new Set());
  for (const e of edges) {
    if (!byId.has(e.source) || !byId.has(e.target)) return "A connection points at a missing step.";
    if (e.source === e.target) return "A step cannot connect to itself.";
    parents.get(e.target)!.add(e.source);
  }
  const brief = briefs[0]!;
  if (parents.get(brief.id)!.size) return "Nothing can come before the Brief.";
  // Kahn's algorithm for cycles.
  const indeg = new Map(nodes.map((n) => [n.id, parents.get(n.id)!.size]));
  const queue = nodes.filter((n) => indeg.get(n.id) === 0).map((n) => n.id);
  let seen = 0;
  while (queue.length) {
    const id = queue.shift()!;
    seen += 1;
    for (const e of edges) {
      if (e.source !== id) continue;
      indeg.set(e.target, indeg.get(e.target)! - 1);
      if (indeg.get(e.target) === 0) queue.push(e.target);
    }
  }
  if (seen !== nodes.length) return "The workflow loops back on itself; remove the loop.";
  const roots = nodes.filter((n) => parents.get(n.id)!.size === 0);
  if (roots.length !== 1) return "Connect every step to the Brief.";
  const memo = new Map<string, Set<NodeType>>();
  const before = (id: string): Set<NodeType> => {
    const hit = memo.get(id);
    if (hit) return hit;
    const out = new Set<NodeType>();
    memo.set(id, out);
    for (const p of parents.get(id)!) {
      out.add(byId.get(p)!.type);
      for (const t of before(p)) out.add(t);
    }
    return out;
  };
  for (const n of nodes) {
    const types = before(n.id);
    if (n.type === "captions" && !types.has("video")) return "Captions go after a Video.";
    if (n.type === "approve" && !["script", "images", "video"].some((t) => types.has(t as NodeType)))
      return "Approve goes after something to approve.";
    if (n.type === "publish" && !types.has("approve")) return "Publish needs an Approve before it.";
  }
  return "";
}

export const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"] as const;

export function stepStatusLabel(status: string): string {
  switch (status) {
    case "done":
      return "Done";
    case "pending_approval":
      return "Waiting for your approval";
    case "waiting":
      return "Approve the steps above";
    case "after_approval":
      return "Runs after approval";
    case "rejected":
      return "Rejected";
    case "failed":
      return "Failed";
    default:
      return status.replace(/_/g, " ");
  }
}

export function runStatusLabel(status: string): string {
  switch (status) {
    case "waiting_for_approval":
      return "Waiting for approval";
    case "publish_pending":
      return "Publish waiting for approval";
    case "done":
      return "Done";
    case "failed":
      return "Stopped";
    default:
      return status.replace(/_/g, " ");
  }
}
