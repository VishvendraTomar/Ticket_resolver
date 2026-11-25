"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import {
  IN_PROGRESS,
  JurisdictionField,
  jurisdictionLabel,
  PipelineBadge,
  useReference,
  VersionStatusBadge,
} from "@/components/knowledge";
import { ErrorCard, Loading } from "@/components/status";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
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
import { useWorkspace } from "@/components/workspace-shell";
import {
  ApiError,
  type ConflictCandidate,
  type Jurisdiction,
  type ScopeField,
  type SectionOut,
  type Topic,
  type VersionDetail,
} from "@/lib/api";
import { useApi, useQuery } from "@/lib/hooks";
import { canEditKnowledge } from "@/lib/roles";
import { usePolling } from "@/lib/use-polling";

const NONE = "__none";
const ANY = "*";

function errorText(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

function TopicSelect({
  value,
  onChange,
  topics,
  label,
  noneLabel,
}: {
  value: string;
  onChange: (v: string) => void;
  topics: Topic[];
  label: string;
  noneLabel: string;
}) {
  return (
    <Select value={value || NONE} onValueChange={(v) => onChange(v === NONE ? "" : v)}>
      <SelectTrigger className="w-52" aria-label={label}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={NONE}>{noneLabel}</SelectItem>
        {topics.map((t) => (
          <SelectItem key={t.id} value={t.id}>
            {t.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function ParseReportCard({ version }: { version: VersionDetail }) {
  const r = version.parse_report;
  if (!r.parser) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Parsing report</CardTitle>
        <CardDescription>
          {r.parser} · {r.page_count ? `${r.page_count} pages · ` : ""}
          {r.sections} sections · {r.chunks} chunks · {r.tables} tables
          {r.embedding
            ? ` · indexed with ${r.embedding.model} (${r.embedding.embedded} new, ${r.embedding.reused} reused)`
            : ""}
        </CardDescription>
      </CardHeader>
      {(r.needs_review || (r.warnings?.length ?? 0) > 0) && (
        <CardContent className="flex flex-col gap-2 text-sm">
          {r.needs_review && r.ocr && (
            <Alert variant="destructive">
              <AlertTitle>Check the scanned pages</AlertTitle>
              <AlertDescription>
                OCR confidence was below {r.ocr.threshold} on page
                {r.ocr.low_confidence_pages.length === 1 ? "" : "s"}{" "}
                {r.ocr.low_confidence_pages.join(", ")} (lowest {r.ocr.min_confidence}). Compare the
                sections below with the original before publishing.
              </AlertDescription>
            </Alert>
          )}
          {r.warnings?.map((w) => (
            <p key={w} className="text-muted-foreground">
              ⚠ {w}
            </p>
          ))}
        </CardContent>
      )}
    </Card>
  );
}

type Override = { jurisdiction: string; topicId: string };

function SectionCard({
  section,
  ordinalLabel,
  jurisdictions,
  topics,
  override,
  onOverride,
  suggestion,
}: {
  section: SectionOut;
  ordinalLabel: string;
  jurisdictions: Jurisdiction[];
  topics: Topic[];
  override?: Override;
  onOverride?: (o: Override) => void;
  suggestion?: { jurisdiction?: string; topic_id?: string };
}) {
  const topicName = (id: string | null) => topics.find((t) => t.id === id)?.name;
  return (
    <div className="rounded-lg border p-4" id={`section-${section.id}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="text-xs text-muted-foreground">
            {ordinalLabel}
            {section.page_start ? ` · page ${section.page_start}` : ""} · {section.chunk_count}{" "}
            chunk{section.chunk_count === 1 ? "" : "s"} · ~{section.token_count} tokens
          </div>
          <div className="font-medium">
            {section.heading_path.length ? section.heading_path.join(" › ") : section.title}
          </div>
        </div>
        <div className="flex flex-wrap gap-1">
          {section.clause_number && <Badge variant="outline">§ {section.clause_number}</Badge>}
          {section.has_table && <Badge variant="outline">table</Badge>}
          {!onOverride && section.jurisdiction_code && (
            <Badge>{jurisdictionLabel(section.jurisdiction_code, jurisdictions)}</Badge>
          )}
          {!onOverride && section.topic_id && (
            <Badge variant="secondary">{topicName(section.topic_id)}</Badge>
          )}
        </div>
      </div>
      <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded bg-muted/50 p-3 font-sans text-sm">
        {section.text}
      </pre>
      {section.refs.length > 0 && (
        <p className="mt-2 text-xs text-muted-foreground">
          References:{" "}
          {section.refs.map((r, i) => (
            <span key={`${r.target_text}-${i}`}>
              {i > 0 && ", "}
              {r.to_section_id ? (
                <a className="underline" href={`#section-${r.to_section_id}`}>
                  {r.target_text}
                </a>
              ) : (
                <span title="Not in this document">{r.target_text} (external)</span>
              )}
            </span>
          ))}
        </p>
      )}
      {onOverride && override && (
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t pt-3 text-sm">
          <span className="text-muted-foreground">This section only:</span>
          <JurisdictionField
            label={`Jurisdiction for ${ordinalLabel}`}
            value={override.jurisdiction}
            onChange={(v) => onOverride({ ...override, jurisdiction: v })}
            jurisdictions={jurisdictions}
            placeholder="inherit"
          />
          <TopicSelect
            label={`Topic for ${ordinalLabel}`}
            value={override.topicId}
            onChange={(v) => onOverride({ ...override, topicId: v })}
            topics={topics}
            noneLabel="Inherit topic"
          />
          {suggestion && (suggestion.jurisdiction || suggestion.topic_id) && (
            <span className="text-xs text-muted-foreground">
              Suggested: {suggestion.jurisdiction ?? "—"}
              {suggestion.topic_id ? ` · ${topicName(suggestion.topic_id)}` : ""}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

function TagForm({
  version,
  sections,
  jurisdictions,
  topics,
  scopeFields,
  onSaved,
}: {
  version: VersionDetail;
  sections: SectionOut[];
  jurisdictions: Jurisdiction[];
  topics: Topic[];
  scopeFields: ScopeField[];
  onSaved: () => void;
}) {
  const api = useApi();
  const workspace = useWorkspace();
  const confirmed = version.tags_confirmed_at !== null;
  const suggested = version.tag_suggestions.version ?? {};
  const sectionSuggestions = version.tag_suggestions.sections ?? {};

  const [jurisdiction, setJurisdiction] = useState(
    (confirmed ? version.jurisdiction_code : suggested.jurisdiction) ?? "",
  );
  const [topicId, setTopicId] = useState(
    (confirmed ? version.topic_id : suggested.topic_id) ?? "",
  );
  const [scope, setScope] = useState<Record<string, string>>(
    confirmed ? version.scope : (suggested.scope ?? {}),
  );
  const [effectiveFrom, setEffectiveFrom] = useState(version.effective_from ?? "");
  const [effectiveTo, setEffectiveTo] = useState(version.effective_to ?? "");
  const [overrides, setOverrides] = useState<Record<string, Override>>(() =>
    Object.fromEntries(
      sections.map((s) => {
        const sg = sectionSuggestions[s.id] ?? {};
        return [
          s.id,
          confirmed
            ? { jurisdiction: s.jurisdiction_code ?? "", topicId: s.topic_id ?? "" }
            : { jurisdiction: sg.jurisdiction ?? "", topicId: sg.topic_id ?? "" },
        ];
      }),
    ),
  );
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await api.confirmTags(workspace.id, version.id, {
        jurisdiction_code: jurisdiction.trim().toUpperCase(),
        topic_id: topicId || null,
        scope: Object.fromEntries(Object.entries(scope).filter(([, v]) => v)),
        effective_from: effectiveFrom,
        effective_to: effectiveTo || null,
        sections: Object.entries(overrides)
          .filter(([, o]) => o.jurisdiction.trim() || o.topicId)
          .map(([id, o]) => ({
            section_id: id,
            jurisdiction_code: o.jurisdiction.trim().toUpperCase() || null,
            topic_id: o.topicId || null,
          })),
      });
      toast.success("Tags confirmed. Indexing has started.");
      onSaved();
    } catch (err) {
      toast.error(errorText(err, "Couldn't save the tags"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle>Where does this policy apply?</CardTitle>
          <CardDescription>
            {confirmed
              ? "Confirmed tags. Change them and save to re-index."
              : version.tag_suggestions.status === "ok"
                ? "Prefilled from AI suggestions. Nothing is used until you confirm."
                : `No AI suggestions (${version.tag_suggestions.status ?? "none"}). Tag by hand.`}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-wrap items-end gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="tag-jurisdiction">Jurisdiction</Label>
              <JurisdictionField
                id="tag-jurisdiction"
                label="Jurisdiction"
                value={jurisdiction}
                onChange={setJurisdiction}
                jurisdictions={jurisdictions}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label>Topic</Label>
              <TopicSelect
                label="Topic"
                value={topicId}
                onChange={setTopicId}
                topics={topics}
                noneLabel="Several topics / none"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="tag-from">Valid from</Label>
              <Input
                id="tag-from"
                type="date"
                required
                value={effectiveFrom}
                onChange={(e) => setEffectiveFrom(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="tag-to">Valid until (optional)</Label>
              <Input
                id="tag-to"
                type="date"
                value={effectiveTo}
                onChange={(e) => setEffectiveTo(e.target.value)}
              />
            </div>
          </div>
          {scopeFields.length > 0 && (
            <div className="flex flex-wrap items-end gap-4">
              {scopeFields.map((f) => (
                <div key={f.key} className="flex flex-col gap-1.5">
                  <Label>{f.name}</Label>
                  <Select
                    value={scope[f.key] || NONE}
                    onValueChange={(v) =>
                      setScope((s) => ({ ...s, [f.key]: v === NONE ? "" : v }))
                    }
                  >
                    <SelectTrigger className="w-44" aria-label={f.name}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={NONE}>Not restricted</SelectItem>
                      <SelectItem value={ANY}>All (*)</SelectItem>
                      {f.allowed_values.map((v) => (
                        <SelectItem key={v} value={v}>
                          {v}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              ))}
            </div>
          )}
          {(version.tag_suggestions.discarded?.length ?? 0) > 0 && (
            <details className="text-xs text-muted-foreground">
              <summary>Suggestions that were discarded ({version.tag_suggestions.discarded?.length})</summary>
              <ul className="mt-1 list-disc pl-5">
                {version.tag_suggestions.discarded?.map((d) => <li key={d}>{d}</li>)}
              </ul>
            </details>
          )}
          <div>
            <Button type="submit" disabled={busy || !jurisdiction.trim() || !effectiveFrom}>
              {busy ? "Saving…" : confirmed ? "Save and re-index" : "Confirm tags"}
            </Button>
          </div>
        </CardContent>
      </Card>

      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold">Sections ({sections.length})</h2>
        <p className="text-sm text-muted-foreground">
          Check that headings, clauses and tables came through intact. Set a jurisdiction on a
          section only when it differs from the document (e.g. a country annex).
        </p>
        {sections.map((s, i) => (
          <SectionCard
            key={s.id}
            section={s}
            ordinalLabel={`Section ${i + 1}`}
            jurisdictions={jurisdictions}
            topics={topics}
            override={overrides[s.id]}
            onOverride={(o) => setOverrides((all) => ({ ...all, [s.id]: o }))}
            suggestion={sectionSuggestions[s.id]}
          />
        ))}
      </section>
    </form>
  );
}

function PublishPanel({ version, onDone }: { version: VersionDetail; onDone: () => void }) {
  const api = useApi();
  const workspace = useWorkspace();
  const [conflicts, setConflicts] = useState<ConflictCandidate[] | null>(null);
  const [busy, setBusy] = useState(false);

  async function publish(acknowledge: boolean) {
    setBusy(true);
    try {
      await api.publish(workspace.id, version.id, acknowledge);
      toast.success("Published. This version can now be used to answer tickets.");
      setConflicts(null);
      onDone();
    } catch (err) {
      const candidates = err instanceof ApiError ? err.details?.candidates : undefined;
      if (Array.isArray(candidates)) setConflicts(candidates as ConflictCandidate[]);
      else toast.error(errorText(err, "Couldn't publish"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Publish</CardTitle>
        <CardDescription>
          Applies to {version.jurisdiction_code} from {version.effective_from}
          {version.effective_to ? ` until ${version.effective_to}` : ""}. An open-ended earlier
          version of this document is closed on that date.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {conflicts && (
          <Alert>
            <AlertTitle>Possible conflicts ({conflicts.length})</AlertTitle>
            <AlertDescription>
              <p className="mb-2">
                These published sections cover the same topic for an overlapping jurisdiction and
                period. Check they don&apos;t contradict this version.
              </p>
              <ul className="list-disc pl-5">
                {conflicts.slice(0, 20).map((c, i) => (
                  <li key={i}>
                    {c.section} ({c.jurisdiction}) ↔ <strong>{c.other_document}</strong>:{" "}
                    {c.other_section} ({c.other_jurisdiction})
                  </li>
                ))}
              </ul>
            </AlertDescription>
          </Alert>
        )}
        <div className="flex gap-2">
          {conflicts ? (
            <>
              <Button onClick={() => publish(true)} disabled={busy}>
                I&apos;ve checked: publish anyway
              </Button>
              <Button variant="ghost" onClick={() => setConflicts(null)} disabled={busy}>
                Cancel
              </Button>
            </>
          ) : (
            <Button onClick={() => publish(false)} disabled={busy}>
              {busy ? "Publishing…" : "Publish"}
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

export default function VersionPage() {
  const { versionId } = useParams<{ versionId: string }>();
  const api = useApi();
  const workspace = useWorkspace();
  const version = useQuery(`version:${versionId}`, () => api.version(workspace.id, versionId));
  const status = version.data?.pipeline_status;
  const sections = useQuery(
    status && !["queued", "parsing"].includes(status) ? `sections:${versionId}:${status}` : null,
    () => api.sections(workspace.id, versionId),
  );
  const { jurisdictions, topics, scopeFields } = useReference(workspace.id);
  usePolling(Boolean(status && IN_PROGRESS.includes(status)), version.reload);
  const editor = canEditKnowledge(workspace.role);

  async function action(fn: () => Promise<unknown>, done: string) {
    try {
      await fn();
      toast.success(done);
      version.reload();
    } catch (err) {
      toast.error(errorText(err, "That didn't work"));
    }
  }

  if (version.error) return <ErrorCard error={version.error} />;
  if (!version.data || !jurisdictions.data || !topics.data || !scopeFields.data) {
    return <Loading />;
  }
  const v = version.data;
  const reviewable =
    editor &&
    v.status === "draft" &&
    ["awaiting_review", "ready", "failed"].includes(v.pipeline_status) &&
    Boolean(v.parse_report.parser);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <Link
          href={`/w/${workspace.id}/documents/${v.document_id}`}
          className="text-sm text-muted-foreground"
        >
          ← Document
        </Link>
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-2xl font-semibold tracking-tight">Version {v.version_number}</h1>
          <VersionStatusBadge status={v.status} />
          <PipelineBadge status={v.pipeline_status} />
        </div>
        <p className="text-sm text-muted-foreground">
          {v.file_name}
          {v.jurisdiction_code
            ? ` · ${jurisdictionLabel(v.jurisdiction_code, jurisdictions.data)}`
            : ""}
          {v.effective_from ? ` · valid ${v.effective_from} → ${v.effective_to ?? "open"}` : ""}
        </p>
      </div>

      {v.pipeline_status === "failed" && (
        <Alert variant="destructive">
          <AlertTitle>Processing failed</AlertTitle>
          <AlertDescription>
            <p>{v.pipeline_error}</p>
            {editor && (
              <Button
                className="mt-2"
                variant="outline"
                size="sm"
                onClick={() => action(() => api.retry(workspace.id, v.id), "Retrying")}
              >
                Retry
              </Button>
            )}
          </AlertDescription>
        </Alert>
      )}
      {IN_PROGRESS.includes(v.pipeline_status) && (
        <p role="status" className="text-sm text-muted-foreground">
          Processing ({v.pipeline_status})… this page updates by itself.
        </p>
      )}

      <ParseReportCard version={v} />

      {editor && v.status === "draft" && v.pipeline_status === "ready" && (
        <PublishPanel version={v} onDone={version.reload} />
      )}
      {editor && v.status === "published" && (
        <div>
          <Button
            variant="outline"
            onClick={() => action(() => api.retire(workspace.id, v.id), "Retired")}
          >
            Retire this version
          </Button>
        </div>
      )}

      {!sections.data ? (
        sections.error ? <ErrorCard error={sections.error} /> : null
      ) : reviewable ? (
        <TagForm
          key={`${v.id}:${v.tags_confirmed_at ?? "new"}`}
          version={v}
          sections={sections.data}
          jurisdictions={jurisdictions.data}
          topics={topics.data}
          scopeFields={scopeFields.data}
          onSaved={version.reload}
        />
      ) : (
        <section className="flex flex-col gap-3">
          <h2 className="text-lg font-semibold">Sections ({sections.data.length})</h2>
          {sections.data.map((s, i) => (
            <SectionCard
              key={s.id}
              section={s}
              ordinalLabel={`Section ${i + 1}`}
              jurisdictions={jurisdictions.data ?? []}
              topics={topics.data ?? []}
            />
          ))}
        </section>
      )}
    </div>
  );
}
