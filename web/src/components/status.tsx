import Link from "next/link";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { ApiError } from "@/lib/api";

export function CenteredPage({ children }: { children: ReactNode }) {
  return <main className="flex flex-1 items-center justify-center p-6">{children}</main>;
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <p role="status" className="text-sm text-muted-foreground">
      {label}
    </p>
  );
}

export function ErrorCard({ error, title }: { error: ApiError; title?: string }) {
  const notFound = error.status === 404;
  return (
    <Card className="w-full max-w-md">
      <CardHeader>
        <CardTitle>{title ?? (notFound ? "Not found" : "Something went wrong")}</CardTitle>
        <CardDescription>
          {notFound
            ? "It doesn't exist, or you're not a member of it."
            : error.message}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Button asChild variant="outline">
          <Link href="/">Back to my workspaces</Link>
        </Button>
      </CardContent>
    </Card>
  );
}
