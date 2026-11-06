import Link from "next/link";
import { Suspense } from "react";

import { RunView } from "@/components/run/run-view";

async function Run({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <RunView runId={id} />;
}

export default function RunPage(props: PageProps<"/runs/[id]">) {
  return (
    <main className="mx-auto w-full max-w-7xl space-y-4 p-6">
      <Link href="/" className="text-sm text-zinc-500 hover:underline">
        ← New problem
      </Link>
      <Suspense fallback={<p className="text-zinc-500">Loading…</p>}>
        <Run params={props.params} />
      </Suspense>
    </main>
  );
}
