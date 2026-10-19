/**
 * Route: /jobs/reels/tasks — the global async task queue (live running tasks).
 *
 * NAV MANIFEST (for integration):
 *   { route: "/jobs/reels/tasks",             title: "Tasks" }
 *   { route: "/jobs/reels/tasks/[id]",        title: "Task" }
 *   { route: "/jobs/reels/batch/[batchId]",   title: "Batch" }
 *
 * Endpoints: GET /api/v1/tasks (list + poll), GET /api/v1/tasks/{task_id},
 * DELETE /api/v1/tasks/{task_id}, GET /api/v1/batches/{batch_id}.
 */
export { TasksScreen as default } from "@/src/features/task-queue";
