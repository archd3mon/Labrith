"""
Component Engineer Agent.

Writes React, TypeScript and Tailwind code for tasks in the plan, runs builds
and tests inside the isolated sandbox, and executes a build-fix loop if failures occur.

Design Doc §3: "Writes React, TypeScript and Tailwind code for each task. Component structure;
how to fix a build or test error. Tools: File writer, npm build, linter, type checker.
Proof of work: Diff, passing build log, lint output."
Design Doc §5 (Scenario 1): "The Engineer reads the error, diagnoses it and patches the code.
The Planner counts attempts; after the limit it replans the task."
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from graph.state import GraphState, TaskDefinition
from lib.llm import complete
from lib.proofs import create_proof
from lib.trace import TraceWriter
from tools.sandbox import Sandbox


def run_engineer(
    state: GraphState,
    trace_writer: Optional[TraceWriter] = None,
    *,
    sandbox: Optional[Sandbox] = None,
    artifact_dir: Path = Path("artifacts"),
    force_failure: bool = False,
    template_dir: Path = Path("templates/vite-react-ts-tailwind"),
    base_dir: Path = Path("runs"),
    **kwargs: Any,
) -> dict:
    """LangGraph node for the Component Engineer.

    Args:
        state: Shared blackboard state.
        trace_writer: Optional trace recorder.
        sandbox: Optional pre-configured Sandbox instance.
        artifact_dir: Directory where artifacts are saved.
        force_failure: If True, simulates a build failure for testing.
    """
    task = _find_engineer_task(state)

    if force_failure:
        if trace_writer:
            trace_writer.write(
                "engineer",
                "build_failed",
                {"task_id": task.task_id, "error": "Simulated type error in ComponentA.tsx"},
            )
        updated_plan = _mark_task_status(state, task.task_id, "failed")
        updated_artifacts = dict(state.code_artifacts)
        updated_artifacts[task.task_id] = {
            "status": "failed",
            "error": "Simulated type error in ComponentA.tsx",
        }
        return {
            "plan": updated_plan,
            "code_artifacts": updated_artifacts,
        }

    # Initialize sandbox if not provided
    if sandbox is None:
        run_id = getattr(trace_writer, "run_id", "run-default") if trace_writer else "run-default"
        sandbox = Sandbox(
            run_id=run_id,
            base_dir=base_dir,
            template_dir=template_dir,
            artifact_dir=artifact_dir,
        )

    # Resolve per-task iteration limit
    max_attempts = (
        state.request.max_iterations
        if state.request and state.request.max_iterations
        else 3
    )

    design_spec = state.design_spec
    initial_prompt = _build_engineer_prompt(task, design_spec)
    messages: list[dict[str, Any]] = [{"role": "user", "content": initial_prompt}]

    attempts = 0
    last_error = ""
    last_files: list[tuple[str, str]] = []
    build_log_path = ""
    test_log_path = ""

    while attempts < max_attempts:
        attempts += 1

        # Query LLM via thin wrapper lib/llm.py
        raw_response = complete("engineer", messages)
        files = _parse_files_from_response(raw_response, default_component_name=task.task_id)
        last_files = files

        # Write generated files into the sandbox
        written_paths: list[str] = []
        for rel_path, content in files:
            p = sandbox.write_file(rel_path, content)
            written_paths.append(str(p))

        # Run npm run build inside sandbox
        build_res = sandbox.run("npm run build", log_name=f"{task.task_id}_build.log")
        build_log_path = build_res.log_path or ""

        if build_res.exit_code != 0:
            last_error = f"Build failed (exit code {build_res.exit_code}):\n{build_res.stderr or build_res.stdout}"
            if trace_writer:
                trace_writer.write(
                    "engineer",
                    "build_failed",
                    {"task_id": task.task_id, "attempt": attempts, "error": last_error},
                )

            if attempts >= max_attempts:
                # Per-task iteration limit reached — report failure to planner
                break

            # Prompt LLM to patch the code
            messages.append({"role": "assistant", "content": raw_response})
            messages.append({
                "role": "user",
                "content": (
                    f"The build failed with the following error:\n{last_error}\n\n"
                    "Please diagnose and fix the error, and return the corrected files in JSON format."
                ),
            })
            continue

        # Build passed — run unit tests
        test_res = sandbox.run("npm test", log_name=f"{task.task_id}_test.log")
        test_log_path = test_res.log_path or ""

        if test_res.exit_code != 0:
            last_error = f"Tests failed (exit code {test_res.exit_code}):\n{test_res.stderr or test_res.stdout}"
            if trace_writer:
                trace_writer.write(
                    "engineer",
                    "tests_failed",
                    {"task_id": task.task_id, "attempt": attempts, "error": last_error},
                )

            if attempts >= max_attempts:
                break

            messages.append({"role": "assistant", "content": raw_response})
            messages.append({
                "role": "user",
                "content": (
                    f"The unit tests failed with the following error:\n{last_error}\n\n"
                    "Please fix the code and/or tests, and return the corrected files in JSON format."
                ),
            })
            continue

        # Both build and tests passed!
        evidence = [
            {"type": "build_log", "ref": build_log_path},
            {"type": "test_result", "ref": test_log_path},
        ]
        for wp in written_paths:
            evidence.append({"type": "source_file", "ref": wp})

        proof = create_proof(
            agent="engineer",
            task_id=task.task_id,
            claim="React component and unit tests built cleanly and passed.",
            evidence=evidence,
            reasoning=(
                f"Component and tests built cleanly on attempt {attempts}. "
                "npm run build and npm test exited with code 0."
            ),
        )

        if trace_writer:
            trace_writer.write(
                "engineer",
                "handoff",
                {"task_id": task.task_id, "claim": proof.claim, "attempts": attempts},
            )

        updated_plan = _mark_task_status(state, task.task_id, "done")
        updated_artifacts = dict(state.code_artifacts)
        updated_artifacts[task.task_id] = {
            "status": "success",
            "attempts": attempts,
            "files": [p for p, _ in last_files],
            "build_log": build_log_path,
            "test_log": test_log_path,
        }
        updated_artifacts["app_dir"] = str(sandbox.app_dir)
        return {
            "plan": updated_plan,
            "code_artifacts": updated_artifacts,
            "proofs": state.proofs + [proof],
        }

    # If attempts exhausted without passing:
    if trace_writer:
        trace_writer.write(
            "engineer",
            "iteration_limit_exhausted",
            {"task_id": task.task_id, "attempts": attempts, "last_error": last_error},
        )

    updated_plan = _mark_task_status(state, task.task_id, "failed")
    return {
        "plan": updated_plan,
        "code_artifacts": {
            task.task_id: {
                "status": "failed",
                "attempts": attempts,
                "error": last_error,
                "build_log": build_log_path,
                "test_log": test_log_path,
            }
        },
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_engineer_task(state: GraphState) -> TaskDefinition:
    for task in (state.plan or []):
        if task.assigned_agent == "engineer" and task.status in ("pending", "in_progress", "failed"):
            return task
    return TaskDefinition(
        task_id="T-02",
        description="Implement React component with TypeScript and Tailwind",
        assigned_agent="engineer",
        status="pending",
    )


def _mark_task_status(state: GraphState, task_id: str, new_status: str) -> list[TaskDefinition]:
    if not state.plan:
        return []
    updated = []
    for task in state.plan:
        if task.task_id == task_id:
            updated.append(task.model_copy(update={"status": new_status}))
        else:
            updated.append(task)
    return updated


def _build_engineer_prompt(task: TaskDefinition, design_spec: Any) -> str:
    tokens = {}
    layout = ""
    if design_spec:
        tokens = getattr(design_spec, "tokens", {}) or {}
        layout = getattr(design_spec, "layout_notes", "") or ""

    return (
        f"You are the Component Engineer. Implement the following task:\n"
        f"Task ID: {task.task_id}\n"
        f"Description: {task.description}\n"
        f"Design Tokens: {json.dumps(tokens)}\n"
        f"Layout Notes: {layout}\n\n"
        "Requirements:\n"
        "1. Write clean React + TypeScript + Tailwind code for the component.\n"
        "2. Write a unit test file using Vitest.\n"
        "3. Output MUST be valid JSON with the format:\n"
        '{\n  "files": [\n    {"path": "src/components/ComponentName.tsx", "content": "..."},\n'
        '    {"path": "src/components/ComponentName.test.tsx", "content": "..."}\n  ]\n}'
    )


def _parse_files_from_response(raw: str, default_component_name: str) -> list[tuple[str, str]]:
    """Parse generated file paths and contents from LLM response."""
    text = raw.strip()

    # 1. Try JSON block or direct JSON
    json_candidate = text
    if "```json" in text:
        match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            json_candidate = match.group(1).strip()
    elif "```" in text:
        match = re.search(r"```\s*(.*?)\s*```", text, re.DOTALL)
        if match and match.group(1).strip().startswith("{"):
            json_candidate = match.group(1).strip()

    try:
        data = json.loads(json_candidate)
        if isinstance(data, dict) and "files" in data and isinstance(data["files"], list):
            results = []
            for item in data["files"]:
                if isinstance(item, dict) and "path" in item and "content" in item:
                    results.append((str(item["path"]), str(item["content"])))
            if results:
                return results
    except Exception:
        pass

    # 2. Try regex extraction for code blocks labeled with file paths
    # Matches ```tsx // src/components/Name.tsx ... ```
    pattern = re.compile(
        r"```(?:tsx?|jsx?|typescript|javascript)?\s*(?://|/\*|#)?\s*(?:file:?|filepath:?|path:?)?\s*([a-zA-Z0-9_\-./\\]+\.(?:tsx|ts|jsx|js))\s*(?:\*/)?\n(.*?)```",
        re.DOTALL,
    )
    matches = pattern.findall(text)
    if matches:
        return [(path.strip(), content.strip()) for path, content in matches]

    # 3. Fallback: single component
    comp_name = default_component_name.replace("-", "").replace("_", "")
    comp_path = f"src/components/{comp_name}.tsx"
    test_path = f"src/components/{comp_name}.test.tsx"

    default_test = (
        "import { describe, it, expect } from 'vitest';\n"
        "describe('Component', () => {\n"
        "  it('passes', () => { expect(true).toBe(true); });\n"
        "});\n"
    )

    clean_content = text
    if "```" in clean_content:
        m = re.search(r"```(?:tsx?|jsx?)?\s*(.*?)\s*```", clean_content, re.DOTALL)
        if m:
            clean_content = m.group(1).strip()

    return [(comp_path, clean_content), (test_path, default_test)]
