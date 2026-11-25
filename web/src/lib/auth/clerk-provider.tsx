"use client";

import { useAuth, useClerk, useUser } from "@clerk/nextjs";
import { useMemo, type ReactNode } from "react";

import { AuthContext } from "@/lib/auth/context";
import type { AuthClient } from "@/lib/auth/types";

/**
 * Adapts Clerk's hooks to our AuthClient. Must sit inside <ClerkProvider>
 * (rendered by the root layout only when a publishable key is configured).
 * The API verifies the session token itself (ADR-0003).
 */
export function ClerkAuthBridge({ children }: { children: ReactNode }) {
  const { isLoaded, isSignedIn, getToken } = useAuth();
  const { user } = useUser();
  const clerk = useClerk();

  const email = user?.primaryEmailAddress?.emailAddress ?? null;
  const name = user?.fullName ?? null;

  const client = useMemo<AuthClient>(
    () => ({
      provider: "clerk",
      state: !isLoaded
        ? { status: "loading" }
        : isSignedIn
          ? { status: "signed-in", email, name }
          : { status: "signed-out" },
      getToken: () => getToken(),
      signOut: () => clerk.signOut({ redirectUrl: "/sign-in" }),
    }),
    [isLoaded, isSignedIn, email, name, getToken, clerk],
  );

  return <AuthContext.Provider value={client}>{children}</AuthContext.Provider>;
}
