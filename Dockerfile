# ===========================================================================
# Stage 1: Build the React Control UI
# ===========================================================================
FROM node:20-slim AS frontend-builder
WORKDIR /build

COPY web/package.json ./
RUN npm install

COPY web/ ./
RUN npm run build

# ===========================================================================
# Stage 2: Python 3.11 Production Runtime & Multi-Agent Engine
# ===========================================================================
FROM python:3.11-slim AS runtime

WORKDIR /app

# Install system dependencies for build tools and Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browser dependencies (for headless QA verification)
RUN python -m playwright install --with-deps chromium || true

# Copy project source code
COPY agents/ ./agents/
COPY graph/ ./graph/
COPY tools/ ./tools/
COPY lib/ ./lib/
COPY schemas/ ./schemas/
COPY api/ ./api/
COPY examples/ ./examples/
COPY docs/ ./docs/
COPY AGENTS.md BUILD_PLAYBOOK.md README.md ./

# Copy built frontend assets from Stage 1 into web/dist
COPY --from=frontend-builder /build/dist ./web/dist

# Expose FastAPI service port
EXPOSE 8000

ENV PORT=8000
ENV PYTHONUNBUFFERED=1

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# Start the unified FastAPI server
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
