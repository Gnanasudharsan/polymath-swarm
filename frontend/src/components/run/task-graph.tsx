"use client";

import "@xyflow/react/dist/style.css";

import { Background, type Edge, type Node, Position, ReactFlow } from "@xyflow/react";
import { useMemo } from "react";

import type { TaskInfo, TaskStatus } from "@/lib/types";

const STATUS_STYLE: Record<TaskStatus, { bg: string; border: string; label: string }> = {
  pending: { bg: "#f4f4f5", border: "#d4d4d8", label: "pending" },
  running: { bg: "#e0e7ff", border: "#6366f1", label: "running" },
  done: { bg: "#dcfce7", border: "#16a34a", label: "done" },
  failed: { bg: "#fee2e2", border: "#dc2626", label: "failed" },
  skipped: { bg: "#f4f4f5", border: "#a1a1aa", label: "skipped" },
};

const NODE_W = 190;
const NODE_H = 72;

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
    pos[t.id] = { x: col * 240, y: row * 110 };
  }
  return pos;
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
      const s = STATUS_STYLE[st];
      return {
        id: t.id,
        position: pos[t.id],
        data: {
          label: (
            <div className="text-left" data-testid={`task-${t.id}`} data-status={st}>
              <div className="font-mono text-xs font-semibold">{t.id}</div>
              <div className="text-[11px] text-zinc-600">{t.assigned_role}</div>
              <div className="mt-1 text-[10px] uppercase tracking-wide">{s.label}</div>
            </div>
          ),
        },
        style: {
          background: s.bg,
          border: `2px solid ${s.border}`,
          borderRadius: 10,
          width: NODE_W,
          height: NODE_H,
          boxShadow: st === "running" ? `0 0 0 4px ${s.border}33` : undefined,
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
      t.deps.map((d) => ({
        id: `${d}->${t.id}`,
        source: d,
        target: t.id,
        type: "smoothstep",
        animated: status[t.id] === "running",
      })),
    );
    return { nodes, edges };
  }, [tasks, status]);

  if (!tasks.length) {
    return <div className="grid h-full place-items-center text-sm text-zinc-500">Planning…</div>;
  }
  return (
    <ReactFlow nodes={nodes} edges={edges} fitView proOptions={{ hideAttribution: true }}>
      <Background gap={20} />
    </ReactFlow>
  );
}
