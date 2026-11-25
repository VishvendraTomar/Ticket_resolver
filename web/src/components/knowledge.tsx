"use client";

import { useId } from "react";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import type {
  Jurisdiction,
  PipelineStatus,
  ScopeField,
  Topic,
  VersionStatus,
} from "@/lib/api";
import { useApi, useQuery } from "@/lib/hooks";

const PIPELINE_LABELS: Record<PipelineStatus, string> = {
  queued: "Queued",
  parsing: "Parsing",
  tagging: "Suggesting tags",
  awaiting_review: "Needs review",
  embedding: "Indexing",
  ready: "Ready to publish",
  failed: "Failed",
};

export const IN_PROGRESS: PipelineStatus[] = ["queued", "parsing", "tagging", "embedding"];

export function PipelineBadge({ status }: { status: PipelineStatus }) {
  const variant =
    status === "failed" ? "destructive" : status === "awaiting_review" ? "default" : "secondary";
  return <Badge variant={variant}>{PIPELINE_LABELS[status]}</Badge>;
}

export function VersionStatusBadge({ status }: { status: VersionStatus }) {
  const variant = status === "published" ? "default" : "outline";
  return <Badge variant={variant}>{status[0].toUpperCase() + status.slice(1)}</Badge>;
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function jurisdictionLabel(code: string | null, all: Jurisdiction[] | undefined): string {
  if (!code) return "—";
  const j = all?.find((x) => x.code === code);
  return j ? `${j.name} (${j.code})` : code;
}

/** Workspace reference data used by the tagging form and coverage map. */
export function useReference(workspaceId: string) {
  const api = useApi();
  const jurisdictions = useQuery<Jurisdiction[]>(`jurisdictions:${workspaceId}`, () =>
    api.jurisdictions(workspaceId),
  );
  const topics = useQuery<Topic[]>(`topics:${workspaceId}`, () => api.topics(workspaceId));
  const scopeFields = useQuery<ScopeField[]>(`scope-fields:${workspaceId}`, () =>
    api.scopeFields(workspaceId),
  );
  return { jurisdictions, topics, scopeFields };
}

/** A searchable jurisdiction picker: type a code or a name (318 entries). */
export function JurisdictionField({
  value,
  onChange,
  jurisdictions,
  placeholder = "e.g. DE or Germany",
  label,
  id,
}: {
  value: string;
  onChange: (code: string) => void;
  jurisdictions: Jurisdiction[];
  placeholder?: string;
  label: string;
  id?: string;
}) {
  const listId = useId();
  return (
    <>
      <Input
        id={id}
        aria-label={label}
        list={listId}
        value={value}
        placeholder={placeholder}
        onChange={(e) => {
          const raw = e.target.value;
          // Accept "DE", "de", or a picked "DE — Germany" option.
          const code = raw.split(" — ")[0].trim().toUpperCase();
          onChange(jurisdictions.some((j) => j.code === code) ? code : raw);
        }}
        className="w-48"
      />
      <datalist id={listId}>
        {jurisdictions.map((j) => (
          <option key={j.code} value={j.code}>
            {j.name}
          </option>
        ))}
      </datalist>
    </>
  );
}
