"use client";

import { useAuthClient } from "@/lib/auth/context";

export function DevAuthBanner() {
  const auth = useAuthClient();
  if (auth.provider !== "fake") return null;
  return (
    <div className="bg-amber-100 px-4 py-1.5 text-center text-xs text-amber-900 dark:bg-amber-950 dark:text-amber-200">
      Development sign-in (fake auth). Works only against an API with AUTH_PROVIDER=fake. Set
      NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY to use Clerk.
    </div>
  );
}
