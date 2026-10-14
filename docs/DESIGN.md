# Labrith Design Document

Oct 13, 2026 · @Jayant

Labrith is a system of six cooperating AI agents that behaves like a frontend team: given a product brief and an OpenAPI description of a backend, it plans, designs, builds, integrates, tests and reviews a React web interface, and delivers a deployed app with a quality report.

## 1. System overview

**Problem.** AI backends and agents ship faster than their interfaces. Single-prompt UI generators produce code in one pass, with no review, no real browser testing and no accessibility checks, and they give no feedback when the output breaks.

**Solution.** Real frontend work is a team process: plan, design, implement, integrate, test, review, fix. Labrith reproduces that loop. Each agent has one role, makes its own LLM-driven decisions, uses tools, and can send work back to another agent. Output is accepted only when evidence shows it was built, run and checked.

**Target user.** Solo AI developers, hackathon teams and early-stage startups with a working backend but no frontend capacity.

**Scope (v1).** React, TypeScript and Tailwind web apps (dashboards and forms) over an OpenAPI-described backend. Out of scope for v1: native mobile apps, other frameworks, and backend generation.

**Why more than one agent.** The roles have conflicting incentives and different tools. The agent that writes code should not be the one that judges it. A separate QA agent running a real browser and a separate critic applying accessibility and design standards catch failures the author misses, and the disagreements between them are what force revision.

## 2. Architecture and data flow

&#91;embedded content: architecture · 6 agents, 1 shared state\]

The Planner receives the validated input and writes a task plan to the shared state. Workers never call each other directly: each reads the state, does its work with its own tools, and writes back its output with a proof-of-work record. The Planner reads every handoff and decides the next step, which is what allows rerouting and replanning. Arrows between the state and the workers run both ways because every worker both reads and writes. When all five gates in Section 6 pass, the Planner assembles the output.

## 3. Agent roles and responsibilities

Six agents, each with one responsibility and its own tools. Agent names here are the names used in code, the trace and the presentation.

| Agent | Responsibility | Decides | Tools | Proof of work it must attach |
| --- | --- | --- | --- | --- |
| Planner (supervisor) | Turns brief and API spec into pages, flows and a task list; routes work; replans on failure | Which agent runs next, when to replan, when to stop or escalate | Spec parser, shared state, task queue | Task plan, routing decision with reason |
| Design Architect | Chooses layout, design tokens and component inventory per page | Palette, spacing, component set; whether to revise after critique | Token generator, screenshot viewer (vision model) | Design spec JSON, rationale for each critic revision |
| Component Engineer | Writes React, TypeScript and Tailwind code for each task | Component structure; how to fix a build or test error | File writer, `npm build`, linter, type checker | Diff, passing build log, lint output |
| Integration Agent | Binds components to the real API with types, loading and error states | How to map responses to UI; how to handle spec mismatches | OpenAPI reader, mock server, HTTP client | Generated API client, request and response log, mismatch report |
| QA Agent | Runs the app in a headless browser and exercises user flows | Which flows to test; whether a failure is a real bug | Playwright, screenshots, console log capture | Test results, screenshots, console log |
| Accessibility and Design Critic | Audits WCAG compliance and visual and UX quality; sends concrete revision requests | Accept or reject a build; which agent must fix what | axe-core, Lighthouse, vision model | Audit report with scores and itemised findings |

Responsibilities do not overlap: only the Engineer writes application code, only the QA Agent declares a flow passed or failed, and only the Critic can accept or reject a build for quality. The Planner never writes code or judges quality; it routes.

## 4. Orchestration pattern

**Pattern: supervisor (orchestrator-worker) over a shared blackboard.** The Planner is the supervisor. All agents read from and write to one shared state object (the blackboard), and the Planner chooses the next step from that state. Workers do not call each other directly; they post results and requests to the state, which keeps every handoff visible in the trace.

**Why this pattern.**

- Frontend work has dependencies (design before code, build before test) but also frequent backward edges (a failed test returns to the Engineer). A supervisor can route in both directions; a fixed pipeline cannot.
- A shared blackboard lets the Critic and the QA Agent see the same artifacts, so disagreements are about the same evidence.
- One central router makes loop limits and escalation rules easy to enforce and to demonstrate in the trace.

**Why not peer-to-peer.** Free-form agent chatter is harder to bound, harder to trace and harder to test. A supervisor with explicit state transitions gives the same adaptiveness with auditable control.

**Termination.** A run ends when the Critic accepts the build and QA reports all required flows passing, or when the iteration budget is exhausted. In the second case the Planner escalates: the report lists unresolved issues rather than hiding them.

## 5. Agentic behaviour: adaptation and conflict resolution

This is what separates Labrith from a workflow. In each scenario below, the next step depends on what an agent discovered, and an LLM-driven agent makes the decision. Each scenario must appear in the captured execution trace of the demo run.

| # | Trigger | What happens | Agents involved |
| --- | --- | --- | --- |
| 1 | Build fails | The Engineer reads the error, diagnoses it and patches the code. The Planner counts attempts; after the limit it replans the task (smaller component, different approach) | Engineer, Planner |
| 2 | Critic rejects a design for low contrast | The Critic posts a revision request with the failing pairs; the Designer proposes new tokens; the Critic re-audits | Critic, Designer |
| 3 | API response differs from the OpenAPI spec | The Integration Agent reports the mismatch with evidence; the Planner decides to adapt the types or ask the Engineer to handle the variant, and updates the plan | Integration, Planner, Engineer |
| 4 | QA flow fails in the browser | QA attaches screenshot and console log and classifies the failure (code bug, integration bug, test flake); the Planner routes to the matching agent | QA, Planner |
| 5 | Critic and QA disagree (flow passes but the UI is inaccessible) | The Planner holds acceptance until both sign off; the Critic's accessibility finding takes priority and returns to the Engineer | Critic, QA, Planner |
| 6 | Iteration budget exhausted | The Planner stops, marks the issue unresolved and lists it in the quality report | Planner |

**Memory.** Within a run, the shared state keeps the design tokens, past errors and the fix that worked, so an agent does not repeat a failed approach. Cross-run memory is out of scope for v1.

**Planning and reasoning.** The Planner produces an explicit task plan and revises it when evidence changes. Every agent records a short reasoning note with each decision; these notes appear in the trace.

## 6. Proof-of-work and verification gates

**Rule: no claim without evidence.** An agent's output is not accepted into the shared state unless it carries a proof-of-work record. The Planner rejects any handoff that arrives without one and sends it back. This design rule serves two purposes: it makes the product trustworthy, and it produces the verifiable trace that CA3 evaluators ask for.

**Proof-of-work record (attached to every agent output):**

```json
{
  "agent": "qa",
  "task_id": "T-07",
  "claim": "Login flow passes",
  "evidence": [
    {"type": "test_result", "ref": "artifacts/T-07/playwright.json"},
    {"type": "screenshot", "ref": "artifacts/T-07/login.png"},
    {"type": "log", "ref": "artifacts/T-07/console.log"}
  ],
  "reasoning": "Submitted valid and invalid credentials; error state rendered for invalid.",
  "timestamp": "2026-10-20T10:42:11Z"
}
```

**Verification gates a build must pass before the Planner accepts it:**

1. **Build gate:** `npm run build` and the type checker exit cleanly (Engineer evidence: build log).
2. **Test gate:** the generated app's own unit tests pass, and every required user flow passes in Playwright (QA evidence: results, screenshots).
3. **Accessibility gate:** no critical or serious axe-core violations (Critic evidence: audit report).
4. **Quality gate:** Lighthouse performance and accessibility above the configured threshold (Critic evidence: scores).
5. **Integration gate:** every API call in the generated client matches the spec, or each mismatch is documented (Integration evidence: mismatch report).

**Tests as a product requirement.** The Engineer must generate unit tests alongside each component, and the QA Agent must generate end-to-end flows from the Planner's user-flow list. A task with no tests is rejected by the Planner.

**Trace integrity.** All agent messages, routing decisions and proof-of-work records are written to an append-only trace file by the system itself, never by hand. The captured demo trace is submitted unedited.

## 7. Technology and framework choices

| Layer | Choice | Justification |
| --- | --- | --- |
| Agent orchestration | LangGraph (Python) | Explicit graph with conditional edges and shared state fits the supervisor pattern; built-in checkpointing and streaming give a natural trace |
| LLM access | One provider client behind a thin wrapper; model chosen per agent | Stronger model for Planner and Engineer, cheaper model for QA and Critic summaries; the wrapper lets us swap models without touching agent logic |
| Vision | Vision-capable model on screenshots | Designer and Critic judge the rendered result, not just the code |
| Backend service | FastAPI | Async, streams agent events to the UI, simple to deploy |
| Control UI | React and Tailwind | Lets the demo show agents working live and the final result side by side |
| Generated app stack | React, TypeScript, Tailwind, Vite | Common, well-supported target; fast builds keep the loop short |
| Browser testing | Playwright | Real browser flows, screenshots and console capture in one tool |
| Accessibility and quality | axe-core, Lighthouse | Standard tools behind the accessibility and quality gates |
| Sandbox | Isolated working directory per run (container if time allows) | Generated code is executed, so it must not touch the host |
| Tests (system) | pytest | Unit and integration tests for the Python system |
| Deployment | Frontend on Vercel, backend on a free-tier host | Early deployment keeps the live demo URL stable |

We use a framework (LangGraph) rather than a custom loop because state, conditional routing and tracing are exactly what it provides; reinventing them would add risk without adding marks.

## 8. Input definition

The system accepts one JSON request describing what to build and where the backend lives.

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `brief` | string | yes | Plain-language description of the product and its users |
| `api_spec_url` | string (URL) or inline OpenAPI 3 JSON | yes | The backend's API description |
| `target` | enum: `dashboard`, `form_app`, `mixed` | yes | Kind of interface to build |
| `style_hints` | array of strings | no | For example `minimal`, `dark`, `data-dense` |
| `required_flows` | array of strings | no | User flows that must pass QA; if absent the Planner derives them |
| `max_iterations` | integer | no | Iteration budget per task (default 3) |

**Sample input** (illustrative; replace with the real demo backend's spec before submission):

```json
{
  "brief": "A support dashboard where agents view open tickets, filter by priority, open a ticket to read its history, and reply.",
  "api_spec_url": "https://demo-backend.example.com/openapi.json",
  "target": "dashboard",
  "style_hints": ["minimal", "data-dense"],
  "required_flows": ["list tickets", "filter by priority", "open ticket detail", "send reply"],
  "max_iterations": 3
}
```

**Validation.** Requests are validated against a JSON Schema before any agent runs. A missing or unreachable spec, or an unsupported `target`, returns a clear error and no agent is started (this is part of the robustness behaviour shown in the live demo).

## 9. Output definition

A run produces a project, a preview URL and a quality report.

| Output | Format | Contents |
| --- | --- | --- |
| Generated project | Git directory (React, TypeScript, Tailwind, Vite) | Source, unit tests, Playwright tests, README |
| Preview URL | HTTPS URL | The deployed generated app |
| `quality_report.json` | JSON | Gate results, scores, agent decisions, unresolved issues |
| `trace.jsonl` | JSON Lines, append-only | Every agent message, routing decision and proof-of-work record |

**Sample `quality_report.json`** (illustrative values; the submitted sample must come from a real run):

```json
{
  "run_id": "run-0007",
  "status": "accepted",
  "iterations": {"total": 5, "by_agent": {"engineer": 3, "designer": 1, "integration": 1}},
  "gates": {
    "build": {"passed": true, "evidence": "artifacts/build.log"},
    "tests": {"passed": true, "flows_passed": 4, "flows_total": 4},
    "accessibility": {"passed": true, "critical": 0, "serious": 0},
    "quality": {"lighthouse_accessibility": 96, "lighthouse_performance": 88},
    "integration": {"passed": true, "documented_mismatches": 1}
  },
  "revisions": [
    {"by": "critic", "to": "designer", "reason": "Body text contrast below WCAG AA", "resolved": true}
  ],
  "unresolved": [],
  "preview_url": "https://labrith-run-0007.example.app"
}
```

**Failure output.** If the iteration budget runs out, `status` is `partial`, the project is still delivered, and `unresolved` lists each open issue with its evidence.

## 10. Testing strategy

There are two layers of tests: tests of Labrith itself (graded under Code Review) and tests that Labrith's agents generate for the apps they build (part of the product).

| Layer | What is tested | Tooling | Owner |
| --- | --- | --- | --- |
| Unit | Input validation, OpenAPI parser, state transitions, routing rules, proof-of-work validator, gate evaluation | pytest | Member 1 and Member 3 |
| Agent behaviour | Each agent given a fixed state returns the expected kind of output and a valid proof-of-work record; LLM calls are mocked with recorded responses | pytest with fixtures | Each agent's owner |
| Loop and routing | Scripted failures (broken build, failing flow, contrast violation) trigger the correct reroute and stop at the iteration limit | pytest with a scripted fake LLM | Member 1 |
| End to end | Full run on the demo spec produces an accepted report and a passing generated app | pytest plus Playwright | Member 3 |
| Robustness | Bad spec, unreachable API, one tool failing mid-run: the system degrades and reports instead of crashing | pytest | Member 3 |

**Rules.** Tests are written with the feature, not at the end. A pull request that adds agent logic without a test is not merged. Test output is saved as evidence for the presentation.

## 11. Repository structure and engineering practice

```text
labrith/
  agents/        planner.py, designer.py, engineer.py, integration.py, qa.py, critic.py
  graph/         state.py, routing.py, graph.py (LangGraph definition)
  tools/         sandbox.py, openapi.py, mock_server.py, playwright_runner.py, axe_runner.py, lighthouse_runner.py
  lib/           llm.py (model wrapper), proofs.py (proof-of-work records), trace.py
  schemas/       input.schema.json, output.schema.json, proof.schema.json
  api/           FastAPI app
  web/           React control UI
  tests/         unit/, agents/, routing/, e2e/
  examples/      sample_input.json, sample_output/, sample_trace.jsonl
  docs/          design document, diagrams
  README.md  .gitignore  .env.example
```

**Practices.**

- Secrets only in `.env` (ignored by Git); `.env.example` documents the variables.
- Short-lived branches and pull requests, with a teammate reviewing each one.
- Commits are small, frequent and descriptive, spread across the whole build period.
- Every member registers their GitHub username on the Artifacts page and commits under their own account.
- The README covers setup, architecture summary, how to run tests and how to reproduce a demo run.

## 12. Team ownership and evidence checklist

Each member owns specific agents and must hand over proof of work and passing tests before a piece counts as done. The team lead uses this table to check submissions.

| Member | Owns | Proof of work to hand over | Tests required |
| --- | --- | --- | --- |
| Member 1 (lead) | Graph, shared state, Planner, trace logging, FastAPI, deployment, Design Document | Graph running with stubs, a captured trace file with routing decisions, deployed URL | Routing and loop-limit tests, state transition tests, proof-of-work validator tests |
| Member 2 | Design Architect, Component Engineer, sandbox, demo backend and spec | Generated sample app that builds, design spec JSON, build logs, first successful fix-the-build loop in the trace | Engineer and Designer agent tests, sandbox isolation test, parser tests for generated output |
| Member 3 | Integration, QA and Critic agents, schemas and samples | Playwright results with screenshots, axe and Lighthouse reports, a mismatch report from a real API, a Critic-to-Designer revision in the trace | QA and Critic agent tests, integration tests with a mock server, end-to-end and robustness tests |

**Hand-over checklist for every pull request:**

- [ ] Code merged through a pull request reviewed by another member
- [ ] Unit tests added and passing (test output attached to the pull request)
- [ ] Proof of work attached: log, screenshot or trace excerpt showing the feature running
- [ ] README or docs updated if behaviour changed
- [ ] No secrets in the diff

**Milestone evidence (collect as you go, for the presentation and the submission):**

- [ ] Architecture diagram in the repo that matches the code
- [ ] First end-to-end run trace (raw, unedited)
- [ ] Trace showing each of the six adaptation scenarios in Section 5
- [ ] Passing test run output for all test layers
- [ ] Live deployment link checked weekly until results are published
- [ ] Demo video of a complete run
- [ ] Each member can explain their agents, and where the work was design rather than commits, notes ready to say so in the presentation

## 13. Risks, failure handling and consistency

| Risk | Mitigation |
| --- | --- |
| LLM latency or outage during the live demo | Cached known-good run available as a fallback; per-call timeouts and retries; demo video as backup |
| Generated code breaks the host | Sandboxed working directory per run; no network access for generated code beyond the demo API |
| Infinite fix loops and runaway cost | Iteration budget per task and per run; Planner escalates instead of retrying forever |
| One tool fails (Playwright, Lighthouse, spec fetch) | The affected agent reports the failure with evidence; the Planner continues with the remaining gates and marks that gate unverified in the report |
| Scope creep | v1 limited to React and Tailwind over an OpenAPI backend; extra targets listed as future work |
| Documents drift from the code | Design Document, schemas, samples and trace are updated in the same pull request as the code they describe |
| Model costs across six agents | Per-agent model choice; cheaper model for summarising and auditing steps |

**Consistency check before submission.** The architecture diagram, the agent list, the input and output samples, the trace and the deployed system must all describe the same six agents and the same flow. Any difference is fixed in the document or the code before submitting, because evaluators cross-check them.
