import {
  Ban,
  BookOpen,
  Calculator,
  CircleCheck,
  CircleDashed,
  CircleX,
  Clock,
  Coins,
  LoaderCircle,
  type LucideIcon,
  Search,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";
import { cn } from "cn";

import type { ClaimStatus, EvidenceKind, RunStatus, TaskStatus } from "@/lib/types";

/** One semantic palette for the whole app (tokens in globals.css). */
export type Tone = "success" | "warning" | "danger" | "running" | "neutral";

export const TONE: Record<Tone, { pill: string; dot: string; text: string; border: string }> = {
  success: {
    pill: "bg-success-soft text-success-foreground ring-success/25",
    dot: "bg-success",
    text: "text-success-foreground",
    border: "border-l-success",
  },
  warning: {
    pill: "bg-warning-soft text-warning-foreground ring-warning/30",
    dot: "bg-warning",
    text: "text-warning-foreground",
    border: "border-l-warning",
  },
  danger: {
    pill: "bg-danger-soft text-danger-foreground ring-danger/25",
    dot: "bg-danger",
    text: "text-danger-foreground",
    border: "border-l-danger",
  },
  running: {
    pill: "bg-running-soft text-running-foreground ring-running/25",
    dot: "bg-running",
    text: "text-running-foreground",
    border: "border-l-running",
  },
  neutral: {
    pill: "bg-neutral-soft text-neutral-foreground ring-foreground/10",
    dot: "bg-muted-foreground/60",
    text: "text-muted-foreground",
    border: "border-l-border",
  },
};

export const RUN_STATUS: Record<RunStatus, { tone: Tone; label: string; icon: LucideIcon }> = {
  planning: { tone: "running", label: "Planning", icon: LoaderCircle },
  awaiting_approval: { tone: "warning", label: "Awaiting approval", icon: Clock },
  executing: { tone: "running", label: "Running", icon: LoaderCircle },
  completed: { tone: "success", label: "Completed", icon: CircleCheck },
  budget_exhausted: { tone: "warning", label: "Budget reached", icon: Coins },
  rejected: { tone: "neutral", label: "Rejected", icon: Ban },
  failed: { tone: "danger", label: "Failed", icon: CircleX },
};

export const TASK_STATUS: Record<TaskStatus, { tone: Tone; label: string }> = {
  pending: { tone: "neutral", label: "Pending" },
  running: { tone: "running", label: "Running" },
  done: { tone: "success", label: "Done" },
  failed: { tone: "danger", label: "Failed" },
  skipped: { tone: "neutral", label: "Skipped" },
};

export const CLAIM_STATUS: Record<ClaimStatus, { tone: Tone; label: string; icon: LucideIcon }> = {
  verified: { tone: "success", label: "verified", icon: ShieldCheck },
  challenged: { tone: "warning", label: "challenged", icon: TriangleAlert },
  proposed: { tone: "neutral", label: "proposed", icon: CircleDashed },
  refuted: { tone: "danger", label: "refuted", icon: CircleX },
};

export const EVIDENCE: Record<EvidenceKind, { label: string; icon: LucideIcon }> = {
  citation: { label: "citation", icon: BookOpen },
  computation: { label: "computation", icon: Calculator },
  formal_proof: { label: "Lean proof", icon: ShieldCheck },
  critique: { label: "critique", icon: Search },
};

const ACTIVE: RunStatus[] = ["planning", "executing"];

export function isActive(status: RunStatus | null): boolean {
  return status === null || ACTIVE.includes(status);
}

export function Pill({
  tone,
  children,
  className,
  ...props
}: React.ComponentProps<"span"> & { tone: Tone }) {
  return (
    <span
      className={cn(
        "inline-flex h-6 shrink-0 items-center gap-1.5 rounded-full px-2.5 text-xs font-medium whitespace-nowrap ring-1 ring-inset",
        TONE[tone].pill,
        className,
      )}
      {...props}
    >
      {children}
    </span>
  );
}

export function StatusDot({ tone, pulse = false }: { tone: Tone; pulse?: boolean }) {
  return (
    <span className="relative inline-flex size-2">
      {pulse && (
        <span
          className={cn(
            "absolute inline-flex size-full animate-ping rounded-full opacity-60 motion-reduce:animate-none",
            TONE[tone].dot,
          )}
        />
      )}
      <span className={cn("relative inline-flex size-2 rounded-full", TONE[tone].dot)} />
    </span>
  );
}

export function RunStatusPill({
  status,
  ...props
}: { status: RunStatus | null } & React.ComponentProps<"span">) {
  const s = status ? RUN_STATUS[status] : RUN_STATUS.planning;
  return (
    <Pill tone={s.tone} {...props}>
      <StatusDot tone={s.tone} pulse={isActive(status)} />
      {status ? s.label : "Starting"}
    </Pill>
  );
}
