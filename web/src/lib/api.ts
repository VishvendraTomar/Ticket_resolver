/** Typed client for the FastAPI backend (/v1). Shapes mirror backend/app/tenancy/schemas.py. */

import type { Role } from "@/lib/roles";

export type UserOut = { id: string; email: string | null; name: string | null };
export type MyWorkspace = { id: string; name: string; role: Role };
export type MeOut = { user: UserOut; workspaces: MyWorkspace[] };
export type WorkspaceOut = { id: string; name: string; created_at: string };
export type MemberOut = {
  id: string;
  user: UserOut;
  role: Role;
  jurisdiction_codes: string[] | null;
  created_at: string;
};

// --- Knowledge base (M2) ---
export type Jurisdiction = {
  code: string;
  parent_code: string | null;
  level: "global" | "region" | "country" | "state";
  name: string;
};
export type Topic = { id: string; key: string; name: string; description: string | null };
export type ScopeField = { id: string; key: string; name: string; allowed_values: string[] };
export type PipelineStatus =
  | "queued"
  | "parsing"
  | "tagging"
  | "awaiting_review"
  | "embedding"
  | "ready"
  | "failed";
export type VersionStatus = "draft" | "published" | "retired";
export type VersionSummary = {
  id: string;
  document_id: string;
  version_number: number;
  status: VersionStatus;
  pipeline_status: PipelineStatus;
  pipeline_error: string | null;
  needs_review: boolean;
  file_name: string;
  mime_type: string;
  size_bytes: number;
  jurisdiction_code: string | null;
  scope: Record<string, string>;
  topic_id: string | null;
  effective_from: string | null;
  effective_to: string | null;
  tags_confirmed_at: string | null;
  created_at: string;
  published_at: string | null;
};
export type TagValues = {
  jurisdiction?: string;
  topic?: string;
  topic_id?: string;
  scope?: Record<string, string>;
};
export type ParseReport = {
  parser?: string;
  page_count?: number | null;
  sections?: number;
  chunks?: number;
  tables?: number;
  headings?: number;
  warnings?: string[];
  needs_review?: boolean;
  ocr?: { pages_ocrd: number; min_confidence: number | null; low_confidence_pages: number[]; threshold: number };
  embedding?: { model: string; embedded: number; reused: number };
};
export type VersionDetail = VersionSummary & {
  parse_report: ParseReport;
  tag_suggestions: {
    status?: string;
    version?: TagValues;
    sections?: Record<string, TagValues>;
    discarded?: string[];
    notes?: string[];
    models?: string[];
  };
  relations: { to_version_id: string; kind: string }[];
};
export type DocumentOut = {
  id: string;
  title: string;
  source: string | null;
  language: string;
  created_at: string;
  version_count: number;
  latest_version: VersionSummary | null;
};
export type DocumentDetail = Omit<DocumentOut, "version_count" | "latest_version"> & {
  versions: VersionSummary[];
};
export type SectionOut = {
  id: string;
  ordinal: number;
  heading_path: string[];
  clause_number: string | null;
  title: string | null;
  text: string;
  token_count: number;
  has_table: boolean;
  page_start: number | null;
  jurisdiction_code: string | null;
  scope: Record<string, string> | null;
  topic_id: string | null;
  chunk_count: number;
  refs: { target_text: string; to_section_id: string | null }[];
};
export type SectionTag = {
  section_id: string;
  jurisdiction_code?: string | null;
  scope?: Record<string, string> | null;
  topic_id?: string | null;
};
export type TagConfirm = {
  jurisdiction_code: string;
  scope: Record<string, string>;
  topic_id: string | null;
  effective_from: string;
  effective_to: string | null;
  sections: SectionTag[];
};
export type ConflictCandidate = {
  section: string;
  jurisdiction: string;
  other_document: string;
  other_section: string;
  other_jurisdiction: string;
  other_version_id: string;
};
export type Coverage = {
  jurisdictions: Jurisdiction[];
  topics: Topic[];
  cells: { jurisdiction_code: string; topic_id: string | null; sections: number; documents: number }[];
};

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details?: Record<string, unknown>,
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
    const err = b.error as { code?: unknown; message?: unknown; details?: unknown } | undefined;
    if (err && typeof err.message === "string") {
      const details =
        err.details && typeof err.details === "object"
          ? (err.details as Record<string, unknown>)
          : undefined;
      return new ApiError(
        status,
        typeof err.code === "string" ? err.code : "error",
        err.message,
        details,
      );
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
      const isForm = body instanceof FormData;
      response = await doFetch(`${baseUrl}${path}`, {
        method,
        headers: {
          Authorization: `Bearer ${token}`,
          // FormData sets its own multipart boundary header.
          ...(body === undefined || isForm ? {} : { "Content-Type": "application/json" }),
        },
        body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
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
    setMemberJurisdictions: (id: string, membershipId: string, codes: string[] | null) =>
      request<MemberOut>("PATCH", `${ws(id)}/members/${encodeURIComponent(membershipId)}`, {
        jurisdiction_codes: codes,
      }),

    jurisdictions: (id: string) => request<Jurisdiction[]>("GET", `${ws(id)}/jurisdictions`),
    topics: (id: string) => request<Topic[]>("GET", `${ws(id)}/topics`),
    scopeFields: (id: string) => request<ScopeField[]>("GET", `${ws(id)}/scope-fields`),
    documents: (id: string) => request<DocumentOut[]>("GET", `${ws(id)}/documents`),
    document: (id: string, documentId: string) =>
      request<DocumentDetail>("GET", `${ws(id)}/documents/${encodeURIComponent(documentId)}`),
    uploadDocument: (id: string, file: File, title: string, language: string) => {
      const form = new FormData();
      form.set("file", file);
      form.set("title", title);
      form.set("language", language);
      return request<DocumentDetail>("POST", `${ws(id)}/documents`, form);
    },
    uploadVersion: (id: string, documentId: string, file: File) => {
      const form = new FormData();
      form.set("file", file);
      return request<VersionSummary>(
        "POST",
        `${ws(id)}/documents/${encodeURIComponent(documentId)}/versions`,
        form,
      );
    },
    version: (id: string, versionId: string) =>
      request<VersionDetail>("GET", `${ws(id)}/versions/${encodeURIComponent(versionId)}`),
    sections: (id: string, versionId: string) =>
      request<SectionOut[]>("GET", `${ws(id)}/versions/${encodeURIComponent(versionId)}/sections`),
    confirmTags: (id: string, versionId: string, body: TagConfirm) =>
      request<VersionDetail>("PUT", `${ws(id)}/versions/${encodeURIComponent(versionId)}/tags`, body),
    publish: (id: string, versionId: string, acknowledgeConflicts: boolean) =>
      request<VersionDetail>(
        "POST",
        `${ws(id)}/versions/${encodeURIComponent(versionId)}/publish`,
        { acknowledge_conflicts: acknowledgeConflicts },
      ),
    retire: (id: string, versionId: string) =>
      request<VersionDetail>("POST", `${ws(id)}/versions/${encodeURIComponent(versionId)}/retire`),
    retry: (id: string, versionId: string) =>
      request<VersionDetail>("POST", `${ws(id)}/versions/${encodeURIComponent(versionId)}/retry`),
    coverage: (id: string) => request<Coverage>("GET", `${ws(id)}/coverage`),
  };
}

export type Api = ReturnType<typeof createApi>;
