import { Progress } from "@/components/ui/progress";
import type { Usage } from "@/lib/types";

export function CostMeter({ usage, maxUsd }: { usage: Usage; maxUsd: number | null }) {
  const pct = maxUsd ? Math.min(100, (usage.usd / maxUsd) * 100) : 0;
  const cap = maxUsd ? `of $${maxUsd.toFixed(2)}` : "no cap";
  return (
    <div className="space-y-1.5" data-testid="cost-meter">
      <div className="flex justify-between text-sm">
        <span className="font-medium" data-testid="cost-usd">
          ${usage.usd.toFixed(4)}
        </span>
        <span className="text-zinc-500">
          {cap} · {usage.tokens.toLocaleString()} tokens
        </span>
      </div>
      <Progress value={pct} />
    </div>
  );
}
