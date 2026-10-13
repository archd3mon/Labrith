# FrontForge Build Playbook

How to build FrontForge in your IDE with an AI coding assistant, one verified slice at a time.
Each slice = one branch, one pull request, tests passing, proof of work attached, owner can explain every line.

---

## Part 1: One-time setup (Member 1, then everyone pulls)

1. Create the GitHub repo (public, or add the evaluation account). Each member adds their GitHub username on the Exam Studio Project Artifacts page.
2. Clone it. Create the folders: `agents graph tools lib schemas api web tests examples docs`.
3. Export the Design Document to `docs/DESIGN.md` (Markdown). Put `AGENTS.md` in the repo root. If your IDE uses its own rules file (e.g. `.cursorrules`, `CLAUDE.md`), add one line pointing to AGENTS.md.
4. Add `.gitignore` (Python, node, `.env`, `artifacts/`, `runs/`), `.env.example`, a stub `README.md`.
5. Make the first commit: "Add design doc, agent rules and repo skeleton". Push. Branch protection on `main`: require a PR and one review.
6. Everyone: create a virtualenv, install dependencies as they are added (`pip install -r requirements.txt`), confirm `pytest` runs (even with zero tests).

## Part 2: The loop for every slice

1. `git checkout -b feat/<slice-name>`
2. Open a fresh IDE chat. Paste the slice prompt below (it starts by making the assistant read AGENTS.md and the design doc).
3. Ask the assistant for a short plan first; approve or correct it before it writes code.
4. Let it implement. Read every changed file. If you can't explain a part, ask the assistant to explain it or simplify it.
5. Run `pytest` yourself. Run the feature once and capture proof (log, trace line, screenshot) into `docs/evidence/<slice-name>/`.
6. Commit in small steps with real messages (not one big commit). Push. Open a PR with: summary, test output, proof, any design deviations.
7. A teammate reviews and comments, then merges. Update `docs/DESIGN.md` in the same PR if behaviour changed.
8. Tick the slice off in the evidence checklist (Design Doc, Section 12).

Tips: use a new chat per slice to keep context clean. If the assistant goes outside the named files, reject the change. Spread work across many days: that is what the individual-contribution marks measure.

---

## Part 3: Slice prompts

Replace anything in [brackets]. The "Done when" line is mandatory in every prompt.

### Slice 0: Foundations (Member 1)
Branch: `feat/foundations`

```text
Read AGENTS.md and docs/DESIGN.md (sections 3, 6, 8, 9, 11) first.

Task: implement the foundations, nothing else.
1. schemas/input.schema.json, schemas/output.schema.json, schemas/proof.schema.json matching the design doc, plus pydantic models in lib/models.py and a loader that validates a request against input.schema.json with clear error messages.
2. graph/state.py: the shared state (pydantic) with fields for: request, plan/tasks, design_spec, code_artifacts, integration_report, qa_results, audit_report, proofs[], iteration counters per task, status, unresolved[].
3. lib/proofs.py: create_proof(...) and validate_proof(...). validate_proof rejects records missing agent, task_id, claim, evidence, reasoning or timestamp, and checks evidence refs exist on disk.
4. lib/trace.py: append-only JSONL trace writer (run_id, seq, timestamp, agent, event_type, payload). Provide read helpers. No function may modify or delete existing lines.
5. lib/llm.py: a thin wrapper with one function complete(agent_name, messages, **opts) that reads the model for each agent from config, with timeout and retry. Provider details isolated here.
6. examples/sample_input.json valid against the schema.

Constraints: touch only these files and tests/. No agents yet.
Done when: pytest passes with tests for schema validation (valid and invalid inputs), proof validation (accept and reject cases), trace append-only behaviour, and the llm wrapper using a fake provider. Show pytest output and a sample trace file produced by a test run.
```

### Slice 1: Graph skeleton with stub agents and routing (Member 1)
Branch: `feat/graph-skeleton`

```text
Read AGENTS.md and docs/DESIGN.md (sections 3, 4, 5, 6) first.

Task: build the LangGraph graph with six STUB agents (planner, designer, engineer, integration, qa, critic) in agents/*.py and the graph in graph/graph.py with routing in graph/routing.py.
- The planner is the supervisor: after every worker returns, control goes back to the planner, which chooses the next agent from state. Provide planner.decide(state) -> next_agent | "finish" | "escalate".
- Stubs return a valid proof-of-work record and write their output to state. The planner must reject any handoff whose proof fails validate_proof and send it back.
- Enforce iteration limits per task and per run (default 3 and 15, configurable). When exceeded: planner escalates, adds the issue to state.unresolved, run ends with status "partial".
- Every handoff and routing decision is written to the trace via lib/trace.py.
- Planner decisions in this slice may use a scripted fake LLM; structure the code so the real LLM call is a drop-in replacement.

Constraints: no real LLM calls, no tools yet. Do not hard-code a fixed agent order; routing must depend on state.
Done when: pytest passes with tests/routing/ covering: normal completion; a stub that returns a failing result causing a reroute; a handoff without proof being rejected; the iteration limit triggering escalation and status "partial". Show pytest output and one trace file from a scripted run.
```

### Slice 2: Sandbox and Engineer build-fix loop (Member 2)
Branch: `feat/engineer-sandbox`

```text
Read AGENTS.md and docs/DESIGN.md (sections 3, 5, 6, 10) first.

Task A: tools/sandbox.py. Create an isolated working directory per run (runs/<run_id>/app), scaffold a Vite + React + TypeScript + Tailwind project from a template folder, and expose: write_file, read_file, run(cmd, timeout) which executes inside that directory only and returns exit code, stdout, stderr. Refuse paths that escape the directory. Save command output to artifacts/ so it can be cited as evidence.

Task B: agents/engineer.py. Given a task from the plan and the design_spec in state, the engineer (via lib/llm.py) writes the React component and a unit test file, runs `npm run build` and the tests in the sandbox, and if the build fails it reads the error and patches the code. It records each attempt. After the per-task limit it stops and reports failure to the planner instead of looping. Output must include a proof record citing the build log and test output paths.

Constraints: touch tools/sandbox.py, agents/engineer.py, a template folder, tests/. LLM calls via lib/llm.py only.
Done when: pytest passes using a scripted fake LLM that first returns code with a type error and then a corrected version, proving the fix loop; sandbox path-escape test passes; one real run (with the real model) builds a simple component and its log is saved under docs/evidence/engineer-sandbox/. Show pytest output.
```

### Slice 3: Planner with real reasoning (Member 1)
Branch: `feat/planner-llm`

```text
Read AGENTS.md and docs/DESIGN.md (sections 3, 4, 5) first.

Task: replace the planner stub with a real LLM-driven planner in agents/planner.py.
1. plan(): parse the OpenAPI spec (tools/openapi.py: list endpoints, schemas) and the brief; produce pages, user flows and an ordered task list with required_flows. Output validated against a pydantic model.
2. decide(state): given state (task statuses, proofs, failures, iteration counts), the LLM chooses the next agent and gives a short reasoning note; deterministic guards still apply (iteration limits, proof validation, finish only when all gates pass).
3. replan(state): when a task keeps failing, produce a revised plan (smaller component, different approach) and log why.
Every decision and reasoning note goes to the trace.

Constraints: keep guards in graph/routing.py; the LLM proposes, guards dispose. No fixed order.
Done when: pytest passes with scripted-LLM tests for plan parsing, decide() choosing different next agents for different states, and replan() triggering after repeated failure. Run once against examples/sample_input.json with the real model and save the plan and trace excerpt to docs/evidence/planner-llm/.
```

### Slice 4: Designer (Member 2)
Branch: `feat/designer`

```text
Read AGENTS.md and docs/DESIGN.md first.

Task: implement agents/designer.py. From the plan and style_hints it produces a design_spec JSON (design tokens: colours, spacing, type scale; component inventory per page; layout notes) validated by a pydantic model. It must also handle revision requests from the critic in state: given a list of findings (e.g. contrast failures with colour pairs), it revises the tokens and records which finding each change resolves. Use a vision-capable call via lib/llm.py when a screenshot path is provided.

Constraints: designer does not write application code.
Done when: pytest passes for: initial spec generation (scripted LLM), spec validation, and a revision test where a contrast finding results in changed tokens plus a rationale entry. Proof records cite the spec file. Show pytest output.
```

### Slice 5: QA agent with Playwright (Member 3)
Branch: `feat/qa-playwright`

```text
Read AGENTS.md and docs/DESIGN.md (sections 3, 5, 6) first.

Task: tools/playwright_runner.py and agents/qa.py.
- Runner: start the generated app (vite preview or dev) from the sandbox, run a flow in headless Chromium, capture screenshots, console errors and a pass/fail result with step details. Save to artifacts/.
- QA agent: from the planner's required_flows, generate Playwright flow scripts via the LLM, run them, and for each failure classify it (code_bug, integration_bug, flaky) with evidence. Retry a failed flow once to detect flakiness. Output a proof record per flow citing results, screenshots and console log.
- QA is the only agent that may declare a flow passed or failed.

Done when: pytest passes with a tiny fixture app (one page with a working and a deliberately broken flow): passing flow reported pass, broken flow reported fail with screenshot and classification. Save sample screenshots under docs/evidence/qa-playwright/. Show pytest output.
```

### Slice 6: Critic with axe and Lighthouse (Member 3)
Branch: `feat/critic`

```text
Read AGENTS.md and docs/DESIGN.md (sections 3, 5, 6) first.

Task: tools/axe_runner.py, tools/lighthouse_runner.py, agents/critic.py.
- Runners return structured findings (axe violations with impact and nodes; Lighthouse scores).
- Critic: combines the audit results and a vision review of screenshots; decides accept or reject. On reject it emits revision requests, each naming the target agent (designer or engineer), the concrete finding and the evidence. It applies the accessibility gate (no critical or serious violations) and the quality gate (configurable Lighthouse thresholds).
- The critic can reject a build even when QA passed (conflict case from design Section 5, scenario 5).

Done when: pytest passes using a fixture page with a known contrast violation: critic rejects and targets the designer with the failing colour pair; after the fixture is fixed, critic accepts. Save the audit report under docs/evidence/critic/. Show pytest output.
```

### Slice 7: Integration agent (Member 3)
Branch: `feat/integration-agent`

```text
Read AGENTS.md and docs/DESIGN.md (sections 3, 5, 6) first.

Task: tools/mock_server.py and agents/integration.py.
- Mock server: serve responses for the spec's endpoints (examples from the spec or generated), with an option to return a deliberately mismatched response.
- Integration agent: generate a typed API client and loading/error states for the components that call the API, call the (mock or real) API, compare actual responses with the spec, and report mismatches with evidence. Decide whether to adapt the types or ask the planner to involve the engineer. Output a proof record citing request/response logs and the mismatch report.

Done when: pytest passes: matching responses produce a clean report; a mismatched response produces a documented mismatch and a request to the planner. Save logs under docs/evidence/integration/. Show pytest output.
```

### Slice 8: Wire everything and run end to end (Member 1, all review)
Branch: `feat/end-to-end`

```text
Read AGENTS.md and docs/DESIGN.md first.

Task: connect all real agents in graph/graph.py, implement the five gates (build, tests, accessibility, quality, integration) in graph/gates.py, and produce quality_report.json and trace.jsonl per run matching schemas/output.schema.json. Add the e2e test that runs examples/sample_input.json against the demo backend with the real model.

Constraints: do not change agent behaviour except to fix integration bugs; list any such fixes in your summary.
Done when: the e2e run finishes with status "accepted" or an honest "partial", the trace contains handoffs among all six agents, and docs/evidence/end-to-end/ holds the raw trace and report (unedited). Show pytest output and the gate results.
```

### Slice 9: API, control UI, deploy (Member 1 with Member 2)
Branch: `feat/api-ui-deploy`

```text
Read AGENTS.md and docs/DESIGN.md first.

Task: api/main.py (FastAPI): POST /runs (validates input, starts a run), GET /runs/{id} (status and report), GET /runs/{id}/events (server-sent events streaming trace events). web/: a React control UI with an input form, a live agent activity feed, and the final preview link and quality report. Add a Dockerfile or deploy config and update the README with setup, running tests, and reproducing a demo run.

Done when: pytest passes for the API (invalid input returns a clear 4xx and starts no agents), the UI shows live events during a run, and the app is deployed at a stable URL. Show test output and the deployed URL.
```

---

## Part 4: Robustness pass (everyone, before demo)

Prompt for each owner on their agents:

```text
Read AGENTS.md. For [agent/tool], add tests and handling for: tool timeout, tool crash, malformed LLM output, empty or invalid spec. The system must degrade and report (gate marked unverified, issue listed in unresolved), never crash. Done when: new pytest cases pass and a scripted failure run shows the graceful path in the trace.
```

## Part 5: Before submission

- [ ] Architecture diagram in repo matches the code and the deployed system
- [ ] `docs/DESIGN.md`, schemas, sample input/output and trace all describe the same six agents
- [ ] Real trace from a captured run, unedited, showing the six adaptation scenarios
- [ ] All tests green; test output saved
- [ ] README complete; no secrets in history
- [ ] Commits from all three members across many days; PRs reviewed
- [ ] Deployment live and checked; demo video recorded as backup
- [ ] Every member can explain their agents without notes
