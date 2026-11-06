import type { RunDetail, RunSummary } from "./types";

// The browser only talks to our Next.js proxy (/api/polymath/*), which adds the API key.
const BASE = "/api/polymath";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return (await res.json()) as T;
}

export async function createRun(input: {
  problem: string;
  max_usd: number;
  require_approval: boolean;
}): Promise<{ run_id: string }> {
  return json(
    await fetch(`${BASE}/runs`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(input),
    }),
  );
}

export async function listRuns(): Promise<RunSummary[]> {
  return (await json<{ runs: RunSummary[] }>(await fetch(`${BASE}/runs`, { cache: "no-store" })))
    .runs;
}

export async function getRun(id: string): Promise<RunDetail> {
  return json(await fetch(`${BASE}/runs/${id}`, { cache: "no-store" }));
}

export async function approveRun(id: string, approved: boolean, feedback?: string) {
  return json(
    await fetch(`${BASE}/runs/${id}/approve`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ approved, feedback: feedback || null }),
    }),
  );
}

export function streamUrl(id: string): string {
  return `${BASE}/runs/${id}/stream`;
}
