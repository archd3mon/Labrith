"""
LangGraph graph definition — supervisor over a shared blackboard.

Topology (Design Doc §4):
  START -> planner
  planner --conditional--> {designer, engineer, integration, qa, critic, END}
  designer  -> planner
  engineer  -> planner
  integration -> planner
  qa        -> planner
  critic    -> planner

Workers NEVER call each other directly.  Every handoff goes back to the
planner, which reads the state and routes the next step.

Public API:
    create_graph(trace_writer, artifact_dir, agent_overrides) -> CompiledGraph
    run_graph(request, trace_writer, artifact_dir, agent_overrides) -> GraphState
"""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Any, Callable, Optional

from langgraph.graph import END, START, StateGraph

from agents.critic import run_critic
from agents.designer import run_designer
from agents.engineer import run_engineer
from agents.integration import run_integration
from agents.planner import run_planner
from agents.qa import run_qa
from graph.routing import route_decision
from graph.state import GraphState
from lib.models import InputRequest
from lib.trace import TraceWriter


# ---------------------------------------------------------------------------
# Node wrappers — inject trace_writer and artifact_dir transparently
# ---------------------------------------------------------------------------

def _make_planner_node(
    trace_writer: Optional[TraceWriter],
) -> Callable[[GraphState], dict]:
    def node(state: GraphState) -> dict:
        return run_planner(state, trace_writer=trace_writer)
    node.__name__ = "planner"
    return node


def _make_worker_node(
    fn: Callable,
    trace_writer: Optional[TraceWriter],
    artifact_dir: Path,
    extra_kwargs: dict[str, Any],
) -> Callable[[GraphState], dict]:
    def node(state: GraphState) -> dict:
        return fn(state, trace_writer=trace_writer, artifact_dir=artifact_dir, **extra_kwargs)
    node.__name__ = fn.__name__
    return node


# ---------------------------------------------------------------------------
# Graph factory
# ---------------------------------------------------------------------------

def create_graph(
    trace_writer: Optional[TraceWriter] = None,
    artifact_dir: Path = Path("artifacts"),
    agent_overrides: Optional[dict[str, dict[str, Any]]] = None,
) -> Any:  # CompiledStateGraph
    """Build and compile the LangGraph supervisor graph.

    Args:
        trace_writer:    TraceWriter instance; if None no trace is written.
        artifact_dir:    Base directory for agent artifact output.
        agent_overrides: Per-agent keyword arguments to override stub defaults.
                         e.g. {"engineer": {"force_failure": True}}
                         Used in tests to simulate failures.

    Returns:
        A compiled LangGraph application.
    """
    overrides = agent_overrides or {}

    builder = StateGraph(GraphState)

    # ---- Planner (supervisor) node ----------------------------------------
    builder.add_node("planner", _make_planner_node(trace_writer))

    # ---- Worker nodes -------------------------------------------------------
    worker_fns = {
        "designer": run_designer,
        "engineer": run_engineer,
        "integration": run_integration,
        "qa": run_qa,
        "critic": run_critic,
    }
    for name, fn in worker_fns.items():
        extra = overrides.get(name, {})
        builder.add_node(
            name,
            _make_worker_node(fn, trace_writer, artifact_dir, extra),
        )

    # ---- Edges --------------------------------------------------------------
    # Entry: START -> planner
    builder.add_edge(START, "planner")

    # Planner -> worker or END (conditional)
    builder.add_conditional_edges(
        "planner",
        route_decision,
        {
            "designer": "designer",
            "engineer": "engineer",
            "integration": "integration",
            "qa": "qa",
            "critic": "critic",
            "finish": END,
            "escalate": END,
        },
    )

    # Every worker -> planner (supervisor pattern; workers never call each other)
    for name in worker_fns:
        builder.add_edge(name, "planner")

    return builder.compile()


# ---------------------------------------------------------------------------
# Convenience runner
# ---------------------------------------------------------------------------

def run_graph(
    request: InputRequest,
    trace_writer: Optional[TraceWriter] = None,
    artifact_dir: Path = Path("artifacts"),
    agent_overrides: Optional[dict[str, dict[str, Any]]] = None,
) -> GraphState:
    """Create and run the graph for the given request.

    Returns:
        The final GraphState after the run completes.
    """
    app = create_graph(
        trace_writer=trace_writer,
        artifact_dir=artifact_dir,
        agent_overrides=agent_overrides,
    )
    initial_state = GraphState(request=request)
    final_state_dict = app.invoke(initial_state)
    # LangGraph returns a dict when the schema is a Pydantic model
    if isinstance(final_state_dict, dict):
        return GraphState(**final_state_dict)
    return final_state_dict
