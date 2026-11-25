"use client";

import type { ReactNode } from "react";

import { ClerkAuthBridge } from "@/lib/auth/clerk-provider";
import { FakeAuthProvider } from "@/lib/auth/fake-provider";
import { authProvider } from "@/lib/env";

export function AppAuthProvider({ children }: { children: ReactNode }) {
  return authProvider === "clerk" ? (
    <ClerkAuthBridge>{children}</ClerkAuthBridge>
  ) : (
    <FakeAuthProvider>{children}</FakeAuthProvider>
  );
}
