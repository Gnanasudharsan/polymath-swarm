"use client";

import { Check, ClipboardList, LoaderCircle, RotateCcw, X } from "lucide-react";
import { useState } from "react";

import { approveRun } from "@/lib/api";
import type { TaskInfo } from "@/lib/types";

import { roleIcon } from "./roles";

export function ApprovalPanel({
  runId,
  tasks,
  onDone,
}: {
  runId: string;
  tasks: TaskInfo[];
  onDone: () => void;
}) {
  const [feedback, setFeedback] = useState("");
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const act = async (approved: boolean) => {
    setBusy(approved ? "approve" : "reject");
    try {
      await approveRun(runId, approved, feedback);
      onDone();
    } finally {
      setBusy(null);
    }
  };
  return (
    <section
      className="overflow-hidden rounded-xl border border-warning/40 bg-card shadow-sm"
      data-testid="approval"
    >
      <div className="flex items-start gap-3 border-b border-warning/25 bg-warning-soft px-5 py-4">
        <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-warning/20 text-warning-foreground">
          <ClipboardList className="size-4" />
        </span>
        <div>
          <p className="text-sm font-semibold">The supervisor proposed this plan. Approve it?</p>
          <p className="text-sm text-muted-foreground">
            {tasks.length} task{tasks.length === 1 ? "" : "s"}. Nothing runs until you decide; reject
            with feedback to get a new plan.
          </p>
        </div>
      </div>

      <ol className="divide-y">
        {tasks.map((t, i) => {
          const Icon = roleIcon(t.assigned_role);
          return (
            <li key={t.id} className="flex gap-3 px-5 py-3">
              <span className="mt-0.5 w-5 shrink-0 text-right font-mono text-xs text-muted-foreground">
                {i + 1}
              </span>
              <span className="mt-0.5 grid size-6 shrink-0 place-items-center rounded-md bg-accent text-accent-foreground">
                <Icon className="size-3.5" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-sm">
                  <span className="font-mono text-xs font-semibold">{t.id}</span>
                  <span className="text-muted-foreground"> · {t.assigned_role}</span>
                  {t.deps.length > 0 && (
                    <span className="text-xs text-muted-foreground"> · after {t.deps.join(", ")}</span>
                  )}
                </p>
                <p className="mt-0.5 line-clamp-2 text-sm text-muted-foreground">{t.description}</p>
              </div>
            </li>
          );
        })}
      </ol>

      <div className="space-y-3 border-t bg-muted/30 px-5 py-4">
        <textarea
          placeholder="Optional feedback: reject with feedback to get a new plan"
          value={feedback}
          onChange={(e) => setFeedback(e.target.value)}
          rows={2}
          className="block w-full resize-y rounded-lg border bg-background px-3 py-2 text-sm outline-none placeholder:text-muted-foreground/70 focus-visible:ring-2 focus-visible:ring-ring/40"
        />
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => void act(true)}
            disabled={busy !== null}
            className="inline-flex h-9 items-center gap-2 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground shadow-sm transition-all hover:brightness-110 active:translate-y-px disabled:opacity-50"
          >
            {busy === "approve" ? <LoaderCircle className="size-4 animate-spin" /> : <Check className="size-4" />}
            Approve plan
          </button>
          <button
            type="button"
            onClick={() => void act(false)}
            disabled={busy !== null}
            className="inline-flex h-9 items-center gap-2 rounded-lg border bg-background px-4 text-sm font-medium transition-colors hover:bg-muted disabled:opacity-50"
          >
            {busy === "reject" ? (
              <LoaderCircle className="size-4 animate-spin" />
            ) : feedback ? (
              <RotateCcw className="size-4" />
            ) : (
              <X className="size-4" />
            )}
            {feedback ? "Replan with feedback" : "Reject"}
          </button>
        </div>
      </div>
    </section>
  );
}
