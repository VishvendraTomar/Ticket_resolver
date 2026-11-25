"use client";

import { createContext, useContext } from "react";

import type { AuthClient } from "@/lib/auth/types";

export const AuthContext = createContext<AuthClient | null>(null);

export function useAuthClient(): AuthClient {
  const client = useContext(AuthContext);
  if (!client) throw new Error("useAuthClient must be used inside <AppAuthProvider>");
  return client;
}
