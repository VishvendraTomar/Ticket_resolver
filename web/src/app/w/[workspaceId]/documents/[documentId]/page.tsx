"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import {
  formatBytes,
  IN_PROGRESS,
  PipelineBadge,
  VersionStatusBadge,
} from "@/components/knowledge";
import { ErrorCard, Loading } from "@/components/status";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useWorkspace } from "@/components/workspace-shell";
import { ApiError } from "@/lib/api";
import { useApi, useQuery } from "@/lib/hooks";
import { canEditKnowledge } from "@/lib/roles";
import { usePolling } from "@/lib/use-polling";

function NewVersionForm({ documentId }: { documentId: string }) {
  const api = useApi();
  const workspace = useWorkspace();
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [fileInputKey, setFileInputKey] = useState(0);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    try {
      const v = await api.uploadVersion(workspace.id, documentId, file);
      setFile(null);
      setFileInputKey((k) => k + 1);
      router.push(`/w/${workspace.id}/versions/${v.id}`);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-wrap items-end gap-3">
      <div className="flex min-w-64 flex-col gap-1.5">
        <Label htmlFor="version-file">Upload a new version</Label>
        <Input
          key={fileInputKey}
          id="version-file"
          type="file"
          accept=".pdf,.docx,.html,.htm,.md,.markdown"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
      </div>
      <Button type="submit" variant="outline" disabled={busy || !file}>
        {busy ? "Uploading…" : "Upload version"}
      </Button>
    </form>
  );
}

export default function DocumentPage() {
  const { documentId } = useParams<{ documentId: string }>();
  const api = useApi();
  const workspace = useWorkspace();
  const doc = useQuery(`document:${documentId}`, () => api.document(workspace.id, documentId));
  usePolling(
    Boolean(doc.data?.versions.some((v) => IN_PROGRESS.includes(v.pipeline_status))),
    doc.reload,
  );

  if (doc.error) return <ErrorCard error={doc.error} />;
  if (!doc.data) return <Loading />;
  const d = doc.data;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <Link href={`/w/${workspace.id}/documents`} className="text-sm text-muted-foreground">
          ← Documents
        </Link>
        <h1 className="text-2xl font-semibold tracking-tight">{d.title}</h1>
        <p className="text-sm text-muted-foreground">
          Language: {d.language}
          {d.source ? ` · Source: ${d.source}` : ""}
        </p>
      </div>

      {canEditKnowledge(workspace.role) && <NewVersionForm documentId={d.id} />}

      <div className="overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Version</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Processing</TableHead>
              <TableHead>Applies to</TableHead>
              <TableHead>Valid</TableHead>
              <TableHead>File</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {d.versions.map((v) => (
              <TableRow key={v.id}>
                <TableCell>
                  <Link
                    href={`/w/${workspace.id}/versions/${v.id}`}
                    className="font-medium underline-offset-4 hover:underline"
                  >
                    v{v.version_number}
                  </Link>
                </TableCell>
                <TableCell>
                  <VersionStatusBadge status={v.status} />
                </TableCell>
                <TableCell>
                  <PipelineBadge status={v.pipeline_status} />
                </TableCell>
                <TableCell className="text-sm">{v.jurisdiction_code ?? "—"}</TableCell>
                <TableCell className="text-sm">
                  {v.effective_from ? `${v.effective_from} → ${v.effective_to ?? "open"}` : "—"}
                </TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {v.file_name} · {formatBytes(v.size_bytes)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
