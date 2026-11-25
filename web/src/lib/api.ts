/** Typed client for the FastAPI backend (/v1). Shapes mirror backend/app/tenancy/schemas.py. */

import type { Role } from "@/lib/roles";

export type UserOut = { id: string; email: string | null; name: string | null };
export type MyWorkspace = { id: string; name: string; role: Role };
export type MeOut = { user: UserOut; workspaces: MyWorkspace[] };
export type WorkspaceOut = { id: string; name: string; created_at: string };
export type MemberOut = { id: string; user: UserOut; role: Role; created_at: string };

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Turn any error body the API can return into an ApiError. */
export function toApiError(status: number, body: unknown): ApiError {
  if (body && typeof body === "object") {
    const b = body as Record<string, unknown>;
    // Domain errors: {"error": {"code", "message"}}
    const err = b.error as { code?: unknown; message?: unknown } | undefined;
    if (err && typeof err.message === "string") {
      return new ApiError(status, typeof err.code === "string" ? err.code : "error", err.message);
    }
    // FastAPI validation errors: {"detail": [{"msg": ...}]} or {"detail": "..."}
    if (Array.isArray(b.detail) && b.detail.length > 0) {
      const first = b.detail[0] as { msg?: unknown };
      if (typeof first.msg === "string") return new ApiError(status, "invalid", first.msg);
    }
    if (typeof b.detail === "string") return new ApiError(status, "error", b.detail);
  }
  return new ApiError(status, "error", `Request failed (${status})`);
}

type Options = {
  baseUrl: string;
  getToken: () => Promise<string | null>;
  onUnauthorized?: () => void;
  fetchImpl?: typeof fetch;
};

export function createApi({ baseUrl, getToken, onUnauthorized, fetchImpl }: Options) {
  const doFetch = fetchImpl ?? ((...args: Parameters<typeof fetch>) => fetch(...args));

  async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const token = await getToken();
    if (!token) throw new ApiError(401, "unauthenticated", "Not signed in");
    let response: Response;
    try {
      response = await doFetch(`${baseUrl}${path}`, {
        method,
        headers: {
          Authorization: `Bearer ${token}`,
          ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch {
      throw new ApiError(0, "network", `Can't reach the API at ${baseUrl}`);
    }
    if (response.status === 204) return undefined as T;
    const data: unknown = await response.json().catch(() => null);
    if (!response.ok) {
      if (response.status === 401) onUnauthorized?.();
      throw toApiError(response.status, data);
    }
    return data as T;
  }

  const ws = (id: string) => `/v1/workspaces/${encodeURIComponent(id)}`;

  return {
    me: () => request<MeOut>("GET", "/v1/me"),
    createWorkspace: (name: string) => request<WorkspaceOut>("POST", "/v1/workspaces", { name }),
    getWorkspace: (id: string) => request<WorkspaceOut>("GET", ws(id)),
    listMembers: (id: string) => request<MemberOut[]>("GET", `${ws(id)}/members`),
    addMember: (id: string, email: string, role: Role) =>
      request<MemberOut>("POST", `${ws(id)}/members`, { email, role }),
    changeRole: (id: string, membershipId: string, role: Role) =>
      request<MemberOut>("PATCH", `${ws(id)}/members/${encodeURIComponent(membershipId)}`, {
        role,
      }),
    removeMember: (id: string, membershipId: string) =>
      request<void>("DELETE", `${ws(id)}/members/${encodeURIComponent(membershipId)}`),
  };
}

export type Api = ReturnType<typeof createApi>;
