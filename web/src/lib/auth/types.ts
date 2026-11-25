import type { AuthProviderName } from "@/lib/env";

/**
 * What the app needs from an identity provider (ADR-0003, ADR-0004).
 * Authorisation (workspaces, roles) comes from our API, never from here.
 */
export type AuthState =
  | { status: "loading" }
  | { status: "signed-out" }
  | { status: "signed-in"; email: string | null; name: string | null };

export interface AuthClient {
  provider: AuthProviderName;
  state: AuthState;
  /** A bearer token for our API, or null when signed out. */
  getToken(): Promise<string | null>;
  signOut(): Promise<void>;
}
