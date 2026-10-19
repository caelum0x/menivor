/** First-party ComfyUI workflow descriptors + registry (mirror of `catalog.py`). */

import type { WorkflowDescriptor } from "./pin.js";

const CATALOG: Record<string, WorkflowDescriptor> = {
  "wan-i2v": {
    slug: "wan-i2v",
    category: "i2v",
    description: "Wan 2.2 image-to-video (A14B).",
    node_commits: {
      WanVideoWrapper: "a1b2c3d",
      "ComfyUI-VideoHelperSuite": "e4f5a6b",
    },
    weight_refs: ["wan2.2-i2v-a14b.safetensors", "umt5-xxl-enc.safetensors"],
    inputs: [
      { name: "image", type: "image", required: true },
      { name: "frames", type: "int", default: 81, min: 16, max: 161 },
      { name: "steps", type: "int", default: 20, min: 1, max: 60 },
    ],
  },
  "flux-first-frame": {
    slug: "flux-first-frame",
    category: "t2i",
    description: "FLUX first-frame T2I (schnell).",
    node_commits: { ComfyUI: "8f37cf8" },
    weight_refs: ["flux1-schnell.safetensors", "t5xxl_fp8.safetensors"],
    inputs: [
      { name: "prompt", type: "string", required: true },
      { name: "steps", type: "int", default: 4, min: 1, max: 12 },
    ],
  },
  "lipsync-musetalk": {
    slug: "lipsync-musetalk",
    category: "lipsync",
    description: "MuseTalk real-time lipsync.",
    node_commits: { "ComfyUI-MuseTalk": "c7d8e9f" },
    weight_refs: ["musetalk.pth", "sd-vae-ft-mse.safetensors"],
    inputs: [
      { name: "video", type: "video", required: true },
      { name: "audio", type: "audio", required: true },
    ],
  },
};

export function getWorkflow(slug: string): WorkflowDescriptor {
  const w = CATALOG[slug];
  if (!w) throw new Error(`unknown workflow ${slug}`);
  return w;
}

export function listWorkflows(category?: string): string[] {
  return Object.keys(CATALOG)
    .filter((s) => category === undefined || CATALOG[s].category === category)
    .sort();
}
