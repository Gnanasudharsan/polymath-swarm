import { cn } from "cn";

import type { Usage } from "@/lib/types";

export function CostMeter({ usage, maxUsd }: { usage: Usage; maxUsd: number | null }) {
  const pct = maxUsd ? Math.min(100, (usage.usd / maxUsd) * 100) : 0;
  const bar = pct >= 100 ? "bg-danger" : pct >= 80 ? "bg-warning" : "bg-primary";
  return (
    <div className="space-y-2" data-testid="cost-meter">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-2xl font-semibold tracking-tight tabular-nums" data-testid="cost-usd">
          ${usage.usd.toFixed(4)}
        </span>
        <span className="text-xs text-muted-foreground tabular-nums">
          {maxUsd ? `of $${maxUsd.toFixed(2)}` : "no cap"}
        </span>
      </div>
      <div
        className="h-1.5 w-full overflow-hidden rounded-full bg-muted"
        role="progressbar"
        aria-label="Budget used"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(pct)}
      >
        <div
          className={cn("h-full rounded-full transition-[width] duration-500", bar)}
          style={{ width: `${Math.max(pct, usage.usd > 0 ? 2 : 0)}%` }}
        />
      </div>
      <p className="text-xs text-muted-foreground tabular-nums">
        {usage.tokens.toLocaleString()} tokens · {pct.toFixed(0)}% of budget
      </p>
    </div>
  );
}
