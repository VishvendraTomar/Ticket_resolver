import { describe, expect, it } from "vitest";

import { assignableRoles, canEditMember, canManageMembers, ROLES } from "@/lib/roles";

describe("role rules (mirror backend/app/tenancy/roles.py)", () => {
  it("only owners and admins manage members", () => {
    expect(ROLES.filter(canManageMembers)).toEqual(["owner", "admin"]);
  });

  it("owners assign every role; admins every role but owner; others none", () => {
    expect(assignableRoles("owner")).toEqual([...ROLES]);
    expect(assignableRoles("admin")).not.toContain("owner");
    expect(assignableRoles("admin")).toHaveLength(ROLES.length - 1);
    for (const r of ["policy_editor", "agent", "viewer", "integrator"] as const) {
      expect(assignableRoles(r)).toEqual([]);
    }
  });

  it("admins can't edit owners", () => {
    expect(canEditMember("admin", "owner")).toBe(false);
    expect(canEditMember("admin", "agent")).toBe(true);
    expect(canEditMember("owner", "owner")).toBe(true);
    expect(canEditMember("agent", "viewer")).toBe(false);
  });
});

describe("knowledge-base editors (mirror backend EDITORS)", () => {
  it("owners, admins and policy editors edit; others read", async () => {
    const { canEditKnowledge } = await import("@/lib/roles");
    expect(ROLES.filter(canEditKnowledge)).toEqual(["owner", "admin", "policy_editor"]);
  });
});
