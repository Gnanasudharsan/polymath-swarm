"""Graph nodes: plan → approve → dispatch ⇄ execute_task (parallel) → finalize."""

from __future__ import annotations

import asyncio
from typing import Any, Final, Literal, TypedDict

from langgraph.graph import END
from langgraph.runtime import Runtime
from langgraph.types import Command, Send, interrupt

from polymath.agents.base import AgentContext, AgentResult
from polymath.core.budget import BudgetExceededError
from polymath.core.logging import get_logger
from polymath.core.models import Claim, EventKind, Problem, Task, TaskStatus, TaskType
from polymath.graph.context import RunContext
from polymath.graph.revision import add_revision_round, is_optional, triggering_claims
from polymath.graph.state import (
    RunStatus,
    SwarmState,
    Usage,
    ready_task_ids,
    task_outcomes,
)
from polymath.llm.cost import LLMUsage
from polymath.llm.usage_scope import usage_scope
from polymath.verification.report import EvidenceReport, render_markdown

log = get_logger(__name__)

PLAN: Final = "plan"
APPROVE: Final = "approve"
DISPATCH: Final = "dispatch"
EXECUTE: Final = "execute_task"
FINALIZE: Final = "finalize"


class TaskInput(TypedDict):
    """Payload of a ``Send`` to :func:`execute_task`."""

    run_id: str
    problem: Problem
    task: Task
    deps: dict[str, AgentResult]
    claims: list[Claim]


def _usage(records: list[LLMUsage]) -> Usage:
    return Usage(tokens=sum(r.total_tokens for r in records), usd=sum(r.usd for r in records))


async def plan(
    state: SwarmState, runtime: Runtime[RunContext]
) -> Command[Literal["approve", "finalize"]]:
    ctx, run_id = runtime.context, state["run_id"]
    problem = state["problem"].model_copy()
    try:
        graph, usage = await ctx.planner.plan(problem, state.get("plan_feedback") or None)
    except BudgetExceededError as exc:
        return Command(
            goto=FINALIZE, update={"status": RunStatus.BUDGET_EXHAUSTED, "stop_reason": str(exc)}
        )
    except Exception as exc:
        log.exception("graph.plan_failed", run_id=run_id)
        return Command(
            goto=FINALIZE, update={"status": RunStatus.FAILED, "stop_reason": f"planner: {exc}"}
        )
    await ctx.blackboard.post(
        run_id,
        EventKind.PLAN_CREATED,
        round=state.get("plan_rounds", 0) + 1,
        problem_type=problem.problem_type.value if problem.problem_type else None,
        plan=graph.model_dump(mode="json"),
    )
    return Command(
        goto=APPROVE,
        update={
            "problem": problem,
            "plan": graph,
            "plan_rounds": state.get("plan_rounds", 0) + 1,
            "plan_feedback": "",
            "approved": False,
            "usage": _usage(usage),
            "status": (
                RunStatus.AWAITING_APPROVAL if _needs_approval(state, ctx) else RunStatus.EXECUTING
            ),
        },
    )


async def approve(
    state: SwarmState, runtime: Runtime[RunContext]
) -> Command[Literal["plan", "dispatch", "finalize"]]:
    """Human-in-the-loop gate. Resume with ``True``/``False`` or
    ``{"approved": bool, "feedback": str}``; rejection with feedback triggers a replan."""
    ctx = runtime.context
    if not _needs_approval(state, ctx) or state.get("approved"):
        return Command(goto=DISPATCH, update={"approved": True, "status": RunStatus.EXECUTING})

    decision: Any = interrupt(
        {
            "type": "plan_approval",
            "run_id": state["run_id"],
            "plan": state["plan"].model_dump(mode="json"),
        }
    )
    # Everything below runs only once the human has answered.
    if isinstance(decision, dict):
        approved, feedback = bool(decision.get("approved")), str(decision.get("feedback") or "")
    else:
        approved, feedback = bool(decision), ""
    await ctx.blackboard.post(
        state["run_id"], EventKind.MESSAGE, topic="plan_decision", approved=approved,
        feedback=feedback,
    )  # fmt: skip
    if approved:
        return Command(goto=DISPATCH, update={"approved": True, "status": RunStatus.EXECUTING})
    if feedback and state.get("plan_rounds", 0) < ctx.max_plan_rounds:
        return Command(goto=PLAN, update={"plan_feedback": feedback, "status": RunStatus.PLANNING})
    return Command(
        goto=FINALIZE,
        update={"status": RunStatus.REJECTED, "stop_reason": feedback or "plan rejected"},
    )


def _needs_approval(state: SwarmState, ctx: RunContext) -> bool:
    """The run's own setting (checkpointed at start) wins over the process default."""
    return bool(state.get("require_approval", ctx.require_approval))


async def dispatch(state: SwarmState, runtime: Runtime[RunContext]) -> dict[str, Any]:
    """Sync the budget from the checkpoint, stop if exhausted or done, else count a round."""
    ctx = runtime.context
    usage = state.get("usage") or Usage()
    elapsed = ctx.elapsed(state.get("elapsed_s", 0.0))
    iterations = state.get("iterations", 0)
    ctx.budget.restore(
        tokens_used=usage.tokens, usd_used=usage.usd, iterations=iterations, elapsed_s=elapsed
    )
    update: dict[str, Any] = {"elapsed_s": elapsed}
    plan, results = state["plan"], dict(state.get("results") or {})

    # Critique loop: refuted/challenged claims before synthesis → insert a revision round.
    handled = set(state.get("handled_claims") or [])
    trigger = triggering_claims(state.get("claims") or {}, handled)
    rounds = state.get("revision_rounds", 0)
    if trigger and rounds < ctx.max_revision_rounds:
        revised = add_revision_round(plan, results, trigger, rounds + 1)
        if revised is not None:
            plan = revised
            update |= {
                "plan": plan,
                "revision_rounds": rounds + 1,
                "handled_claims": sorted(handled | {c.id for c in trigger}),
            }
            await ctx.blackboard.post(
                state["run_id"], EventKind.MESSAGE, topic="revision_round", round=rounds + 1,
                claims=[c.id for c in trigger], plan=plan.model_dump(mode="json"),
            )  # fmt: skip

    ready = ready_task_ids(plan, results)
    if not ready:
        return update | {"status": RunStatus.COMPLETED}
    try:
        ctx.budget.check()
    except BudgetExceededError as exc:
        return update | {"status": RunStatus.BUDGET_EXHAUSTED, "stop_reason": str(exc)}
    if ctx.budget.is_near_limit():
        await ctx.blackboard.post(
            state["run_id"], EventKind.BUDGET_WARNING, **ctx.budget.snapshot()
        )
        # Degrade gracefully: drop optional work (extra critique rounds) near the ceiling.
        skipped = {
            tid: AgentResult(
                task_id=tid,
                role=plan.tasks[tid].assigned_role,
                output="(skipped: run budget nearly exhausted)",
            )
            for tid in ready
            if is_optional(plan.tasks[tid])
        }
        if skipped:
            update["results"] = skipped
    return update | {"iterations": iterations + 1, "status": RunStatus.EXECUTING}


def route(state: SwarmState, runtime: Runtime[RunContext]) -> list[Send] | str:
    """Fan out every ready task in parallel (up to ``max_parallel``), or finish."""
    # Compare by value: top-level enum fields come back from Postgres as plain strings.
    if state.get("status") != RunStatus.EXECUTING:
        return FINALIZE
    results = state.get("results") or {}
    ready = ready_task_ids(state["plan"], results)[: runtime.context.max_parallel]
    return [
        Send(
            EXECUTE,
            TaskInput(
                run_id=state["run_id"],
                problem=state["problem"],
                task=state["plan"].tasks[tid],
                # skipped inputs have no result; synthesis may still run without them
                deps={d: results[d] for d in state["plan"].tasks[tid].deps if d in results},
                claims=list((state.get("claims") or {}).values()),
            ),
        )
        for tid in ready
    ]


async def execute_task(payload: TaskInput, runtime: Runtime[RunContext]) -> dict[str, Any]:
    ctx, task, run_id = runtime.context, payload["task"], payload["run_id"]
    await ctx.blackboard.post(
        run_id, EventKind.TASK_STARTED, task_id=task.id, role=task.assigned_role.value
    )
    deps = payload["deps"]
    agent_ctx = AgentContext(
        problem=payload["problem"],
        claims=payload["claims"],
        messages=[m for r in deps.values() for m in r.messages],
        notes="\n\n".join(f"### Output of `{tid}`\n{r.output}" for tid, r in deps.items()),
    )
    timeout = ctx.timeout_for(task)
    with usage_scope() as spent:
        try:
            executor = ctx.executor_for(task.assigned_role)
            result = await asyncio.wait_for(executor.run(task, agent_ctx), timeout)
        except TimeoutError:
            result = _failed(task, f"TimeoutError: task exceeded {timeout:g}s")
        except (BudgetExceededError, LookupError) as exc:
            result = _failed(task, f"{type(exc).__name__}: {exc}")
        except Exception as exc:
            log.exception("graph.task_failed", run_id=run_id, task_id=task.id)
            result = _failed(task, f"{type(exc).__name__}: {exc}")
    if spent:
        # The gateway saw every call, including those of a task that failed or timed out.
        result = result.model_copy(update={"usage": list(spent)})

    for claim in result.claims:
        await ctx.blackboard.post(
            run_id, EventKind.CLAIM_PROPOSED, task_id=task.id, claim=claim.model_dump(mode="json")
        )
    await ctx.blackboard.post(
        run_id,
        EventKind.TASK_FINISHED,
        task_id=task.id,
        role=task.assigned_role.value,
        success=result.success,
        error=result.error,
        usd=result.usd,
        output_preview=result.output[:500],
    )
    return {
        "results": {task.id: result},
        "claims": {c.id: c for c in result.claims},
        "usage": _usage(result.usage),
    }


def _failed(task: Task, error: str) -> AgentResult:
    return AgentResult(
        task_id=task.id, role=task.assigned_role, output="", success=False, error=error
    )


async def finalize(state: SwarmState, runtime: Runtime[RunContext]) -> dict[str, Any]:
    ctx, run_id = runtime.context, state["run_id"]
    status = RunStatus(state.get("status", RunStatus.COMPLETED))
    update: dict[str, Any] = {}
    if "plan" in state:
        results = state.get("results") or {}
        outcome = task_outcomes(state["plan"], results)
        plan = state["plan"].model_copy(deep=True)
        for tid, task_status in outcome.items():
            plan.tasks[tid].status = task_status
        update["plan"] = plan
        update["answer"] = _answer(plan.tasks.values(), results)
        report = _report(state, plan.tasks.values(), results)
        if report is not None:
            update["report"], update["report_markdown"] = report
        if status is RunStatus.COMPLETED and not any(r.success for r in results.values()):
            status = RunStatus.FAILED
            update["stop_reason"] = "no task succeeded"
    update["status"] = status
    await ctx.blackboard.post(
        run_id,
        EventKind.RUN_FINISHED,
        status=status.value,
        stop_reason=update.get("stop_reason", state.get("stop_reason", "")),
    )
    return update


def _report(
    state: SwarmState, tasks: Any, results: dict[str, AgentResult]
) -> tuple[dict[str, Any], str] | None:
    """The synthesiser's evidence report, stamped with run id and final cost."""
    for task in tasks:
        r = results.get(task.id)
        if task.type is TaskType.SYNTHESIS and r and r.success and "report" in r.data:
            usage = state.get("usage") or Usage()
            report = EvidenceReport.model_validate(r.data["report"]).model_copy(
                update={"run_id": state["run_id"], "usd": usage.usd, "tokens": usage.tokens}
            )
            return report.model_dump(mode="json"), render_markdown(report)
    return None


def _answer(tasks: Any, results: dict[str, AgentResult]) -> str:
    """The synthesis output if it ran, otherwise the outputs of the successful leaf tasks."""
    for task in tasks:
        r = results.get(task.id)
        if task.type is TaskType.SYNTHESIS and r and r.success:
            return r.output
    done = [t for t in tasks if t.status is TaskStatus.DONE]
    return "\n\n".join(results[t.id].output for t in done if results[t.id].output)


__all__ = ["END", "approve", "dispatch", "execute_task", "finalize", "plan", "route"]
