"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { ErrorCard, Loading } from "@/components/status";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useWorkspace } from "@/components/workspace-shell";
import { ApiError, type MemberOut } from "@/lib/api";
import { useApi, useMe, useQuery } from "@/lib/hooks";
import {
  assignableRoles,
  canEditMember,
  canManageMembers,
  ROLE_LABELS,
  type Role,
} from "@/lib/roles";

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

function RoleSelect({
  value,
  options,
  onChange,
  disabled,
  label,
}: {
  value: Role;
  options: Role[];
  onChange: (role: Role) => void;
  disabled?: boolean;
  label: string;
}) {
  return (
    <Select value={value} onValueChange={(v) => onChange(v as Role)} disabled={disabled}>
      <SelectTrigger className="w-40" aria-label={label}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {options.map((r) => (
          <SelectItem key={r} value={r}>
            {ROLE_LABELS[r]}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function AddMemberForm({ onAdded }: { onAdded: () => void }) {
  const api = useApi();
  const workspace = useWorkspace();
  const roles = assignableRoles(workspace.role);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>(roles.includes("agent") ? "agent" : roles[0]);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await api.addMember(workspace.id, email.trim(), role);
      toast.success(`Added ${email.trim()}`);
      setEmail("");
      onAdded();
    } catch (err) {
      toast.error(errorMessage(err, "Couldn't add the member"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-wrap items-end gap-3">
      <div className="flex min-w-64 flex-1 flex-col gap-1.5">
        <Label htmlFor="member-email">Email</Label>
        <Input
          id="member-email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="colleague@company.com"
          required
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label>Role</Label>
        <RoleSelect value={role} options={roles} onChange={setRole} label="Role for new member" />
      </div>
      <Button type="submit" disabled={busy || !email.trim()}>
        {busy ? "Adding…" : "Add member"}
      </Button>
    </form>
  );
}

function MemberRow({
  member,
  isMe,
  onChanged,
}: {
  member: MemberOut;
  isMe: boolean;
  onChanged: (opts?: { leftWorkspace?: boolean }) => void;
}) {
  const api = useApi();
  const workspace = useWorkspace();
  const editable = canEditMember(workspace.role, member.role);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);

  async function changeRole(role: Role) {
    if (role === member.role) return;
    setBusy(true);
    try {
      await api.changeRole(workspace.id, member.id, role);
      toast.success(`Role changed to ${ROLE_LABELS[role]}`);
      onChanged();
    } catch (err) {
      toast.error(errorMessage(err, "Couldn't change the role"));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    try {
      await api.removeMember(workspace.id, member.id);
      toast.success(isMe ? "You left the workspace" : "Member removed");
      onChanged({ leftWorkspace: isMe });
    } catch (err) {
      toast.error(errorMessage(err, "Couldn't remove the member"));
      setBusy(false);
      setConfirming(false);
    }
  }

  const who = member.user.name || member.user.email || "Unknown user";
  const [codes, setCodes] = useState((member.jurisdiction_codes ?? []).join(", "));

  async function saveJurisdictions() {
    const list = codes
      .split(",")
      .map((c) => c.trim().toUpperCase())
      .filter(Boolean);
    setBusy(true);
    try {
      await api.setMemberJurisdictions(workspace.id, member.id, list.length ? list : null);
      toast.success(list.length ? `Limited to ${list.join(", ")}` : "No jurisdiction limits");
      onChanged();
    } catch (err) {
      toast.error(errorMessage(err, "Couldn't save the jurisdictions"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <TableRow>
      <TableCell>
        <div className="font-medium">
          {who} {isMe && <span className="text-muted-foreground">(you)</span>}
        </div>
        {member.user.name && member.user.email && (
          <div className="text-xs text-muted-foreground">{member.user.email}</div>
        )}
        {member.role === "policy_editor" &&
          (editable ? (
            <div className="mt-1 flex items-center gap-1">
              <Input
                aria-label={`Jurisdictions ${who} may edit`}
                className="h-7 w-44 text-xs"
                placeholder="All jurisdictions (e.g. DE, FR)"
                value={codes}
                onChange={(e) => setCodes(e.target.value)}
              />
              <Button size="xs" variant="outline" onClick={saveJurisdictions} disabled={busy}>
                Save
              </Button>
            </div>
          ) : (
            member.jurisdiction_codes && (
              <div className="text-xs text-muted-foreground">
                Only {member.jurisdiction_codes.join(", ")}
              </div>
            )
          ))}
      </TableCell>
      <TableCell>
        {editable ? (
          <RoleSelect
            value={member.role}
            options={assignableRoles(workspace.role)}
            onChange={changeRole}
            disabled={busy}
            label={`Role for ${who}`}
          />
        ) : (
          <Badge variant="secondary">{ROLE_LABELS[member.role]}</Badge>
        )}
      </TableCell>
      <TableCell className="text-sm text-muted-foreground">
        {new Date(member.created_at).toLocaleDateString()}
      </TableCell>
      <TableCell className="text-right">
        {editable &&
          (confirming ? (
            <div className="flex justify-end gap-2">
              <Button size="sm" variant="destructive" onClick={remove} disabled={busy}>
                {isMe ? "Leave" : "Remove"}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setConfirming(false)} disabled={busy}>
                Cancel
              </Button>
            </div>
          ) : (
            <Button size="sm" variant="outline" onClick={() => setConfirming(true)} disabled={busy}>
              {isMe ? "Leave" : "Remove"}
            </Button>
          ))}
      </TableCell>
    </TableRow>
  );
}

export default function MembersPage() {
  const api = useApi();
  const me = useMe();
  const router = useRouter();
  const workspace = useWorkspace();
  const members = useQuery(`members:${workspace.id}`, () => api.listMembers(workspace.id));
  const manager = canManageMembers(workspace.role);

  function onChanged(opts?: { leftWorkspace?: boolean }) {
    me.reload(); // our own role may have changed
    if (opts?.leftWorkspace) router.replace("/");
    else members.reload();
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Members</h1>
        <p className="text-sm text-muted-foreground">
          People who can work in {workspace.name}.{" "}
          {manager ? "Owners and admins manage members." : "Only owners and admins can make changes."}
        </p>
      </div>

      {manager && (
        <Card>
          <CardHeader>
            <CardTitle>Add a member</CardTitle>
            <CardDescription>They need to have signed in once.</CardDescription>
          </CardHeader>
          <CardContent>
            <AddMemberForm onAdded={members.reload} />
          </CardContent>
        </Card>
      )}

      {members.error ? (
        <ErrorCard error={members.error} />
      ) : !members.data ? (
        <Loading />
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Member</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Added</TableHead>
                <TableHead className="text-right">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {members.data.map((m) => (
                <MemberRow
                  key={m.id}
                  member={m}
                  isMe={m.user.id === me.data?.user.id}
                  onChanged={onChanged}
                />
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
