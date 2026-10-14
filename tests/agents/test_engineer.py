"""
Tests for agents/engineer.py.

Covers:
1. Scripted fake LLM returning a type error on attempt 1 and a corrected version
   on attempt 2, verifying the build-fix loop, trace records, and proof attachment.
2. Stopping at the per-task iteration limit without looping indefinitely.
3. Successful build on the first attempt.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure repo root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest

from agents.engineer import run_engineer
from graph.state import DesignSpec, GraphState, TaskDefinition
from lib.llm import set_fake_llm_handler
from lib.models import InputRequest, TargetType
from lib.proofs import validate_proof
from lib.trace import TraceWriter, read_trace, filter_trace
from tools.sandbox import Sandbox


@pytest.fixture(autouse=True)
def _reset_fake():
    set_fake_llm_handler(None)
    yield
    set_fake_llm_handler(None)


@pytest.fixture
def sample_state(tmp_path: Path) -> GraphState:
    request = InputRequest(
        brief="Support dashboard",
        api_spec_url="https://example.com/api.json",
        target=TargetType.DASHBOARD,
        max_iterations=3,
    )
    plan = [
        TaskDefinition(
            task_id="T-01",
            description="Design layout",
            assigned_agent="designer",
            status="done",
        ),
        TaskDefinition(
            task_id="T-02",
            description="Implement UserProfile component",
            assigned_agent="engineer",
            status="pending",
        ),
    ]
    design_spec = DesignSpec(
        tokens={"color_primary": "#3B82F6"},
        component_inventory={"UserProfile": ["Avatar", "UserDetails"]},
        layout_notes="Card layout",
    )
    return GraphState(request=request, plan=plan, design_spec=design_spec)


@pytest.fixture
def real_sandbox(tmp_path: Path) -> Sandbox:
    template_dir = Path("templates/vite-react-ts-tailwind")
    return Sandbox(
        run_id="run-engineer-test",
        base_dir=tmp_path / "runs",
        template_dir=template_dir,
        artifact_dir=tmp_path / "artifacts",
    )


class TestEngineerBuildFixLoop:
    def test_build_fix_loop_success(
        self,
        sample_state: GraphState,
        real_sandbox: Sandbox,
        tmp_path: Path,
    ):
        """Simulate a TypeScript error on attempt 1, followed by a fix on attempt 2."""
        trace_path = tmp_path / "trace.jsonl"
        trace_writer = TraceWriter(trace_path, run_id="run-engineer-test")

        # Broken code: string assigned to number (TS2322)
        broken_response = json.dumps({
            "files": [
                {
                    "path": "src/components/UserProfile.tsx",
                    "content": (
                        "export function UserProfile() {\n"
                        "  const age: number = 'thirty'; // Type error\n"
                        "  return <div className=\"p-4\">{age}</div>;\n"
                        "}\n"
                        "export default UserProfile;\n"
                    ),
                },
                {
                    "path": "src/components/UserProfile.test.tsx",
                    "content": (
                        "import { describe, it, expect } from 'vitest';\n"
                        "describe('UserProfile', () => {\n"
                        "  it('renders', () => { expect(true).toBe(true); });\n"
                        "});\n"
                    ),
                },
            ]
        })

        # Fixed code: valid TypeScript
        fixed_response = json.dumps({
            "files": [
                {
                    "path": "src/components/UserProfile.tsx",
                    "content": (
                        "export function UserProfile() {\n"
                        "  const age: number = 30;\n"
                        "  return <div className=\"p-4\">{age}</div>;\n"
                        "}\n"
                        "export default UserProfile;\n"
                    ),
                },
                {
                    "path": "src/components/UserProfile.test.tsx",
                    "content": (
                        "import { describe, it, expect } from 'vitest';\n"
                        "describe('UserProfile', () => {\n"
                        "  it('renders', () => { expect(true).toBe(true); });\n"
                        "});\n"
                    ),
                },
            ]
        })

        call_count = 0

        def scripted_fake(agent_name: str, messages: list[dict], **kwargs) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return broken_response
            # Verify that subsequent prompt includes build error feedback
            last_msg = messages[-1]["content"]
            assert "The build failed" in last_msg or "error" in last_msg.lower()
            return fixed_response

        set_fake_llm_handler(scripted_fake)

        result = run_engineer(
            sample_state,
            trace_writer=trace_writer,
            sandbox=real_sandbox,
            artifact_dir=real_sandbox.artifact_dir,
        )

        # 1. State update assertions
        assert "code_artifacts" in result
        art = result["code_artifacts"]["T-02"]
        assert art["status"] == "success"
        assert art["attempts"] == 2
        assert "build_log" in art
        assert Path(art["build_log"]).exists()

        # 2. Plan was updated to 'done'
        assert "plan" in result
        updated_task = next(t for t in result["plan"] if t.task_id == "T-02")
        assert updated_task.status == "done"

        # 3. Proof record is valid and attached
        assert "proofs" in result
        assert len(result["proofs"]) == 1
        proof = result["proofs"][0]
        assert proof.agent.value == "engineer"
        assert proof.task_id == "T-02"

        is_valid, errors = validate_proof(proof)
        assert is_valid, f"Proof invalid: {errors}"

        # 4. Trace assertions
        trace_entries = read_trace(trace_path)
        fail_entries = filter_trace(trace_entries, event_type="build_failed")
        handoff_entries = filter_trace(trace_entries, event_type="handoff")

        assert len(fail_entries) == 1, "Expected 1 build_failed entry in trace"
        assert fail_entries[0].payload["attempt"] == 1
        assert len(handoff_entries) == 1, "Expected 1 handoff entry in trace"
        assert handoff_entries[0].payload["attempts"] == 2

    def test_iteration_limit_exhausted(
        self,
        sample_state: GraphState,
        real_sandbox: Sandbox,
        tmp_path: Path,
    ):
        """Simulate persistent errors: engineer stops at per-task limit."""
        trace_path = tmp_path / "trace.jsonl"
        trace_writer = TraceWriter(trace_path, run_id="run-engineer-test")

        # Always broken
        broken_response = json.dumps({
            "files": [
                {
                    "path": "src/components/Broken.tsx",
                    "content": "export const Broken: number = 'never_fixed';",
                }
            ]
        })

        call_count = 0

        def scripted_fake(agent_name: str, messages: list[dict], **kwargs) -> str:
            nonlocal call_count
            call_count += 1
            return broken_response

        set_fake_llm_handler(scripted_fake)

        # Limit to 2 iterations
        sample_state.request.max_iterations = 2

        result = run_engineer(
            sample_state,
            trace_writer=trace_writer,
            sandbox=real_sandbox,
            artifact_dir=real_sandbox.artifact_dir,
        )

        # Result reports failure to planner
        assert "code_artifacts" in result
        art = result["code_artifacts"]["T-02"]
        assert art["status"] == "failed"
        assert art["attempts"] == 2
        assert "proofs" not in result

        # Plan task marked failed
        updated_task = next(t for t in result["plan"] if t.task_id == "T-02")
        assert updated_task.status == "failed"

        # Trace recorded limit exhaustion
        trace_entries = read_trace(trace_path)
        exhaust_entries = filter_trace(trace_entries, event_type="iteration_limit_exhausted")
        assert len(exhaust_entries) == 1
        assert exhaust_entries[0].payload["attempts"] == 2
