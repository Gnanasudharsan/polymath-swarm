"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { approveRun } from "@/lib/api";

export function ApprovalPanel({ runId, onDone }: { runId: string; onDone: () => void }) {
  const [feedback, setFeedback] = useState("");
  const [busy, setBusy] = useState(false);
  const act = async (approved: boolean) => {
    setBusy(true);
    try {
      await approveRun(runId, approved, feedback);
      onDone();
    } finally {
      setBusy(false);
    }
  };
  return (
    <div
      className="space-y-2 rounded-lg border border-indigo-300 bg-indigo-50 p-3"
      data-testid="approval"
    >
      <p className="text-sm font-medium">The supervisor proposed this plan. Approve it?</p>
      <Textarea
        placeholder="Optional feedback: reject with feedback to get a new plan"
        value={feedback}
        onChange={(e) => setFeedback(e.target.value)}
        rows={2}
      />
      <div className="flex gap-2">
        <Button onClick={() => act(true)} disabled={busy}>
          Approve plan
        </Button>
        <Button variant="outline" onClick={() => act(false)} disabled={busy}>
          {feedback ? "Replan with feedback" : "Reject"}
        </Button>
      </div>
    </div>
  );
}
