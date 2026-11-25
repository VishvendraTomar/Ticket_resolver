"use client";

import Link from "next/link";

import { CreateWorkspaceForm } from "@/components/create-workspace-form";
import { RequireAuth } from "@/components/require-auth";
import { CenteredPage } from "@/components/status";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export default function NewWorkspacePage() {
  return (
    <RequireAuth>
      <CenteredPage>
        <Card className="w-full max-w-md">
          <CardHeader>
            <CardTitle>New workspace</CardTitle>
            <CardDescription>
              You&apos;ll be its owner. <Link href="/" className="underline">Cancel</Link>
            </CardDescription>
          </CardHeader>
          <CardContent>
            <CreateWorkspaceForm />
          </CardContent>
        </Card>
      </CenteredPage>
    </RequireAuth>
  );
}
