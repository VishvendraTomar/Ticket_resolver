"use client";

import { ErrorCard, Loading } from "@/components/status";
import { useWorkspace } from "@/components/workspace-shell";
import { useApi, useQuery } from "@/lib/hooks";

export default function CoveragePage() {
  const api = useApi();
  const workspace = useWorkspace();
  const coverage = useQuery(`coverage:${workspace.id}`, () => api.coverage(workspace.id));

  if (coverage.error) return <ErrorCard error={coverage.error} />;
  if (!coverage.data) return <Loading />;
  const { jurisdictions, topics, cells } = coverage.data;
  const cell = new Map(cells.map((c) => [`${c.jurisdiction_code}|${c.topic_id ?? ""}`, c]));
  const indent = { global: 0, region: 1, country: 2, state: 3 } as const;

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Coverage</h1>
        <p className="text-sm text-muted-foreground">
          Published sections per jurisdiction and topic, from confirmed tags. Empty cells are
          gaps: tickets on that topic for that place can only be answered from a broader
          (e.g. global) policy, or not at all. Drafts don&apos;t count.
        </p>
      </div>
      {cells.length === 0 && (
        <p className="text-sm text-muted-foreground">Nothing is published yet.</p>
      )}
      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b bg-muted/40">
              <th className="sticky left-0 bg-muted/40 p-2 text-left font-medium">Jurisdiction</th>
              {topics.map((t) => (
                <th key={t.id} className="p-2 text-left font-medium whitespace-nowrap">
                  {t.name}
                </th>
              ))}
              <th className="p-2 text-left font-medium whitespace-nowrap">No topic</th>
            </tr>
          </thead>
          <tbody>
            {jurisdictions.map((j) => (
              <tr key={j.code} className="border-b last:border-0">
                <th
                  scope="row"
                  className="sticky left-0 bg-background p-2 text-left font-normal whitespace-nowrap"
                  style={{ paddingLeft: `${0.5 + indent[j.level] * 1}rem` }}
                >
                  {j.name} <span className="text-muted-foreground">({j.code})</span>
                </th>
                {[...topics.map((t) => t.id), ""].map((tid) => {
                  const c = cell.get(`${j.code}|${tid}`);
                  return (
                    <td
                      key={tid || "none"}
                      className={c ? "bg-emerald-50 p-2 dark:bg-emerald-950/40" : "p-2 text-muted-foreground/50"}
                      title={c ? `${c.sections} sections in ${c.documents} documents` : "gap"}
                    >
                      {c ? `${c.sections} · ${c.documents} doc${c.documents === 1 ? "" : "s"}` : "—"}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
