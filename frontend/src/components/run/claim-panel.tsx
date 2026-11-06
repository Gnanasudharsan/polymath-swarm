import { Badge } from "@/components/ui/badge";
import type { Claim, ClaimStatus, EvidenceKind } from "@/lib/types";

const STATUS_CLASS: Record<ClaimStatus, string> = {
  verified: "bg-green-100 text-green-800 border-green-300",
  refuted: "bg-red-100 text-red-800 border-red-300",
  challenged: "bg-amber-100 text-amber-800 border-amber-300",
  proposed: "bg-zinc-100 text-zinc-700 border-zinc-300",
};

const EVIDENCE_BADGE: Record<EvidenceKind, string> = {
  citation: "📚 citation",
  computation: "🧮 computation",
  formal_proof: "✅ Lean",
  critique: "🔍 critique",
};

const ORDER: ClaimStatus[] = ["verified", "challenged", "proposed", "refuted"];

export function ClaimPanel({ claims }: { claims: Claim[] }) {
  const sorted = [...claims].sort((a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status));
  if (!sorted.length) return <p className="text-sm text-zinc-500">No claims yet.</p>;
  return (
    <ul className="space-y-3" data-testid="claims">
      {sorted.map((c) => {
        const kinds = [...new Set(c.evidence.map((e) => e.kind))];
        return (
          <li key={c.id} className="rounded-lg border p-3" data-testid="claim" data-status={c.status}>
            <div className="mb-1 flex flex-wrap items-center gap-1.5">
              <Badge variant="outline" className={STATUS_CLASS[c.status]}>
                {c.status}
              </Badge>
              {kinds.map((k) => (
                <Badge key={k} variant="secondary" className="font-normal">
                  {EVIDENCE_BADGE[k]}
                </Badge>
              ))}
              {c.origin_run_id && (
                <Badge variant="outline" title={`recalled from ${c.origin_run_id}`}>
                  ♻️ memory
                </Badge>
              )}
            </div>
            <p className="text-sm leading-snug">{c.statement}</p>
          </li>
        );
      })}
    </ul>
  );
}
