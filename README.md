# Labrith (FrontForge)

Labrith is a multi-agent system (LangGraph, Python) that acts as a collaborative frontend engineering team. Given a product brief and an OpenAPI spec, it plans, designs, builds, integrates, tests, and reviews a React + TypeScript + Tailwind web application and delivers it with a verified quality report.

## The Six Agents
- **Planner (Supervisor)**: Formulates the task plan, routes agent work, handles replanning and escalations.
- **Design Architect**: Selects layout, design tokens, palettes, and component specifications.
- **Component Engineer**: Writes React, TypeScript, and Tailwind code with automated build verification.
- **Integration Agent**: Generates API clients, mocks endpoints, and binds components to OpenAPI services.
- **QA Agent**: Executes user flows in a headless browser (Playwright) and verifies behavior.
- **Accessibility & Design Critic**: Audits WCAG compliance (axe-core, Lighthouse) and visual UX standards.

## Project Structure
```
agents/     # Individual agent implementations
graph/      # LangGraph state machine, state schema, and routing logic
tools/      # External tool definitions (Playwright, axe-core, linters, OpenAPI generators)
lib/        # Shared core utilities (models, proofs, trace, llm wrapper)
schemas/    # JSON schemas (input, output, proof)
api/        # API integration specifications and helpers
web/        # Generated / target React application workspace
tests/      # Unit and integration test suite
examples/   # Sample inputs and test fixtures
docs/       # Design document (docs/DESIGN.md) and evidence traces
```

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
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Copy `.env.example` to `.env` and set your configuration:
   ```bash
   cp .env.example .env
   ```
5. Run tests:
   ```bash
   pytest
   ```

## Development Guidelines
Please review [AGENTS.md](AGENTS.md) and [docs/DESIGN.md](docs/DESIGN.md) before contributing.
