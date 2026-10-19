/**
 * `@reelforge/comfy-workflow-schema` — ComfyUI graphs as pinned, versioned
 * artifacts (node commits + weight refs + input contract locked per version).
 * Byte-identical to the Python port (`reelforge_comfy_workflow`, golden
 * fixtures) so the render-farm registry, adapters, and desktop all reference one
 * immutable workflow identity.
 */

export {
  graphHash,
  validateInputs,
  type InputSlot,
  type WorkflowDescriptor,
} from "./pin.js";
export { getWorkflow, listWorkflows } from "./catalog.js";
