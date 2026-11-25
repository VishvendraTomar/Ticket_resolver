"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { CreateWorkspaceForm } from "@/components/create-workspace-form";
import { RequireAuth } from "@/components/require-auth";
import { CenteredPage, ErrorCard, Loading } from "@/components/status";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useMe } from "@/lib/hooks";

function Home() {
  const me = useMe();
  const router = useRouter();
  const first = me.data?.workspaces[0];

  useEffect(() => {
    if (first) router.replace(`/w/${first.id}/documents`);
  }, [first, router]);

  if (me.error) return <ErrorCard error={me.error} />;
  if (!me.data || first) return <Loading />;

  return (
    <Card className="w-full max-w-md">
      <CardHeader>
        <CardTitle>Create your first workspace</CardTitle>
        <CardDescription>
          A workspace holds one company&apos;s policies, tickets and team.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <CreateWorkspaceForm />
      </CardContent>
    </Card>
  );
}

export default function HomePage() {
  return (
    <RequireAuth>
      <CenteredPage>
        <Home />
      </CenteredPage>
    </RequireAuth>
  );
}
