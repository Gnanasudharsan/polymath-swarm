import { BookOpen, Calculator, ChevronRight, Inbox, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { Suspense } from "react";

import { NewRunForm } from "@/components/new-run-form";
import { RUN_STATUS, RunStatusPill } from "@/components/status";
import { timeAgo } from "@/lib/format";
import type { RunSummary } from "@/lib/types";

const PILLARS = [
  {
    icon: BookOpen,
    title: "Verified citations",
    body: "Every quote is re-fetched from the paper and matched word for word.",
  },
  {
    icon: Calculator,
    title: "Reproduced computations",
    body: "Programs run in a locked-down sandbox, then the gate runs them again.",
  },
  {
    icon: ShieldCheck,
    title: "Lean 4 proofs",
    body: "Formal proofs with Mathlib: no sorry, no custom axioms.",
  },
];

function dotColor(status: RunSummary["status"]): string {
  const tone = status ? RUN_STATUS[status].tone : "running";
  return `var(--${tone === "neutral" ? "muted-foreground" : tone})`;
}

/** Uncached, request-time read (Cache Components: rendered inside <Suspense>). */
async function RecentRuns() {
  const api = process.env.POLYMATH_API_URL ?? "http://localhost:8000";
  let runs: RunSummary[] = [];
  let reachable = true;
  let now = 0; // server time of the response, for "5 min ago"
  try {
    const res = await fetch(`${api}/runs`, {
      headers: { "x-api-key": process.env.POLYMATH_API_KEY ?? "" },
      cache: "no-store",
    });
    if (res.ok) runs = ((await res.json()) as { runs: RunSummary[] }).runs;
    else reachable = false;
    now = new Date(res.headers.get("date") ?? 0).getTime();
  } catch {
    reachable = false;
  }
  if (runs.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 px-6 py-12 text-center">
        <span className="grid size-10 place-items-center rounded-full bg-muted text-muted-foreground">
          <Inbox className="size-5" />
        </span>
        <p className="text-sm font-medium">{reachable ? "No runs yet" : "API unreachable"}</p>
        <p className="max-w-sm text-sm text-muted-foreground">
          {reachable
            ? "Pose a problem above. Runs appear here with their status and evidence."
            : "Start the API (polymath serve) and refresh this page."}
        </p>
      </div>
    );
  }
  return (
    <ul className="divide-y" data-testid="recent-runs">
      {runs.map((r) => (
        <li key={r.run_id}>
          <Link
            href={`/runs/${r.run_id}`}
            className="group flex items-center gap-4 px-5 py-3 transition-colors hover:bg-muted/60"
          >
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium group-hover:text-primary">{r.problem}</p>
              <p className="mt-0.5 font-mono text-[11px] text-muted-foreground">
                {r.run_id} · {timeAgo(r.created_at, now)}
              </p>
            </div>
            <RunStatusPill status={r.status} className="hidden sm:inline-flex" />
            <span
              className="size-2 rounded-full sm:hidden"
              style={{ background: dotColor(r.status) }}
              aria-label={r.status ?? "starting"}
            />
            <ChevronRight className="size-4 text-muted-foreground/60 transition-transform group-hover:translate-x-0.5 group-hover:text-foreground" />
          </Link>
        </li>
      ))}
    </ul>
  );
}

function RunsSkeleton() {
  return (
    <ul className="divide-y">
      {[0, 1, 2].map((i) => (
        <li key={i} className="flex items-center gap-4 px-5 py-3.5">
          <div className="flex-1 space-y-2">
            <div className="h-3.5 w-2/3 animate-pulse rounded bg-muted" />
            <div className="h-2.5 w-1/3 animate-pulse rounded bg-muted" />
          </div>
          <div className="h-6 w-24 animate-pulse rounded-full bg-muted" />
        </li>
      ))}
    </ul>
  );
}

export default function Home() {
  return (
    <main className="w-full">
      <section className="bg-hero border-b">
        <div className="mx-auto w-full max-w-5xl px-4 pt-14 pb-10 sm:px-6 sm:pt-20">
          <p className="mb-4 inline-flex items-center gap-2 rounded-full border bg-card/70 px-3 py-1 text-xs font-medium text-muted-foreground shadow-xs">
            <span className="size-1.5 rounded-full bg-success" />
            Verification-first multi-agent research
          </p>
          <h1 className="text-4xl font-semibold tracking-tight text-balance sm:text-5xl">
            Polymath Swarm
          </h1>
          <p className="mt-4 max-w-2xl text-base text-pretty text-muted-foreground sm:text-lg">
            A team of specialist agents plans, researches, computes, proves and critiques. Only
            claims backed by checkable evidence make it into the answer.
          </p>
          <div className="mt-8 grid gap-3 sm:grid-cols-3">
            {PILLARS.map(({ icon: Icon, title, body }) => (
              <div
                key={title}
                className="flex gap-3 rounded-xl border bg-card/80 p-3.5 shadow-xs backdrop-blur sm:block sm:p-4"
              >
                <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-accent text-accent-foreground sm:mb-3">
                  <Icon className="size-4" />
                </span>
                <div>
                  <p className="text-sm font-medium">{title}</p>
                  <p className="mt-0.5 text-sm leading-relaxed text-muted-foreground sm:mt-1">{body}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <div className="mx-auto w-full max-w-5xl space-y-8 px-4 py-10 sm:px-6">
        <section aria-labelledby="new-problem">
          <h2 id="new-problem" className="sr-only">
            New problem
          </h2>
          <NewRunForm />
        </section>

        <section id="runs" aria-labelledby="runs-title" className="scroll-mt-20">
          <div className="mb-3 flex items-end justify-between">
            <div>
              <h2 id="runs-title" className="text-base font-semibold tracking-tight">
                Recent runs
              </h2>
              <p className="text-sm text-muted-foreground">Open a run to see its plan, claims and report.</p>
            </div>
          </div>
          <div className="overflow-hidden rounded-xl border bg-card shadow-xs">
            <Suspense fallback={<RunsSkeleton />}>
              <RecentRuns />
            </Suspense>
          </div>
        </section>
      </div>
    </main>
  );
}
