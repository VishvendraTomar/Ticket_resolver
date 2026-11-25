"use client";

import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { CenteredPage, Loading } from "@/components/status";
import { useAuthClient } from "@/lib/auth/context";

/** Client-side gate: the API is the real guard (every call needs a valid token). */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { state } = useAuthClient();
  const router = useRouter();

  useEffect(() => {
    if (state.status === "signed-out") router.replace("/sign-in");
  }, [state.status, router]);

  if (state.status !== "signed-in") {
    return (
      <CenteredPage>
        <Loading />
      </CenteredPage>
    );
  }
  return children;
}
