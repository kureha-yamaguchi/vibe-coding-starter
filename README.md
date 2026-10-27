# Full-stack starter

FastAPI backend (port 8000) + React / Vite frontend (port 3000).

## Setup

From the repo root, run each block in its own shell.

Copy the env file and add your Mistral API key:

```bash
cp .env.example .env
```

Install [uv](https://docs.astral.sh/uv/) if needed, then sync backend dependencies:

```bash
cd backend
uv sync
```

Install frontend dependencies:

```bash
cd frontend
pnpm install
```

## Quick start

Open **two terminals** from the repo root.

### Terminal 1 — Backend

```bash
cd backend
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Terminal 2 — Frontend

```bash
cd frontend
pnpm dev
```

App: http://127.0.0.1:3000

When the backend is up, the home page shows a green backend status dot.