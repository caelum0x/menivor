/**
 * Workflow canvas client: saved workflows, runs and schedules. Every call goes to
 * `/api/v1/workflows...`. Spend and publish steps only become pending approvals.
 */

import { apiRequest, type RequestOptions } from "@/src/shared/api";
import { apiPath } from "@/src/shared/api/path";

export type NodeType = "brief" | "script" | "images" | "video" | "captions" | "approve" | "publish";

export interface NodeData {
  request?: string;
  seconds?: number;
  count?: number;
  style?: "clean" | "bold";
  platforms?: string[];
}

export interface ApiNode {
  id: string;
  type: NodeType;
  position: { x: number; y: number };
  data: NodeData;
}

export interface ApiEdge {
  id?: string;
  source: string;
  target: string;
}

export interface WorkflowGraph {
  nodes: ApiNode[];
  edges: ApiEdge[];
}

export interface WorkflowSchedule {
  enabled: boolean;
  weekday: number | null;
  hour: number;
  label: string;
  next_run_at: string | null;
  last_run_at: string | null;
}

export interface Workflow {
  id: string;
  name: string;
  space_id: string | null;
  graph: WorkflowGraph;
  schedule: WorkflowSchedule;
  updated_at: string | null;
}

export interface NodeTypeInfo {
  type: NodeType;
  label: string;
  spends: boolean;
  help: string;
}

export interface RunStep {
  node_id: string;
  type: NodeType;
  label: string;
  status: string;
  output?: string;
  action_id?: string;
  credits?: number;
  platforms?: string[];
}

export interface WorkflowRun {
  id: string;
  workflow_id: string;
  trigger: string;
  status: string;
  steps: RunStep[];
  error: string;
  created_at: string | null;
}

export interface WorkflowListing {
  workflows: Workflow[];
  node_types: NodeTypeInfo[];
  starter: WorkflowGraph;
}


export function listWorkflows(options?: RequestOptions): Promise<WorkflowListing> {
  return apiRequest<WorkflowListing>("/workflows", { options });
}

export async function createWorkflow(name: string, options?: RequestOptions): Promise<Workflow> {
  const out = await apiRequest<{ workflow: Workflow }>("/workflows", { method: "POST", body: { name }, options });
  return out.workflow;
}

export function getWorkflow(id: string, options?: RequestOptions): Promise<{ workflow: Workflow; runs: WorkflowRun[] }> {
  return apiRequest(apiPath`/workflows/${id}`, { options });
}

export async function saveWorkflow(
  id: string,
  body: { name?: string; graph?: WorkflowGraph },
  options?: RequestOptions,
): Promise<Workflow> {
  const out = await apiRequest<{ workflow: Workflow }>(apiPath`/workflows/${id}`, { method: "PUT", body, options });
  return out.workflow;
}

export async function runWorkflow(id: string, options?: RequestOptions): Promise<WorkflowRun> {
  const out = await apiRequest<{ run: WorkflowRun }>(apiPath`/workflows/${id}/run`, { method: "POST", options });
  return out.run;
}

export async function scheduleWorkflow(
  id: string,
  body: { enabled: boolean; weekday: number | null; hour: number },
  options?: RequestOptions,
): Promise<Workflow> {
  const out = await apiRequest<{ workflow: Workflow }>(apiPath`/workflows/${id}/schedule`, {
    method: "PUT",
    body,
    options,
  });
  return out.workflow;
}
