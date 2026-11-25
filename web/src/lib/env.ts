/**
 * Public (browser-visible) configuration. Only NEXT_PUBLIC_* values belong
 * here; Next.js inlines them at build time, so each one must be referenced
 * literally. They are read from the repo-root .env (see next.config.ts).
 */

export type AuthProviderName = "clerk" | "fake";

const clerkPublishableKey = process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY ?? "";
const explicitProvider = process.env.NEXT_PUBLIC_AUTH_PROVIDER ?? "";

/**
 * Clerk when a publishable key is configured, otherwise the fake provider.
 * NEXT_PUBLIC_AUTH_PROVIDER overrides the guess. The fake only works against
 * an API running with AUTH_PROVIDER=fake, which the backend refuses outside
 * ENVIRONMENT=local/test, so a misconfigured deploy fails closed.
 */
export const authProvider: AuthProviderName =
  explicitProvider === "clerk" || explicitProvider === "fake"
    ? explicitProvider
    : clerkPublishableKey
      ? "clerk"
      : "fake";

if (authProvider === "clerk" && !clerkPublishableKey) {
  throw new Error(
    "NEXT_PUBLIC_AUTH_PROVIDER=clerk needs NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY",
  );
}

export { clerkPublishableKey };

export const apiUrl = (
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
).replace(/\/+$/, "");
