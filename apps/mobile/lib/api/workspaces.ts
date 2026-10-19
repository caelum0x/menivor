/**
 * Workspaces domain — team workspaces, members, credits, RBAC, audit trail.
 * (POST/GET /workspaces, /workspaces/{id}/members, /workspaces/{id}/credits,
 *  GET /me/permissions, /me/workspaces/{id}/audit, /admin/*)
 */

export {
  adminImpersonate,
  adminListJobs,
  adminListUsers,
  adminListWorkspaces,
  createWorkspace,
  getMyPermissions,
  getWorkspaceCredits,
  grantWorkspaceCredits,
  inviteMember,
  leaveWorkspace,
  listAuditLog,
  listMembers,
  listMyWorkspaces,
  listWorkspaceMembers,
  removeMember,
  setMemberRole,
  updateMemberRole,
} from "@/lib/api";
