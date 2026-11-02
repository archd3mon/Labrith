 # FrontForge (Labrith)

> **Multi-agent frontend generation system** — give it a product brief and an OpenAPI spec and it returns a deployed React + TypeScript + Tailwind app with a verified quality report.

FrontForge is built with LangGraph (Python) and orchestrates six cooperating AI agents that mirror a real frontend team: planning, design, implementation, API integration, browser testing, and accessibility review. Every agent decision is recorded in an append-only trace so the full reasoning is auditable.

**Target users:** Solo AI developers, hackathon teams, and early-stage startups with a working backend but no frontend capacity.

**Live Stable Deployment URL:** [https://frontforge-demo.loca.lt](https://frontforge-demo.loca.lt) (Local: `http://localhost:8000`)

---

## Architecture

FrontForge uses the **supervisor-over-blackboard** pattern (see `docs/DESIGN.md` §4):

- The **Planner** is the supervisor. It writes a task plan to the shared state and, after each handoff, reads every agent's output to decide the next step. It never writes code or judges quality.
- All other agents are **workers**. They read from the shared state, do their work using dedicated tools, and write back their output with a **proof-of-work record**. Workers never call each other directly.
- The **shared state** (`graph/state.py`) is the single source of truth — design tokens, past errors, task statuses, and all agent outputs live there.
- Routing is LLM-driven and handled in `graph/routing.py`, with hard iteration limits to prevent infinite loops.
- Every agent message, routing decision, and proof-of-work record is appended to `trace.jsonl` by `lib/trace.py`.

```
Brief + OpenAPI spec
        │
    ┌───▼───┐
    │Planner│  (supervisor)
    └───┬───┘
        │  reads/writes shared state
   ┌────┴─────────────────────────────────┐
   │  Designer │ Engineer │ Integration   │
   │  QA       │ Critic                   │
   └──────────────────────────────────────┘
        │
    quality_report.json + trace.jsonl
```

---

## The Six Cooperating Agents
FrontForge enforces strict separation of concerns across six autonomous agents communicating through a shared blackboard state (Design Doc §3 & §4):

| Agent | Role | Key Tools | Proof of Work Attached |
|---|---|---|---|
| **Planner (Supervisor)** | Formulates task plans, reasons over blackboard state, routes workflows, triggers replanning and escalations. | Spec parser, task queue, shared state | Plan DAG, routing decision and justification |
| **Design Architect** | Selects design tokens, responsive layouts, color palettes, and component inventory. | Token generator, screenshot viewer (vision model) | Design spec JSON, critic revision notes |
| **Component Engineer** | Writes React, TypeScript, and Tailwind code with automated compilation and build tests. | File writer, `npm run build`, linter, type checker | Code diff, passing `npm run build` log |
| **Integration Agent** | Generates typed API clients, spins up mock servers, and binds UI to OpenAPI endpoints. | OpenAPI reader (`tools/openapi.py`), mock server (`tools/mock_server.py`), HTTP client | Generated client, contract mismatch report |
| **QA Agent** | Runs end-to-end user flows in a real headless browser (Playwright) and captures evidence. | Playwright (`tools/playwright_runner.py`), screenshots, console log capture | Test run results, screenshot paths, console logs |
| **Accessibility & Design Critic** | Audits WCAG 2.1 AA compliance (axe-core) and performance/UX scores (Lighthouse). | axe-core (`tools/axe_runner.py`), Lighthouse (`tools/lighthouse_runner.py`), vision model | Accessibility audit report, Lighthouse scores |

Every agent output **must** carry a proof-of-work record validated against `schemas/proof.schema.json`. The Planner rejects any handoff without one.

---

## Verification Gates (Design Doc §6)
A build is only accepted when all five verification gates pass:
1. **Build Gate:** `npm run build` and TypeScript compiler exit cleanly.
2. **Test Gate:** All required user flows pass in headless Playwright browser tests.
3. **Accessibility Gate:** Zero critical or serious axe-core violations (WCAG 2.1 AA compliance).
4. **Quality Gate:** Lighthouse performance and accessibility scores above threshold.
5. **Integration Gate:** Every API call verified against OpenAPI contract or documented.

---

## FastAPI Endpoints (`api/main.py`)
The system provides a FastAPI service that streams agent activity in real time:

- `POST /runs` — Validates input against `schemas/input.schema.json` and verifies OpenAPI spec reachability. If invalid, returns a clear `400 Bad Request` with itemised reasons and starts **no** agents. If valid, generates a unique `run_id`, initializes workspace in background, and returns `201 Created`.

  **Request body fields:**
  | Field | Type | Required | Description |
  |---|---|---|---|
  | `brief` | string | ✓ | Plain-language product description |
  | `api_spec_url` | string (URL) or inline OpenAPI 3 JSON | ✓ | Backend API description |
  | `target` | `"dashboard"` \| `"form_app"` \| `"mixed"` | ✓ | Type of interface to generate |
  | `style_hints` | array of strings | — | e.g. `["minimal", "dark"]` |
  | `required_flows` | array of strings | — | QA flows; Planner derives them if absent |
  | `max_iterations` | integer | — | Per-task budget (default `3`) |

  **Success response (`201`):** `{"run_id": "run-xxxx", "status": "running"}`

- `GET /runs/{run_id}` — Returns the current status (`running`, `accepted`, `partial`, `failed`), preview URL, and full `quality_report.json` upon completion.
- `GET /runs/{run_id}/events` — Server-Sent Events (SSE) streaming append-only trace entries from `trace.jsonl` in real time. Each `trace` event's `data` is one JSONL entry; entries are not necessarily proof-of-work records. The stream concludes with an `end` event containing the run status and final report.
- `GET /runs` — Lists runs held in the service's in-memory registry and their completion statuses.
- `GET /api/sample-input` — Returns the sample request used to prefill the Control UI, making it available to API clients as well.
- `GET /health` — Health check endpoint (`{"status": "ok", "service": "FrontForge API"}`).
- `GET /` — Serves the React Control UI bundle from `web/dist`.
- `/docs` and `/redoc` — Interactive Swagger UI and ReDoc API references; `/openapi.json` serves the generated OpenAPI document.

---

## React Control UI (`web/`)
The web workspace contains a production-grade React + TypeScript + Vite + Tailwind CSS control studio:
- **Control Deck:** Input form with quick-fill presets (Support Ticket Dashboard, Form App, Analytics Portal), OpenAPI spec URL, interface targets (`dashboard`, `form_app`, `mixed`), style hints, user flows, and iteration limits.
- **Active Blackboard Grid:** Real-time visual state of all 6 agents (Planner supervisor + 5 workers) displaying active status, execution indicators, and latest proof-of-work claims.
- **Live Activity Feed:** Real-time SSE stream displaying agent reasoning, routing transitions, proof-of-work records, and expandable JSON evidence files.
- **Quality Report & Preview:** Status hero banner, interactive 5 verification gates cards, agent iteration breakdown, revision logs, and live app preview link.
- **Run History Modal:** Switch between historical runs and inspect previously generated reports.

---

## Setup & Getting Started

### Prerequisites
- Python **3.11+** (3.11 or 3.12 recommended; check with `python --version`)
- Node.js **18+** & npm (check with `node --version`)
- Git

### Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/archd3mon/Labrith.git
   cd Labrith
   ```
2. Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   # Windows PowerShell:
   .\.venv\Scripts\Activate.ps1
   # Linux / macOS:
   source .venv/bin/activate
   ```
   If PowerShell blocks activation, allow scripts for the current PowerShell process only, then retry:
   ```powershell
   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process
   .\.venv\Scripts\Activate.ps1
   ```
3. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Install Playwright browsers (required for QA agent):
   ```bash
   pip install playwright
   playwright install chromium
   ```
5. Build the React Control UI:
   ```bash
   cd web
   npm install
   npm run build
   cd ..
   ```
6. Configure environment variables (optional for offline demo):
   ```bash
   cp .env.example .env
   # Edit .env and add your API keys (see Configuration section below)
   ```

---

## Configuration

All configuration is via environment variables in `.env` (copy from `.env.example`). Never commit real keys.

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | One of these is required | API key for Anthropic (Claude models) |
| `OPENAI_API_KEY` | One of these is required | API key for OpenAI (GPT models) |
| `GEMINI_API_KEY` | One of these is required | API key for Google Gemini |
| `GROQ_API_KEY` | One of these is required | API key for Groq |
| `PLANNER_MODEL` | No (default in `.env.example`) | LLM model string used by the Planner agent |
| `DESIGNER_MODEL` | No | LLM model string used by the Design Architect |
| `ENGINEER_MODEL` | No | LLM model string used by the Component Engineer |
| `INTEGRATION_MODEL` | No | LLM model string used by the Integration Agent |
| `QA_MODEL` | No | LLM model string used by the QA Agent |
| `CRITIC_MODEL` | No | LLM model string used by the Accessibility & Design Critic |
| `MAX_ITERATIONS` | No (default: `5`) | Global iteration budget cap across all agents |
| `LLM_TIMEOUT_SECONDS` | No (default: `60`) | Per-call LLM timeout in seconds |

All LLM calls go through `lib/llm.py`. Model selection per agent is read from these variables so you can mix providers (e.g. a stronger model for the Engineer, a cheaper one for the Critic) without touching agent code.

---

## Running Tests
Run the comprehensive test suite with `pytest`:

```bash
# Run all unit tests (validation, state, routing, gates, proof-of-work)
pytest tests/unit/ -v

# Run agent behaviour tests (each agent with mocked LLM via tests/fakes.py)
pytest tests/agents/ -v

# Run routing and loop-limit tests (scripted fake LLM)
pytest tests/routing/ -v

# Run the full end-to-end pipeline test (uses a real model — requires API keys in .env)
pytest tests/e2e/ -v

# Run everything except e2e
pytest tests/unit/ tests/agents/ tests/routing/ -v
```

The `tests/fakes.py` module provides a scripted fake LLM for unit and agent tests so no real API key is needed for most of the suite.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `POST /runs` returns `400` | Request body is malformed or fails validation | Check required fields: `brief`, `api_spec_url`, `target` |
| `POST /runs` returns `400` | `api_spec_url` is unreachable or not valid OpenAPI 3 | Verify the URL is reachable and returns a valid spec |
| `playwright install` fails | Playwright not installed | Run `pip install playwright` then `playwright install chromium` |
| `npm run build` fails in `web/` | Node modules not installed | Run `npm install` inside `web/` first |
| LLM calls time out | `LLM_TIMEOUT_SECONDS` too low or network issue | Increase `LLM_TIMEOUT_SECONDS` in `.env` |
| Agent loop hits iteration limit | `MAX_ITERATIONS` exhausted | Run status becomes `partial`; check `quality_report.json` `unresolved` field for details |

---

## Running the Application Locally

### Option 1: Unified FastAPI Server (Serves API + Built UI)
```bash
# Start the unified backend on port 8000
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```
Open [http://localhost:8000](http://localhost:8000) in your browser.

### Option 2: Vite Dev Server + FastAPI (For Frontend Development)
In Terminal 1 (Backend):
```bash
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload
```

In Terminal 2 (Frontend):
```bash
cd web
npm run dev
```
Open [http://localhost:5173](http://localhost:5173) in your browser (proxies API requests to port 8000).

---

## Running with Docker & Docker Compose

### Using Docker Compose:
```bash
docker compose up --build
```
Access the application at [http://localhost:8000](http://localhost:8000).

### Using Docker directly:
```bash
docker build -t frontforge .
docker run -p 8000:8000 frontforge
```

---

## Reproducing a Demo Run

### Via the Control UI:
1. Open [http://localhost:8000](http://localhost:8000) (or the deployed live URL [https://frontforge-demo.loca.lt](https://frontforge-demo.loca.lt)).
2. Click **Load Sample** (or select the **Support** preset).
3. Click **Launch FrontForge Run**.
4. Watch the Live Trace feed stream agent events and proof-of-work records in real time.
5. Once completed, navigate to **Quality Report & Preview** to inspect the 5 verification gates and click **Open Live Preview**.

### Via `curl`:
The example below uses Bash-style line continuations. In Windows PowerShell, use the native PowerShell example that follows; `curl` there is an alias for `Invoke-WebRequest`.

```bash
# 1. Trigger a run
curl -X POST http://localhost:8000/runs \
  -H "Content-Type: application/json" \
  -d '{
    "brief": "A support dashboard where agents view open tickets, filter by priority, open a ticket to read its history, and reply.",
    "api_spec_url": "https://demo-backend.example.com/openapi.json",
    "target": "dashboard",
    "style_hints": ["minimal", "data-dense"],
    "required_flows": ["list tickets", "filter by priority", "open ticket detail", "send reply"],
    "max_iterations": 3
  }'

# Returns: {"run_id": "run-xxxx", "status": "running"}

# 2. Check run status & quality report
curl http://localhost:8000/runs/run-xxxx

# 3. Stream live trace events
curl -N http://localhost:8000/runs/run-xxxx/events
```

### Via PowerShell:
```powershell
# 1. Trigger a run
$body = @{
  brief = "A support dashboard where agents view open tickets, filter by priority, open a ticket to read its history, and reply."
  api_spec_url = "https://demo-backend.example.com/openapi.json"
  target = "dashboard"
  style_hints = @("minimal", "data-dense")
  required_flows = @("list tickets", "filter by priority", "open ticket detail", "send reply")
  max_iterations = 3
} | ConvertTo-Json -Depth 5

$run = Invoke-RestMethod -Method Post `
  -Uri "http://localhost:8000/runs" `
  -ContentType "application/json" `
  -Body $body
$run

# 2. Check run status and quality report
Invoke-RestMethod -Uri "http://localhost:8000/runs/$($run.run_id)"

# 3. Stream live trace events
curl.exe -N "http://localhost:8000/runs/$($run.run_id)/events"
```

---

## Architecture Rules & Integrity
- All agent interactions follow the supervisor-blackboard pattern (`graph/graph.py`).
- Every handoff carries a proof-of-work record (`schemas/proof.schema.json`).
- Traces are append-only (`lib/trace.py`).
- See [AGENTS.md](AGENTS.md) and [docs/DESIGN.md](docs/DESIGN.md) for full architecture specifications.
