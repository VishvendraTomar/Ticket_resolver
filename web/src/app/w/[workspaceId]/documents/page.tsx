"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { IN_PROGRESS, PipelineBadge, VersionStatusBadge } from "@/components/knowledge";
import { ErrorCard, Loading } from "@/components/status";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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

const ACCEPT = ".pdf,.docx,.html,.htm,.md,.markdown";

function UploadForm() {
  const api = useApi();
  const workspace = useWorkspace();
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [language, setLanguage] = useState("en");
  const [busy, setBusy] = useState(false);
  const [fileInputKey, setFileInputKey] = useState(0);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    try {
      const doc = await api.uploadDocument(workspace.id, file, title.trim(), language.trim());
      toast.success("Uploaded. Parsing has started.");
      // Reset first: with cacheComponents this page stays mounted (hidden) after navigating.
      setFile(null);
      setTitle("");
      setFileInputKey((k) => k + 1);
      router.push(`/w/${workspace.id}/versions/${doc.versions[0].id}`);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-wrap items-end gap-3">
      <div className="flex min-w-64 flex-1 flex-col gap-1.5">
        <Label htmlFor="doc-file">File (PDF, DOCX, HTML or Markdown)</Label>
        <Input
          key={fileInputKey}
          id="doc-file"
          type="file"
          accept={ACCEPT}
          required
          onChange={(e) => {
            const f = e.target.files?.[0] ?? null;
            setFile(f);
            if (f && !title) setTitle(f.name.replace(/\.[^.]+$/, "").replace(/[-_]+/g, " "));
          }}
        />
      </div>
      <div className="flex min-w-64 flex-1 flex-col gap-1.5">
        <Label htmlFor="doc-title">Title</Label>
        <Input
          id="doc-title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Northwind Leave Policy — Germany"
          maxLength={300}
          required
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="doc-lang">Language</Label>
        <Input
          id="doc-lang"
          value={language}
          onChange={(e) => setLanguage(e.target.value)}
          className="w-24"
          maxLength={16}
          required
        />
      </div>
      <Button type="submit" disabled={busy || !file || !title.trim()}>
        {busy ? "Uploading…" : "Upload"}
      </Button>
    </form>
  );
}

export default function DocumentsPage() {
  const api = useApi();
  const workspace = useWorkspace();
  const docs = useQuery(`documents:${workspace.id}`, () => api.documents(workspace.id));
  const busy = docs.data?.some(
    (d) => d.latest_version && IN_PROGRESS.includes(d.latest_version.pipeline_status),
  );
  usePolling(Boolean(busy), docs.reload);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Documents</h1>
        <p className="text-sm text-muted-foreground">
          Policies are parsed, tagged by jurisdiction, reviewed by a person, then published.
          Only published versions are ever used to answer tickets.
        </p>
      </div>

      {canEditKnowledge(workspace.role) && (
        <Card>
          <CardHeader>
            <CardTitle>Upload a policy</CardTitle>
            <CardDescription>
              You&apos;ll review its sections and confirm where it applies before publishing.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <UploadForm />
          </CardContent>
        </Card>
      )}

      {docs.error ? (
        <ErrorCard error={docs.error} />
      ) : !docs.data ? (
        <Loading />
      ) : docs.data.length === 0 ? (
        <p className="text-sm text-muted-foreground">No documents yet.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Document</TableHead>
                <TableHead>Latest version</TableHead>
                <TableHead>Processing</TableHead>
                <TableHead>Jurisdiction</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {docs.data.map((d) => (
                <TableRow key={d.id}>
                  <TableCell>
                    <Link
                      href={`/w/${workspace.id}/documents/${d.id}`}
                      className="font-medium underline-offset-4 hover:underline"
                    >
                      {d.title}
                    </Link>
                    <div className="text-xs text-muted-foreground">
                      {d.version_count} version{d.version_count === 1 ? "" : "s"} · {d.language}
                    </div>
                  </TableCell>
                  <TableCell>
                    {d.latest_version && (
                      <span className="flex items-center gap-2">
                        v{d.latest_version.version_number}
                        <VersionStatusBadge status={d.latest_version.status} />
                      </span>
                    )}
                  </TableCell>
                  <TableCell>
                    {d.latest_version && (
                      <Link href={`/w/${workspace.id}/versions/${d.latest_version.id}`}>
                        <PipelineBadge status={d.latest_version.pipeline_status} />
                      </Link>
                    )}
                  </TableCell>
                  <TableCell className="text-sm">
                    {d.latest_version?.jurisdiction_code ?? "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
