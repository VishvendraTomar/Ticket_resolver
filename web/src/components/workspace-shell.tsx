"use client";

import { ChevronsUpDown, LogOut, Plus } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { createContext, useContext, type ReactNode } from "react";

import { RequireAuth } from "@/components/require-auth";
import { CenteredPage, ErrorCard, Loading } from "@/components/status";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ApiError, type MyWorkspace } from "@/lib/api";
import { useAuthClient } from "@/lib/auth/context";
import { useMe } from "@/lib/hooks";
import { ROLE_LABELS } from "@/lib/roles";

const WorkspaceContext = createContext<MyWorkspace | null>(null);

/** The workspace the current page acts in, with the caller's role in it. */
export function useWorkspace(): MyWorkspace {
  const ws = useContext(WorkspaceContext);
  if (!ws) throw new Error("useWorkspace must be used inside <WorkspaceShell>");
  return ws;
}

function WorkspaceSwitcher({ current, all }: { current: MyWorkspace; all: MyWorkspace[] }) {
  const router = useRouter();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" className="gap-2" aria-label="Switch workspace">
          <span className="max-w-48 truncate font-medium">{current.name}</span>
          <Badge variant="secondary">{ROLE_LABELS[current.role]}</Badge>
          <ChevronsUpDown className="size-4 opacity-60" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-64">
        <DropdownMenuLabel>Workspaces</DropdownMenuLabel>
        {all.map((ws) => (
          <DropdownMenuItem
            key={ws.id}
            onSelect={() => router.push(`/w/${ws.id}/members`)}
            className="justify-between"
          >
            <span className="truncate">{ws.name}</span>
            {ws.id === current.id && <span className="text-xs text-muted-foreground">current</span>}
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => router.push("/workspaces/new")}>
          <Plus className="size-4" /> New workspace
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function UserMenu() {
  const auth = useAuthClient();
  const me = useMe();
  const label = me.data?.user.name || me.data?.user.email || "Account";
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" className="max-w-56 truncate">
          {label}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {me.data?.user.email && <DropdownMenuLabel>{me.data.user.email}</DropdownMenuLabel>}
        <DropdownMenuItem onSelect={() => void auth.signOut()}>
          <LogOut className="size-4" /> Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function Shell({ children }: { children: ReactNode }) {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const me = useMe();

  if (me.error) {
    return (
      <CenteredPage>
        <ErrorCard error={me.error} />
      </CenteredPage>
    );
  }
  const current = me.data?.workspaces.find((w) => w.id === workspaceId);
  if (!current) {
    // A workspace created a moment ago appears once /v1/me reloads.
    return (
      <CenteredPage>
        {!me.data || me.loading ? (
          <Loading />
        ) : (
          <ErrorCard error={new ApiError(404, "not_found", "Workspace not found")} />
        )}
      </CenteredPage>
    );
  }

  return (
    <WorkspaceContext.Provider value={current}>
      <header className="flex items-center justify-between gap-4 border-b px-4 py-2">
        <div className="flex items-center gap-2">
          <Link href="/" className="font-semibold tracking-tight">
            Ticket Resolver
          </Link>
          <span className="text-muted-foreground">/</span>
          <WorkspaceSwitcher current={current} all={me.data?.workspaces ?? []} />
        </div>
        <nav className="flex items-center gap-1">
          <Button asChild variant="ghost" size="sm">
            <Link href={`/w/${current.id}/members`}>Members</Link>
          </Button>
          <UserMenu />
        </nav>
      </header>
      <main className="mx-auto w-full max-w-5xl flex-1 p-6">{children}</main>
    </WorkspaceContext.Provider>
  );
}

export function WorkspaceShell({ children }: { children: ReactNode }) {
  return (
    <RequireAuth>
      <Shell>{children}</Shell>
    </RequireAuth>
  );
}
