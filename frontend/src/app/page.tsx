import Link from "next/link";
import { Suspense } from "react";

import { NewRunForm } from "@/components/new-run-form";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { RunSummary } from "@/lib/types";

/** Uncached, request-time read (Cache Components: rendered inside <Suspense>). */
async function RecentRuns() {
  const api = process.env.POLYMATH_API_URL ?? "http://localhost:8000";
  let runs: RunSummary[] = [];
  try {
    const res = await fetch(`${api}/runs`, {
      headers: { "x-api-key": process.env.POLYMATH_API_KEY ?? "" },
      cache: "no-store",
    });
    if (res.ok) runs = ((await res.json()) as { runs: RunSummary[] }).runs;
  } catch {
    // API down: show the empty state
  }
  if (runs.length === 0) return <p className="text-sm text-zinc-500">No runs yet.</p>;
  return (
    <ul className="divide-y" data-testid="recent-runs">
      {runs.map((r) => (
        <li key={r.run_id} className="flex items-center justify-between gap-4 py-2">
          <Link href={`/runs/${r.run_id}`} className="truncate text-sm hover:underline">
            {r.problem}
          </Link>
          <Badge variant="outline">{r.status ?? "…"}</Badge>
        </li>
      ))}
    </ul>
  );
}

export default function Home() {
  return (
    <main className="mx-auto max-w-5xl space-y-6 p-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold">Polymath Swarm</h1>
        <p className="text-sm text-zinc-600">
          A verification-first multi-agent swarm. Every claim in the answer carries evidence: a
          verified citation, a reproduced computation, or a Lean 4 proof.
        </p>
      </header>
      <Card>
        <CardHeader>
          <CardTitle className="text-base">New problem</CardTitle>
        </CardHeader>
        <CardContent>
          <NewRunForm />
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Recent runs</CardTitle>
        </CardHeader>
        <CardContent>
          <Suspense fallback={<p className="text-sm text-zinc-500">Loading…</p>}>
            <RecentRuns />
          </Suspense>
        </CardContent>
      </Card>
    </main>
  );
}
