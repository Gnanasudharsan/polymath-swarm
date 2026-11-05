"""Assemble the swarm ``StateGraph``."""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from polymath.graph import nodes
from polymath.graph.context import RunContext
from polymath.graph.state import SwarmState

SwarmGraph = CompiledStateGraph[SwarmState, RunContext, SwarmState, SwarmState]


def build_graph() -> StateGraph[SwarmState, RunContext, SwarmState, SwarmState]:
    g: StateGraph[SwarmState, RunContext, SwarmState, SwarmState] = StateGraph(
        SwarmState, context_schema=RunContext
    )
    g.add_node(nodes.PLAN, nodes.plan, destinations=(nodes.APPROVE, nodes.FINALIZE))
    g.add_node(
        nodes.APPROVE, nodes.approve, destinations=(nodes.PLAN, nodes.DISPATCH, nodes.FINALIZE)
    )
    g.add_node(nodes.DISPATCH, nodes.dispatch)
    # Send-only node: its input is TaskInput, not the graph state. LangGraph's overloads
    # cannot infer that from a TypedDict, hence the ignore.
    g.add_node(nodes.EXECUTE, nodes.execute_task, input_schema=nodes.TaskInput)  # type: ignore[call-overload]
    g.add_node(nodes.FINALIZE, nodes.finalize)

    g.add_edge(START, nodes.PLAN)
    g.add_conditional_edges(nodes.DISPATCH, nodes.route, [nodes.EXECUTE, nodes.FINALIZE])
    g.add_edge(nodes.EXECUTE, nodes.DISPATCH)
    g.add_edge(nodes.FINALIZE, END)
    return g


def compile_graph(checkpointer: BaseCheckpointSaver[Any] | None = None) -> SwarmGraph:
    return build_graph().compile(checkpointer=checkpointer, name="polymath-swarm")


def mermaid() -> str:
    """Mermaid source for the compiled graph (kept in docs/diagrams/swarm-graph.mmd)."""
    return build_graph().compile().get_graph().draw_mermaid()
