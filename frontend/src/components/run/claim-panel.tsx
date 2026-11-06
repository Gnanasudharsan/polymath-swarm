"use client";

import { ChevronRight, Recycle } from "lucide-react";
import { cn } from "cn";
import { useState } from "react";

import { CLAIM_STATUS, EVIDENCE, Pill, TONE } from "@/components/status";
import type { Claim, ClaimStatus } from "@/lib/types";

const ORDER: ClaimStatus[] = ["verified", "challenged", "proposed", "refuted"];
type Filter = "all" | ClaimStatus;

export function ClaimPanel({ claims }: { claims: Claim[] }) {
  const [filter, setFilter] = useState<Filter>("all");
  const sorted = [...claims].sort((a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status));
  const counts = Object.fromEntries(ORDER.map((s) => [s, claims.filter((c) => c.status === s).length]));
  const shown = filter === "all" ? sorted : sorted.filter((c) => c.status === filter);

  if (!sorted.length) {
    return (
      <p className="px-5 py-10 text-center text-sm text-muted-foreground">
        No claims yet. They appear here as agents propose them.
      </p>
    );
  }
  const tabs: Filter[] = ["all", ...ORDER.filter((s) => counts[s] > 0)];
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex gap-1 overflow-x-auto border-b px-3 py-2 scrollbar-thin" role="tablist">
        {tabs.map((t) => (
          <button
            key={t}
            type="button"
            role="tab"
            aria-selected={filter === t}
            onClick={() => setFilter(t)}
            className={cn(
              "inline-flex shrink-0 items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium capitalize transition-colors",
              filter === t ? "bg-secondary text-foreground" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {t}
            <span className="rounded bg-background/70 px-1 tabular-nums text-muted-foreground">
              {t === "all" ? claims.length : counts[t]}
            </span>
          </button>
        ))}
      </div>
      <ul className="min-h-0 flex-1 space-y-2.5 overflow-y-auto p-3 scrollbar-thin" data-testid="claims">
        {shown.map((c) => (
          <ClaimCard key={c.id} claim={c} />
        ))}
      </ul>
    </div>
  );
}

function ClaimCard({ claim: c }: { claim: Claim }) {
  const st = CLAIM_STATUS[c.status];
  const kinds = [...new Set(c.evidence.map((e) => e.kind))];
  const StatusIcon = st.icon;
  const [open, setOpen] = useState(false);
  const long = c.statement.length > 260;
  return (
    <li
      className={cn("rounded-lg border border-l-[3px] bg-card p-3", TONE[st.tone].border)}
      data-testid="claim"
      data-status={c.status}
    >
      <div className="mb-2 flex flex-wrap items-center gap-1.5">
        <Pill tone={st.tone} className="h-5 px-2 text-[11px]">
          <StatusIcon className="size-3" />
          {st.label}
        </Pill>
        {kinds.map((k) => {
          const { icon: Icon, label } = EVIDENCE[k];
          return (
            <span
              key={k}
              className="inline-flex h-5 items-center gap-1 rounded-full border bg-background px-2 text-[11px] text-muted-foreground"
            >
              <Icon className="size-3" />
              {label}
            </span>
          );
        })}
        {c.origin_run_id && (
          <span
            title={`recalled from ${c.origin_run_id}`}
            className="inline-flex h-5 items-center gap-1 rounded-full border bg-background px-2 text-[11px] text-muted-foreground"
          >
            <Recycle className="size-3" /> memory
          </span>
        )}
      </div>
      <p className={cn("text-sm leading-relaxed break-words", long && !open && "line-clamp-5")}>
        {c.statement}
      </p>
      {long && (
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="mt-1 text-xs font-medium text-primary hover:underline"
        >
          {open ? "Show less" : "Show more"}
        </button>
      )}
      {c.evidence.length > 0 && (
        <details className="group mt-2">
          <summary className="flex cursor-pointer list-none items-center gap-1 text-xs text-muted-foreground select-none hover:text-foreground">
            <ChevronRight className="size-3.5 transition-transform group-open:rotate-90" />
            {c.evidence.length} piece{c.evidence.length === 1 ? "" : "s"} of evidence
          </summary>
          <ul className="mt-2 space-y-1.5 border-l pl-3">
            {c.evidence.map((e) => (
              <li key={e.id} className="text-xs leading-relaxed text-muted-foreground">
                <span className="font-medium text-foreground/80">{EVIDENCE[e.kind].label}:</span>{" "}
                {e.summary}
              </li>
            ))}
          </ul>
        </details>
      )}
    </li>
  );
}
