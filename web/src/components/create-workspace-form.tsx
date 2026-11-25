"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api";
import { useApi, useMe } from "@/lib/hooks";

export function CreateWorkspaceForm() {
  const api = useApi();
  const me = useMe();
  const router = useRouter();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const ws = await api.createWorkspace(name.trim());
      me.reload();
      setName(""); // this page may stay mounted (hidden) after navigating
      router.push(`/w/${ws.id}/documents`);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Couldn't create the workspace");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-3">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="workspace-name">Workspace name</Label>
        <Input
          id="workspace-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Northwind Global"
          maxLength={200}
          required
          autoFocus
        />
      </div>
      <Button type="submit" disabled={busy || !name.trim()}>
        {busy ? "Creating…" : "Create workspace"}
      </Button>
    </form>
  );
}
