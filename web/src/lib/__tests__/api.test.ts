import { describe, expect, it, vi } from "vitest";

import { ApiError, createApi, toApiError } from "@/lib/api";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("toApiError", () => {
  it("reads domain errors", () => {
    const e = toApiError(409, { error: { code: "conflict", message: "Nope" } });
    expect([e.status, e.code, e.message]).toEqual([409, "conflict", "Nope"]);
  });

  it("reads FastAPI validation errors", () => {
    expect(toApiError(422, { detail: [{ msg: "bad email" }] }).message).toBe("bad email");
  });

  it("falls back for unknown bodies", () => {
    expect(toApiError(500, null).message).toBe("Request failed (500)");
  });
});

describe("createApi", () => {
  it("sends the bearer token and JSON body", async () => {
    const fetchImpl = vi.fn(async () => jsonResponse(201, { id: "w1", name: "A", created_at: "" }));
    const api = createApi({ baseUrl: "http://api", getToken: async () => "t0k", fetchImpl });
    await api.createWorkspace("A");
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://api/v1/workspaces");
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer t0k");
    expect(init.body).toBe(JSON.stringify({ name: "A" }));
  });

  it("calls onUnauthorized on 401 and throws ApiError", async () => {
    const onUnauthorized = vi.fn();
    const api = createApi({
      baseUrl: "http://api",
      getToken: async () => "t",
      onUnauthorized,
      fetchImpl: async () => jsonResponse(401, { error: { code: "unauthenticated", message: "x" } }),
    });
    await expect(api.me()).rejects.toBeInstanceOf(ApiError);
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });

  it("doesn't call the API without a token", async () => {
    const fetchImpl = vi.fn();
    const api = createApi({ baseUrl: "http://api", getToken: async () => null, fetchImpl });
    await expect(api.me()).rejects.toMatchObject({ status: 401 });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("returns undefined for 204 and reports network failures", async () => {
    const ok = createApi({
      baseUrl: "http://api",
      getToken: async () => "t",
      fetchImpl: async () => new Response(null, { status: 204 }),
    });
    await expect(ok.removeMember("w", "m")).resolves.toBeUndefined();

    const down = createApi({
      baseUrl: "http://api",
      getToken: async () => "t",
      fetchImpl: async () => {
        throw new TypeError("fetch failed");
      },
    });
    await expect(down.me()).rejects.toMatchObject({ status: 0, code: "network" });
  });
});
