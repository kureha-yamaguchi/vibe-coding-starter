# Vibe Coding Starter

You are working in a pre-configured full-stack interview starter. Build on top of it — do not replace the stack unless the candidate asks.

## Stack

- **Backend**: FastAPI on port 8000 (`backend/`)
- **Frontend**: React + Vite on port 3000 (`frontend/`)
- **Env**: `MISTRAL_API_KEY` in `.env` at the repo root

## What is already set up

- `backend/main.py` — FastAPI app with CORS and `/api/health`
- `frontend/src/App.tsx` — landing page with backend status check

## Setup

From the repo root, run each block in its own shell.

```bash
cp .env.example .env
```

```bash
cd backend
uv sync
```

```bash
cd frontend
pnpm install
```

## Running locally

Open two terminals from the repo root.

```bash
cd backend
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

```bash
cd frontend
pnpm dev
```
