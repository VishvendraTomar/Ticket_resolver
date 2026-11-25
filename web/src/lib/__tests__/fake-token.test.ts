import { describe, expect, it } from "vitest";

import { devIdentityFor, makeFakeToken } from "@/lib/auth/fake-token";

describe("fake tokens (must match backend/app/providers/auth/fake.py)", () => {
  it("uses the backend's fake|subject|email|name format", () => {
    expect(makeFakeToken({ subject: "dev_a", email: "a@x.com", name: "A" })).toBe(
      "fake|dev_a|a@x.com|A",
    );
  });

  it("rejects '|' and an empty subject", () => {
    expect(() => makeFakeToken({ subject: "a|b", email: "", name: "" })).toThrow();
    expect(() => makeFakeToken({ subject: "", email: "", name: "" })).toThrow();
  });

  it("maps the same email to the same subject, case-insensitively", () => {
    const a = devIdentityFor(" Alice@Example.com ", "Alice");
    const b = devIdentityFor("alice@example.com", "");
    expect(a.subject).toBe(b.subject);
    expect(a.email).toBe("alice@example.com");
  });

  it("strips '|' from names and rejects invalid emails", () => {
    expect(devIdentityFor("a@x.com", "A|B").name).toBe("AB");
    expect(() => devIdentityFor("not-an-email", "")).toThrow();
    expect(() => devIdentityFor("a|b@x.com", "")).toThrow();
  });
});
