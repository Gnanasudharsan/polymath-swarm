"use client";

import {
  Ban,
  CircleCheck,
  CircleX,
  Copy,
  Check,
  Coins,
  Download,
  FileText,
  ListChecks,
  Play,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
  Workflow,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { RunStatusPill } from "@/components/status";
import { getRun, streamUrl } from "@/lib/api";
import type { BlackboardEvent, Claim, RunDetail, TaskStatus } from "@/lib/types";

import { ApprovalPanel } from "./approval-panel";
import { ClaimPanel } from "./claim-panel";
import { CostMeter } from "./cost-meter";
import { ReportView } from "./report-view";
import { GraphLegend, TaskGraph } from "./task-graph";

// Events after which the full run state is re-read (plan changes, approvals, completion).
const REFRESH_ON = new Set(["plan_created", "task_finished", "message", "budget_warning", "run_finished"]);

function describe(e: BlackboardEvent): string {
  const p = e.payload;
  switch (e.kind) {
    case "task_started":
      return `${p.task_id} started (${p.role})`;
    case "task_finished":
      return `${p.task_id} ${p.success ? "done" : "failed"}${p.usd ? ` · $${Number(p.usd).toFixed(4)}` : ""}`;
    case "claim_proposed":
      return `claim: ${String((p.claim as Claim | undefined)?.statement ?? "").slice(0, 90)}`;
    case "plan_created":
      return `plan created (round ${p.round})`;
    case "run_finished":
      return `run finished: ${p.status}`;
    default:
      return p.topic ? `${e.kind}: ${p.topic}` : e.kind;
  }
}

function eventIcon(e: BlackboardEvent) {
  switch (e.kind) {
    case "task_started":
      return { Icon: Play, cls: "text-running-foreground bg-running-soft" };
    case "task_finished":
      return e.payload.success
        ? { Icon: CircleCheck, cls: "text-success-foreground bg-success-soft" }
        : { Icon: CircleX, cls: "text-danger-foreground bg-danger-soft" };
    case "claim_proposed":
      return { Icon: Sparkles, cls: "text-accent-foreground bg-accent" };
    case "plan_created":
      return { Icon: Workflow, cls: "text-accent-foreground bg-accent" };
    case "budget_warning":
      return { Icon: Coins, cls: "text-warning-foreground bg-warning-soft" };
    case "run_finished":
      return { Icon: ShieldCheck, cls: "text-success-foreground bg-success-soft" };
    default:
      return { Icon: ListChecks, cls: "text-muted-foreground bg-muted" };
  }
}

function Panel({
  title,
  icon: Icon,
  actions,
  children,
  className = "",
  bodyClassName = "",
  ...props
}: {
  title: string;
  icon: typeof FileText;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  bodyClassName?: string;
} & Omit<React.ComponentProps<"section">, "title">) {
  return (
    <section className={`flex flex-col overflow-hidden rounded-xl border bg-card shadow-xs ${className}`} {...props}>
      <div className="flex min-h-12 items-center gap-2 border-b px-5 py-2.5">
        <Icon className="size-4 text-muted-foreground" />
        <h2 className="text-sm font-semibold tracking-tight whitespace-nowrap">{title}</h2>
        {actions && <div className="ml-auto flex items-center gap-2">{actions}</div>}
      </div>
      <div className={bodyClassName}>{children}</div>
    </section>
  );
}

function Stat({
  label,
  value,
  hint,
  className = "",
}: {
  label: string;
  value: React.ReactNode;
  hint?: string;
  className?: string;
}) {
  return (
    <div className={`rounded-xl border bg-card p-4 shadow-xs ${className}`}>
      <p className="text-xs font-medium text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-semibold tracking-tight tabular-nums">{value}</p>
      {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

function ReportActions({ markdown, runId }: { markdown: string; runId: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    await navigator.clipboard.writeText(markdown);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  const download = () => {
    const url = URL.createObjectURL(new Blob([markdown], { type: "text/markdown" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: `${runId}.md` });
    a.click();
    URL.revokeObjectURL(url);
  };
  const btn =
    "inline-flex h-7 items-center gap-1.5 rounded-md border bg-background px-2.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground";
  return (
    <>
      <button type="button" className={btn} onClick={() => void copy()}>
        {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
        {copied ? "Copied" : "Copy"}
      </button>
      <button type="button" className={btn} onClick={download}>
        <Download className="size-3.5" /> .md
      </button>
    </>
  );
}

export function RunView({ runId }: { runId: string }) {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [live, setLive] = useState<Record<string, TaskStatus>>({});
  const [claims, setClaims] = useState<Record<string, Claim>>({});
  const [log, setLog] = useState<BlackboardEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const pending = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const detail = await getRun(runId);
      setRun(detail);
      setClaims(Object.fromEntries(detail.claims.map((c) => [c.id, c])));
      setLive({});
      setError(null);
    } catch (err) {
      setError(String(err));
    }
  }, [runId]);

  const scheduleRefresh = useCallback(() => {
    if (pending.current) clearTimeout(pending.current);
    pending.current = setTimeout(refresh, 250);
  }, [refresh]);

  useEffect(() => {
    scheduleRefresh(); // initial load, outside the effect body
    const source = new EventSource(streamUrl(runId));
    source.onmessage = (msg) => {
      const e = JSON.parse(msg.data) as BlackboardEvent;
      setLog((prev) => (prev.some((x) => x.id === e.id) ? prev : [e, ...prev].slice(0, 200)));
      const p = e.payload;
      if (e.kind === "task_started") setLive((s) => ({ ...s, [String(p.task_id)]: "running" }));
      if (e.kind === "task_finished")
        setLive((s) => ({ ...s, [String(p.task_id)]: p.success ? "done" : "failed" }));
      if (e.kind === "claim_proposed" && p.claim) {
        const c = p.claim as Claim;
        setClaims((s) => ({ ...s, [c.id]: c }));
      }
      if (REFRESH_ON.has(e.kind)) scheduleRefresh();
      if (e.kind === "run_finished") source.close();
    };
    source.onerror = () => {
      // The server closes the stream when the run finishes; reconnects are automatic otherwise.
      scheduleRefresh();
    };
    return () => source.close();
  }, [runId, scheduleRefresh]);

  if (error && !run) {
    return (
      <div className="flex items-start gap-3 rounded-xl border border-danger/30 bg-danger-soft p-4 text-sm text-danger-foreground">
        <TriangleAlert className="mt-0.5 size-4 shrink-0" />
        <div>
          <p className="font-medium">Could not load this run</p>
          <p className="mt-0.5 opacity-90">{error}</p>
        </div>
      </div>
    );
  }
  if (!run) return <RunSkeleton />;

  const status = { ...run.task_status, ...live };
  const claimList = Object.values(claims);
  const done = run.tasks.filter((t) => status[t.id] === "done").length;
  const failed = run.tasks.filter((t) => status[t.id] === "failed").length;
  const verified = claimList.filter((c) => c.status === "verified").length;
  const refuted = claimList.filter((c) => c.status === "refuted").length;

  return (
    <div className="space-y-6">
      <header className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <RunStatusPill status={run.status} data-testid="run-status" data-status={run.status ?? ""} />
          <span className="font-mono text-xs text-muted-foreground">{run.run_id}</span>
        </div>
        <h1 className="max-w-4xl text-xl leading-snug font-semibold tracking-tight text-balance sm:text-2xl">
          {run.problem}
        </h1>
        {run.stop_reason && (
          <p className="inline-flex items-center gap-1.5 text-sm text-muted-foreground">
            <Ban className="size-3.5" /> {run.stop_reason}
          </p>
        )}
      </header>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <div className="col-span-2 rounded-xl border bg-card p-4 shadow-xs lg:col-span-1">
          <p className="mb-1 text-xs font-medium text-muted-foreground">Cost</p>
          <CostMeter usage={run.usage} maxUsd={run.max_usd} />
        </div>
        <Stat
          label="Tasks"
          value={
            <>
              {done}
              <span className="text-base text-muted-foreground">/{run.tasks.length || "–"}</span>
            </>
          }
          hint={failed ? `${failed} failed` : run.tasks.length ? "completed" : "planning"}
        />
        <Stat
          label="Verified claims"
          value={
            <span className={verified ? "text-success-foreground" : undefined}>
              {verified}
              <span className="text-base text-muted-foreground">/{claimList.length}</span>
            </span>
          }
          hint={claimList.length ? `${Math.round((verified / claimList.length) * 100)}% backed by evidence` : "none yet"}
        />
        <Stat
          className="col-span-2 sm:col-span-1"
          label="Refuted"
          value={<span className={refuted ? "text-danger-foreground" : undefined}>{refuted}</span>}
          hint="claims disproved by the gate"
        />
      </div>

      {run.awaiting_approval && <ApprovalPanel runId={run.run_id} tasks={run.tasks} onDone={refresh} />}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_400px]">
        <Panel title="Task graph" icon={Workflow} actions={<GraphLegend />} className="min-h-[460px]">
          <div className="h-[420px]" data-testid="task-graph">
            <TaskGraph tasks={run.tasks} status={status} />
          </div>
        </Panel>
        <Panel title="Claims" icon={ShieldCheck} className="h-[480px]" bodyClassName="flex min-h-0 flex-1 flex-col">
          <ClaimPanel claims={claimList} />
        </Panel>
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_400px]">
        {run.report_markdown ? (
          <Panel
            title="Evidence report"
            icon={FileText}
            actions={<ReportActions markdown={run.report_markdown} runId={run.run_id} />}
            bodyClassName="px-6 py-5"
          >
            <ReportView markdown={run.report_markdown} />
          </Panel>
        ) : (
          <Panel title="Evidence report" icon={FileText} bodyClassName="px-6 py-10">
            <p className="text-center text-sm text-muted-foreground">
              The synthesizer writes the report once the tasks finish. It may state only verified claims.
            </p>
          </Panel>
        )}
        <Panel title="Activity" icon={ListChecks} className="lg:max-h-[640px]" bodyClassName="min-h-0 flex-1 overflow-hidden">
          <ol
            className="max-h-80 space-y-0.5 overflow-y-auto px-3 py-3 scrollbar-thin lg:max-h-[580px]"
            data-testid="activity"
          >
            {log.length === 0 && <li className="px-2 py-6 text-center text-sm text-muted-foreground">Waiting for events…</li>}
            {log.map((e) => {
              const { Icon, cls } = eventIcon(e);
              return (
                <li key={e.id} className="flex items-start gap-2.5 rounded-md px-2 py-1.5 hover:bg-muted/50">
                  <span className={`mt-px grid size-5 shrink-0 place-items-center rounded-md ${cls}`}>
                    <Icon className="size-3" />
                  </span>
                  <span className="min-w-0 flex-1 text-xs leading-relaxed break-words">{describe(e)}</span>
                  <time className="shrink-0 font-mono text-[10px] leading-5 text-muted-foreground">
                    {e.created_at.slice(11, 19)}
                  </time>
                </li>
              );
            })}
          </ol>
        </Panel>
      </div>
    </div>
  );
}

function RunSkeleton() {
  return (
    <div className="space-y-6" aria-busy="true">
      <div className="space-y-3">
        <div className="h-6 w-40 animate-pulse rounded-full bg-muted" />
        <div className="h-7 w-2/3 animate-pulse rounded bg-muted" />
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="h-28 animate-pulse rounded-xl border bg-card" />
        ))}
      </div>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_400px]">
        <div className="h-[460px] animate-pulse rounded-xl border bg-card" />
        <div className="h-[460px] animate-pulse rounded-xl border bg-card" />
      </div>
    </div>
  );
}
