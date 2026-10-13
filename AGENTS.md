# AGENTS.md — rules for any AI coding assistant working on FrontForge

Read this file and `docs/DESIGN.md` before every task. If a request conflicts with them, stop and say so instead of improvising.

## Project in one line
FrontForge is a multi-agent system (LangGraph, Python) that acts as a frontend team: given a brief and an OpenAPI spec it plans, designs, builds, integrates, tests and reviews a React + TypeScript + Tailwind app and delivers it with a quality report.

## The six agents (do not add, merge or rename without updating docs/DESIGN.md)
planner (supervisor), designer, engineer, integration, qa, critic.

## Architecture rules
- Pattern: supervisor over a shared state (blackboard). Workers never call each other directly; they read and write the shared state and the planner routes.
- Routing decisions come from the planner reasoning over state (LLM-driven, with hard limits), not from a fixed hard-coded sequence.
- Every agent output MUST carry a proof-of-work record (schemas/proof.schema.json): agent, task_id, claim, evidence[], reasoning, timestamp. The planner rejects outputs without one.
- Every message, routing decision and proof record is appended to the trace by lib/trace.py. Never write, edit or "tidy" trace files by hand or in tests of real runs.
- All LLM calls go through lib/llm.py. No direct provider SDK calls inside agents. Model choice is per agent via config.
- Iteration limits are enforced in graph/routing.py. When exhausted, the planner escalates and records the issue as unresolved; it never loops forever or hides failures.

## Repo layout (keep it)
agents/  graph/  tools/  lib/  schemas/  api/  web/  tests/  examples/  docs/

## Engineering rules
- Python 3.11+, type hints, pydantic models for state and schemas, pytest for tests.
- Write tests WITH each feature, in the same change. No test, no merge.
- Unit tests mock the LLM with a scripted fake (tests/fakes.py). Only the e2e test uses a real model.
- Never commit secrets. Config via .env; keep .env.example current.
- Small, focused changes. Touch only the files named in the task. Do not refactor unrelated code.
- If behaviour, schemas or the agent flow change, update docs/DESIGN.md in the same change.
- Commit messages: imperative, specific (e.g. "Add engineer build-fix loop with retry limit").

## Definition of done (every task)
1. Code implemented in the named files only.
2. Tests added and passing; paste the pytest output.
3. A proof-of-work excerpt shown (log, trace line or screenshot path) demonstrating the feature running.
4. Docs updated if anything in the design changed.
5. Short summary: what changed, what was NOT done, any deviation from the design.

## Never
- Never fabricate or hand-edit execution traces or test output.
- Never make an agent a fixed pipeline step that always fires in the same order.
- Never silently change the design; flag it instead.
