"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { createRun } from "@/lib/api";

const EXAMPLES = [
  "Prove that for every natural number n, the product n * (n + 1) is even.",
  "Compute the sum of the first 100 prime numbers, and determine whether that sum is prime.",
  "Who proved the 2023 exponential improvement for diagonal Ramsey numbers, and what bound?",
];

export function NewRunForm() {
  const router = useRouter();
  const [problem, setProblem] = useState("");
  const [maxUsd, setMaxUsd] = useState("0.50");
  const [approval, setApproval] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const { run_id } = await createRun({
        problem,
        max_usd: Number(maxUsd),
        require_approval: approval,
      });
      router.push(`/runs/${run_id}`);
    } catch (err) {
      setError(String(err));
      setBusy(false);
    }
  };

  return (
    <div className="space-y-3">
      <Textarea
        data-testid="problem-input"
        placeholder="State a research or mathematics problem…"
        rows={4}
        value={problem}
        onChange={(e) => setProblem(e.target.value)}
      />
      <div className="flex flex-wrap gap-2">
        {EXAMPLES.map((ex) => (
          <button
            key={ex}
            type="button"
            onClick={() => setProblem(ex)}
            className="rounded-full border px-3 py-1 text-xs text-zinc-600 hover:bg-zinc-100"
          >
            {ex.length > 60 ? `${ex.slice(0, 60)}…` : ex}
          </button>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-6">
        <label className="flex items-center gap-2 text-sm">
          Budget (USD)
          <Input
            className="w-24"
            type="number"
            step="0.05"
            min="0.01"
            value={maxUsd}
            onChange={(e) => setMaxUsd(e.target.value)}
          />
        </label>
        <label className="flex items-center gap-2 text-sm">
          <Switch checked={approval} onCheckedChange={setApproval} data-testid="approval-toggle" />
          Approve plan before running
        </label>
        <Button onClick={submit} disabled={busy || !problem.trim()} data-testid="submit">
          {busy ? "Starting…" : "Solve"}
        </Button>
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}
    </div>
  );
}
