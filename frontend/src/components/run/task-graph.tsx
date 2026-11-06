"use client";

import "@xyflow/react/dist/style.css";

import {
  Background,
  BackgroundVariant,
  Controls,
  type Edge,
  type Node,
  Position,
  ReactFlow,
} from "@xyflow/react";
import { LoaderCircle } from "lucide-react";
import { useMemo } from "react";

import { TASK_STATUS, type Tone } from "@/components/status";
import type { TaskInfo, TaskStatus } from "@/lib/types";

import { roleIcon } from "./roles";

// Theme-aware colours (CSS variables from globals.css), per semantic tone.
const NODE_TONE: Record<Tone, { accent: string; soft: string; text: string }> = {
  success: { accent: "var(--success)", soft: "var(--success-soft)", text: "var(--success-foreground)" },
  warning: { accent: "var(--warning)", soft: "var(--warning-soft)", text: "var(--warning-foreground)" },
  danger: { accent: "var(--danger)", soft: "var(--danger-soft)", text: "var(--danger-foreground)" },
  running: { accent: "var(--running)", soft: "var(--running-soft)", text: "var(--running-foreground)" },
  neutral: { accent: "var(--border)", soft: "var(--neutral-soft)", text: "var(--neutral-foreground)" },
};

const NODE_W = 200;
const NODE_H = 76;

/** Longest-path layering: a task's column is one more than its deepest dependency. */
export function layout(tasks: TaskInfo[]): Record<string, { x: number; y: number }> {
  const byId = new Map(tasks.map((t) => [t.id, t]));
  const level = new Map<string, number>();
  const depth = (id: string, seen: Set<string>): number => {
    const known = level.get(id);
    if (known !== undefined) return known;
    if (seen.has(id)) return 0; // defensive: plans are validated DAGs
    seen.add(id);
    const deps = byId.get(id)?.deps.filter((d) => byId.has(d)) ?? [];
    const d = deps.length ? 1 + Math.max(...deps.map((x) => depth(x, seen))) : 0;
    level.set(id, d);
    return d;
  };
  tasks.forEach((t) => depth(t.id, new Set()));
  const rows = new Map<number, number>();
  const pos: Record<string, { x: number; y: number }> = {};
  for (const t of tasks) {
    const col = level.get(t.id) ?? 0;
    const row = rows.get(col) ?? 0;
    rows.set(col, row + 1);
    pos[t.id] = { x: col * 250, y: row * 112 };
  }
  return pos;
}

export function GraphLegend() {
  const items: TaskStatus[] = ["pending", "running", "done", "failed"];
  return (
    <div className="hidden flex-wrap items-center gap-3 text-xs text-muted-foreground sm:flex">
      {items.map((s) => (
        <span key={s} className="inline-flex items-center gap-1.5">
          <span
            className="size-2.5 rounded-sm ring-1 ring-inset ring-black/5"
            style={{ background: NODE_TONE[TASK_STATUS[s].tone].accent }}
          />
          {TASK_STATUS[s].label}
        </span>
      ))}
    </div>
  );
}

export function TaskGraph({
  tasks,
  status,
}: {
  tasks: TaskInfo[];
  status: Record<string, TaskStatus>;
}) {
  const { nodes, edges } = useMemo(() => {
    const pos = layout(tasks);
    const nodes: Node[] = tasks.map((t) => {
      const st = status[t.id] ?? "pending";
      const { tone, label } = TASK_STATUS[st];
      const c = NODE_TONE[tone];
      const Icon = roleIcon(t.assigned_role);
      return {
        id: t.id,
        position: pos[t.id],
        data: {
          label: (
            <div
              className="flex h-full flex-col justify-between text-left"
              data-testid={`task-${t.id}`}
              data-status={st}
              title={t.description}
            >
              <div className="flex items-center gap-2">
                <span
                  className="grid size-6 shrink-0 place-items-center rounded-md"
                  style={{ background: c.soft, color: c.text }}
                >
                  <Icon className="size-3.5" />
                </span>
                <div className="min-w-0">
                  <div className="truncate font-mono text-[11px] font-semibold text-foreground">{t.id}</div>
                  <div className="truncate text-[11px] text-muted-foreground">{t.assigned_role}</div>
                </div>
              </div>
              <span
                className="inline-flex w-fit items-center gap-1 rounded-full px-2 py-px text-[10px] font-medium tracking-wide uppercase"
                style={{ background: c.soft, color: c.text }}
              >
                {st === "running" && <LoaderCircle className="size-2.5 animate-spin" />}
                {label}
              </span>
            </div>
          ),
        },
        className: st === "running" ? "animate-pulse-ring" : undefined,
        style: {
          background: "var(--card)",
          color: "var(--card-foreground)",
          border: "1px solid var(--border)",
          borderLeft: `4px solid ${c.accent}`,
          borderRadius: 12,
          padding: "10px 12px",
          width: NODE_W,
          height: NODE_H,
          boxShadow: "0 1px 2px rgb(0 0 0 / 0.05)",
        },
        draggable: false,
        // Explicit size: nodes are rebuilt on every status change, and without known dimensions
        // React Flow hides them until re-measured (a visible flicker).
        width: NODE_W,
        height: NODE_H,
        // Columns run left to right, so connect right side → left side.
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
      };
    });
    const edges: Edge[] = tasks.flatMap((t) =>
      t.deps.map((d) => {
        const done = status[d] === "done";
        return {
          id: `${d}->${t.id}`,
          source: d,
          target: t.id,
          type: "smoothstep",
          animated: status[t.id] === "running",
          style: {
            stroke: done ? "var(--success)" : undefined,
            strokeWidth: 1.5,
            opacity: done ? 0.7 : 1,
          },
        };
      }),
    );
    return { nodes, edges };
  }, [tasks, status]);

  if (!tasks.length) {
    return (
      <div className="grid h-full place-items-center">
        <div className="flex flex-col items-center gap-2 text-sm text-muted-foreground">
          <LoaderCircle className="size-5 animate-spin text-primary" />
          The supervisor is planning…
        </div>
      </div>
    );
  }
  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      fitView
      // Long plans would otherwise shrink until unreadable: keep a legible zoom and let the user
      // drag to pan instead (wheel scrolling stays with the page).
      fitViewOptions={{ padding: 0.15, minZoom: 0.8, maxZoom: 1.1 }}
      onInit={(flow) => {
        // When the plan is wider than the panel, start at its first task, not its middle.
        requestAnimationFrame(() => {
          const vp = flow.getViewport();
          if (vp.x < 0) flow.setViewport({ ...vp, x: 24 });
        });
      }}
      minZoom={0.4}
      maxZoom={1.5}
      preventScrolling={false}
      zoomOnScroll={false}
      nodesConnectable={false}
      proOptions={{ hideAttribution: true }}
    >
      <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="var(--grid-dot)" />
      <Controls showInteractive={false} position="bottom-right" />
    </ReactFlow>
  );
}
