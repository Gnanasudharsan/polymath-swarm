"use client";

import { ArrowRight, BookOpen, Calculator, CornerDownLeft, LoaderCircle, Sigma } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Switch } from "@/components/ui/switch";
import { createRun } from "@/lib/api";

const MAX_CHARS = 8000;

const EXAMPLES = [
  {
    icon: Sigma,
    kind: "Proof",
    text: "Prove that for every natural number n, the product n * (n + 1) is even.",
  },
  {
    icon: Calculator,
    kind: "Computation",
    text: "Compute the sum of the first 100 prime numbers, and determine whether that sum is prime.",
  },
  {
    icon: BookOpen,
    kind: "Literature",
    text: "Who proved the 2023 exponential improvement for diagonal Ramsey numbers, and what bound?",
  },
];

export function NewRunForm() {
  const router = useRouter();
  const [problem, setProblem] = useState("");
  const [maxUsd, setMaxUsd] = useState("0.50");
  const [approval, setApproval] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const budget = Number(maxUsd);
  const budgetOk = Number.isFinite(budget) && budget > 0 && budget <= 10;
  const canSubmit = !busy && problem.trim().length > 0 && budgetOk;

  const submit = async () => {
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    try {
      const { run_id } = await createRun({
        problem,
        max_usd: budget,
        require_approval: approval,
      });
      router.push(`/runs/${run_id}`);
    } catch (err) {
      setError(String(err));
      setBusy(false);
    }
  };

  return (
    <div className="rounded-2xl border bg-card shadow-sm ring-1 ring-transparent transition-shadow focus-within:shadow-md focus-within:ring-primary/30">
      <label htmlFor="problem" className="sr-only">
        Problem
      </label>
      <textarea
        id="problem"
        data-testid="problem-input"
        placeholder="State a research or mathematics problem…"
        rows={5}
        maxLength={MAX_CHARS}
        value={problem}
        onChange={(e) => setProblem(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
            e.preventDefault();
            void submit();
          }
        }}
        className="block w-full resize-y rounded-t-2xl bg-transparent px-5 pt-5 pb-3 text-[15px] leading-relaxed outline-none placeholder:text-muted-foreground/70"
      />

      <div className="flex flex-wrap gap-2 px-5 pb-4">
        {EXAMPLES.map(({ icon: Icon, kind, text }) => (
          <button
            key={kind}
            type="button"
            onClick={() => setProblem(text)}
            title={text}
            className="group inline-flex max-w-full items-center gap-1.5 rounded-full border bg-background px-3 py-1 text-xs text-muted-foreground transition-colors hover:border-primary/40 hover:bg-accent hover:text-accent-foreground"
          >
            <Icon className="size-3.5 shrink-0" />
            <span className="font-medium text-foreground/80 group-hover:text-accent-foreground">
              {kind}
            </span>
            <span className="hidden truncate md:inline">
              {text.length > 48 ? `${text.slice(0, 48)}…` : text}
            </span>
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-x-6 gap-y-3 border-t bg-muted/40 px-5 py-3 rounded-b-2xl">
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          Budget
          <span className="relative">
            <span className="pointer-events-none absolute inset-y-0 left-2.5 flex items-center text-muted-foreground">
              $
            </span>
            <input
              type="number"
              step="0.05"
              min="0.01"
              max="10"
              value={maxUsd}
              onChange={(e) => setMaxUsd(e.target.value)}
              aria-invalid={!budgetOk}
              className="h-8 w-24 rounded-lg border bg-background pr-2 pl-6 text-sm text-foreground tabular-nums outline-none focus-visible:ring-2 focus-visible:ring-ring/40 aria-invalid:border-destructive"
            />
          </span>
        </label>
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          <Switch checked={approval} onCheckedChange={setApproval} data-testid="approval-toggle" />
          Approve plan before running
        </label>
        <div className="ml-auto flex items-center gap-3">
          <span className="hidden items-center gap-1 text-xs text-muted-foreground lg:inline-flex">
            <kbd className="rounded border bg-background px-1.5 font-sans">⌘</kbd>
            <CornerDownLeft className="size-3" />
          </span>
          <span className="hidden text-xs text-muted-foreground tabular-nums sm:inline">
            {problem.length.toLocaleString()}/{MAX_CHARS.toLocaleString()}
          </span>
          <button
            type="button"
            onClick={() => void submit()}
            disabled={!canSubmit}
            data-testid="submit"
            className="inline-flex h-9 items-center gap-2 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground shadow-sm transition-all hover:brightness-110 focus-visible:ring-3 focus-visible:ring-ring/40 focus-visible:outline-none active:translate-y-px disabled:pointer-events-none disabled:opacity-50"
          >
            {busy ? (
              <>
                <LoaderCircle className="size-4 animate-spin" /> Starting…
              </>
            ) : (
              <>
                Solve <ArrowRight className="size-4" />
              </>
            )}
          </button>
        </div>
      </div>
      {error && (
        <p className="border-t bg-danger-soft px-5 py-2.5 text-sm text-danger-foreground rounded-b-2xl">
          {error}
        </p>
      )}
    </div>
  );
}
