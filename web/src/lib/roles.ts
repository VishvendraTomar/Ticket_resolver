/**
 * Mirrors backend/app/tenancy/roles.py. The UI uses these only to hide
 * controls the API would refuse; the API is the authority.
 */

export const ROLES = [
  "owner",
  "admin",
  "policy_editor",
  "agent",
  "viewer",
  "integrator",
] as const;

export type Role = (typeof ROLES)[number];

export const ROLE_LABELS: Record<Role, string> = {
  owner: "Owner",
  admin: "Admin",
  policy_editor: "Policy editor",
  agent: "Agent",
  viewer: "Viewer",
  integrator: "Integrator",
};

export function canManageMembers(role: Role): boolean {
  return role === "owner" || role === "admin";
}

/** Admins manage everyone except owners; only owners create or change owners. */
export function canAssignRole(actor: Role, target: Role): boolean {
  if (actor === "owner") return true;
  if (actor === "admin") return target !== "owner";
  return false;
}

export function assignableRoles(actor: Role): Role[] {
  return ROLES.filter((r) => canAssignRole(actor, r));
}

/** Can `actor` change or remove a member who currently has `memberRole`? */
export function canEditMember(actor: Role, memberRole: Role): boolean {
  return canManageMembers(actor) && canAssignRole(actor, memberRole);
}
