"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getRun, streamUrl } from "@/lib/api";
import type { BlackboardEvent, Claim, RunDetail, TaskStatus } from "@/lib/types";

import { ApprovalPanel } from "./approval-panel";
import { ClaimPanel } from "./claim-panel";
import { CostMeter } from "./cost-meter";
import { ReportView } from "./report-view";
import { TaskGraph } from "./task-graph";

// Events after which the full run state is re-read (plan changes, approvals, completion).
const REFRESH_ON = new Set(["plan_created", "task_finished", "message", "budget_warning", "run_finished"]);

function describe(e: BlackboardEvent): string {
  const p = e.payload;
  switch (e.kind) {
    case "task_started":
      return `▶ ${p.task_id} (${p.role})`;
    case "task_finished":
      return `${p.success ? "✓" : "✗"} ${p.task_id}${p.usd ? ` · $${Number(p.usd).toFixed(4)}` : ""}`;
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

  if (error && !run) return <p className="text-red-600">Could not load run: {error}</p>;
  if (!run) return <p className="text-zinc-500">Loading…</p>;

  const status = { ...run.task_status, ...live };
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-3xl space-y-1">
          <p className="font-mono text-xs text-zinc-500">{run.run_id}</p>
          <h1 className="text-lg font-semibold leading-snug">{run.problem}</h1>
          <Badge data-testid="run-status" data-status={run.status ?? ""}>
            {run.status ?? "starting"}
          </Badge>
          {run.stop_reason && <p className="text-xs text-zinc-500">{run.stop_reason}</p>}
        </div>
        <div className="w-72">
          <CostMeter usage={run.usage} maxUsd={run.max_usd} />
        </div>
      </div>

      {run.awaiting_approval && <ApprovalPanel runId={run.run_id} onDone={refresh} />}

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_380px]">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Task graph</CardTitle>
          </CardHeader>
          <CardContent className="h-[440px] p-0" data-testid="task-graph">
            <TaskGraph tasks={run.tasks} status={status} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Claims</CardTitle>
          </CardHeader>
          <CardContent className="max-h-[440px] overflow-y-auto">
            <ClaimPanel claims={Object.values(claims)} />
          </CardContent>
        </Card>
      </div>

      {run.report_markdown && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Evidence report</CardTitle>
          </CardHeader>
          <CardContent>
            <ReportView markdown={run.report_markdown} />
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Activity</CardTitle>
        </CardHeader>
        <CardContent>
          <ol className="max-h-56 space-y-1 overflow-y-auto font-mono text-xs" data-testid="activity">
            {log.map((e) => (
              <li key={e.id} className="text-zinc-600">
                <span className="text-zinc-400">{e.created_at.slice(11, 19)}</span> {describe(e)}
              </li>
            ))}
          </ol>
        </CardContent>
      </Card>
    </div>
  );
}
