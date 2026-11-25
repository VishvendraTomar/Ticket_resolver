"use client";

import { useMemo, useSyncExternalStore, type ReactNode } from "react";

import { AuthContext } from "@/lib/auth/context";
import { makeFakeToken, type DevIdentity } from "@/lib/auth/fake-token";
import type { AuthClient } from "@/lib/auth/types";

const STORAGE_KEY = "tr.devIdentity";
const listeners = new Set<() => void>();

function readRaw(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function subscribe(onChange: () => void): () => void {
  listeners.add(onChange);
  window.addEventListener("storage", onChange);
  return () => {
    listeners.delete(onChange);
    window.removeEventListener("storage", onChange);
  };
}

function write(identity: DevIdentity | null): void {
  try {
    if (identity) window.localStorage.setItem(STORAGE_KEY, JSON.stringify(identity));
    else window.localStorage.removeItem(STORAGE_KEY);
  } finally {
    listeners.forEach((l) => l());
  }
}

function parse(raw: string | null): DevIdentity | null {
  if (!raw) return null;
  try {
    const v = JSON.parse(raw) as Partial<DevIdentity>;
    return v.subject && v.email !== undefined
      ? { subject: v.subject, email: v.email, name: v.name ?? "" }
      : null;
  } catch {
    return null;
  }
}

/** Sign in as a dev identity (fake provider only). */
export function signInDev(identity: DevIdentity): void {
  write(identity);
}

export function FakeAuthProvider({ children }: { children: ReactNode }) {
  // undefined on the server and during hydration = still loading.
  const raw = useSyncExternalStore<string | null | undefined>(
    subscribe,
    readRaw,
    () => undefined,
  );

  const client = useMemo<AuthClient>(() => {
    const identity = raw === undefined ? undefined : parse(raw);
    return {
      provider: "fake",
      state:
        identity === undefined
          ? { status: "loading" }
          : identity === null
            ? { status: "signed-out" }
            : { status: "signed-in", email: identity.email, name: identity.name || null },
      getToken: async () => (identity ? makeFakeToken(identity) : null),
      signOut: async () => write(null),
    };
  }, [raw]);

  return <AuthContext.Provider value={client}>{children}</AuthContext.Provider>;
}
