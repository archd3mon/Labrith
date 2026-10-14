# FrontForge (Labrith)

FrontForge is a multi-agent system (LangGraph, Python) that acts as a collaborative frontend engineering team. Given a product brief and an OpenAPI spec, it plans, designs, builds, integrates, tests, and reviews a React + TypeScript + Tailwind web application and delivers it with a verified quality report.

**Live Stable Deployment URL:** [https://frontforge-demo.loca.lt](https://frontforge-demo.loca.lt) (Local: `http://localhost:8000`)

---

## The Six Cooperating Agents
FrontForge enforces strict separation of concerns across six autonomous agents communicating through a shared blackboard state (Design Doc §3 & §4):

| Agent | Role | Proof of Work Attached |
|---|---|---|
| **Planner (Supervisor)** | Formulates task plans, reasons over blackboard state, routes workflows, triggers replanning and escalations. | Plan DAG, routing decision and justification |
| **Design Architect** | Selects design tokens, responsive layouts, color palettes, and component inventory. | Design spec JSON, critic revision notes |
| **Component Engineer** | Writes React, TypeScript, and Tailwind code with automated compilation and build tests. | Code diff, passing `npm run build` log |
| **Integration Agent** | Generates typed API clients, spins up mock servers, and binds UI to OpenAPI endpoints. | Generated client, contract mismatch report |
| **QA Agent** | Runs end-to-end user flows in a real headless browser (Playwright) and captures evidence. | Test run results, screenshot paths, console logs |
| **Accessibility & Design Critic** | Audits WCAG 2.1 AA compliance (axe-core) and performance/UX scores (Lighthouse). | Accessibility audit report, Lighthouse scores |

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
- `GET /runs/{run_id}` — Returns the current status (`running`, `accepted`, `partial`, `failed`), preview URL, and full `quality_report.json` upon completion.
- `GET /runs/{run_id}/events` — Server-Sent Events (SSE) streaming append-only trace entries from `trace.jsonl` in real time, concluding with `event: end`.
- `GET /runs` — Lists historical runs and their completion statuses.
- `GET /health` — Health check endpoint (`{"status": "ok"}`).
- `GET /` — Serves the React Control UI bundle from `web/dist`.

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
- Python 3.11+
- Node.js 18+ & npm

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
   .venv\Scripts\Activate.ps1
   # Linux / macOS:
   source .venv/bin/activate
   ```
3. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Build the React Control UI:
   ```bash
   cd web
   npm install
   npm run build
   cd ..
   ```
5. Configure environment variables (optional for offline demo):
   ```bash
   cp .env.example .env
   ```

---

## Running Tests
Run the comprehensive test suite with `pytest`:

```bash
# Run all API unit tests (validation, 400 errors, lifecycle, SSE streaming)
pytest tests/unit/test_api.py -v

# Run the full end-to-end pipeline test across all 6 agents
pytest tests/e2e/test_e2e.py -v

# Run all unit tests
pytest tests/unit/ -v
```

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

---

## Architecture Rules & Integrity
- All agent interactions follow the supervisor-blackboard pattern (`graph/graph.py`).
- Every handoff carries a proof-of-work record (`schemas/proof.schema.json`).
- Traces are append-only (`lib/trace.py`).
- See [AGENTS.md](AGENTS.md) and [docs/DESIGN.md](docs/DESIGN.md) for full architecture specifications.
