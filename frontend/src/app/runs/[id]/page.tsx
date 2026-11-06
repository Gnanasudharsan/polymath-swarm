import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { Suspense } from "react";

import { RunView } from "@/components/run/run-view";

async function Run({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <RunView runId={id} />;
}

export default function RunPage(props: PageProps<"/runs/[id]">) {
  return (
    <main className="w-full bg-hero">
      <div className="mx-auto w-full max-w-7xl space-y-5 px-4 py-6 sm:px-6">
        <nav aria-label="Breadcrumb" className="flex items-center gap-1 text-sm text-muted-foreground">
          <Link href="/" className="transition-colors hover:text-foreground">
            New problem
          </Link>
          <ChevronRight className="size-3.5" />
          <Link href="/#runs" className="transition-colors hover:text-foreground">
            Runs
          </Link>
          <ChevronRight className="size-3.5" />
          <span className="text-foreground">Run</span>
        </nav>
        <Suspense fallback={<p className="text-sm text-muted-foreground">Loading…</p>}>
          <Run params={props.params} />
        </Suspense>
      </div>
    </main>
  );
}
