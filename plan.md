# Plan: Blind Test (music quiz) game — Mistral-powered

## Context

`brief.md` asks for a full-stack **blind test** game built end to end on the existing starter (FastAPI + React/Vite). A blind test is a music quiz: the player hears a short audio clip and must guess the song (title and/or artist). Constraints from the brief:

- Audio previews must come from a source that needs **no API key**.
- An **LLM must be used**, and specifically a **Mistral model** (non-negotiable). `MISTRAL_API_KEY` is already wired in `.env` and `mistralai` is already a backend dependency.
- Start simple, then layer features.
- Primary use case: *play a game*.

The starter already gives us: `backend/main.py` (FastAPI, CORS, dotenv, `/api` router prefix), `backend/routers/health.py` (router pattern to copy), `frontend/src/App.tsx` (fetches `/api/health` via the Vite proxy), Inter font + Mistral colour tokens in `frontend/src/index.css`. The Vite dev server proxies `/api` to port 8000, so the frontend never needs CORS or absolute URLs.

## Decisions confirmed with you

| Topic | Decision |
|---|---|
| Mistral's jobs | **Judge free-text guesses** (MVP) and **generate playlists from a theme** (phase 2). Hints / multiple-choice decoys are optional later extras, not committed. |
| Players | **Single player** in the MVP; local pass-and-play in phase 3. No online multiplayer / WebSockets. |
| Audio source | **Deezer public API** (keyless, 30 s MP3 previews). Backend proxies it; client kept swappable so iTunes could replace it. |
| MVP time budget | **About 1 hour**: chart mode + Mistral judging + single-player loop, minimal styling, a few tests. Then pause for review. |

## Remaining assumptions (correct me if wrong)

- **[A1] Models**: `mistral-small-latest` for judging (fast, cheap, called once per guess); `mistral-large-latest` for playlist generation. Both via JSON-mode / structured output so the backend parses a strict schema.
- **[A2] Fallback when Mistral fails**: judging falls back to normalised fuzzy string matching (`difflib`) and the response says so; the game never hard-blocks on the LLM. Missing `MISTRAL_API_KEY` is surfaced as a clear message on the setup screen.
- **[A3] No database.** Game state lives in memory in the backend (dict keyed by game id, TTL sweep). Fine for a single-player local game; SQLite leaderboard is an optional later step.
- **[A4] No auth, no accounts.** Player name is free text.
- **[A5] Scoring**: 1 point for artist, 1 point for title, +1 speed bonus if the correct full answer lands within the first 10 s of the clip. One guess per round is *not* enforced: the player can keep guessing until the clip ends or they reveal, but points are only awarded once per component.
- **[A6] Round length** = the full 30 s Deezer preview in the MVP; a difficulty setting (5 / 10 / 30 s heard) comes in phase 2.
- **[A7] Language**: UI in English; judging prompt tolerates guesses in any language.
- **[A8] MVP "sources"**: Deezer top chart and Deezer search (artist / playlist keyword). Theme mode arrives in phase 2.
- **[A9] Testing level**: pytest for the pure game rules, the judge fallback, and one router happy-path with the LLM and Deezer mocked. Manual end-to-end run through the UI. No frontend unit tests.

## Architecture

```
frontend (React/Vite :3000)  --/api proxy-->  backend (FastAPI :8000)
                                                ├── services/music.py   (Deezer client, httpx, small TTL cache)
                                                ├── services/llm.py     (Mistral: judge_guess, generate_playlist)
                                                ├── services/game.py    (pydantic models, pure rules, in-memory store)
                                                └── routers/game.py     (REST endpoints)
```

The browser plays the preview MP3 directly from the Deezer CDN URL via an `<audio>` element; the backend only passes the URL through. **The answer (title/artist) is never sent to the browser before the round is revealed**: the backend holds it and only returns it on reveal. That is what makes it a genuine blind test rather than a client-side toy.

### Backend

New files (copy the `routers/health.py` pattern; register in `backend/main.py` with `prefix="/api"`):

- `backend/services/music.py`
  - `get_chart_tracks(limit)` → `GET https://api.deezer.com/chart/0/tracks`; `search_tracks(query, limit)` → `GET /search?q=`.
  - Normalise to a `Track` model: `id, title, artist, album, cover_url, preview_url`. Drop tracks whose `preview` is empty; shuffle; de-duplicate by artist+title.
  - `resolve(artist, title)` → best-match Deezer search for LLM-proposed tracks (phase 2).
  - Small in-process TTL cache keyed by query.
- `backend/services/llm.py`
  - Thin wrapper around `mistralai.Mistral` read from `MISTRAL_API_KEY`. One place for model names, timeout, `response_format={"type": "json_object"}`.
  - `judge_guess(guess, title, artist) -> JudgeResult{title_correct, artist_correct, comment, source: "mistral"|"fallback"}`.
  - `generate_playlist(theme, n) -> list[{artist, title}]` (phase 2).
  - `fuzzy_judge(...)` deterministic fallback used on any exception / missing key.
- `backend/services/game.py`
  - Pydantic models: `GameConfig`, `Game`, `Round`, `GuessResult`, `PublicGameState` (the latter is the *only* shape the router returns while a round is live, and it has no title/artist fields by construction).
  - Pure rule functions (`apply_judgement`, `advance_round`, `is_over`) free of I/O so they are unit-testable.
  - `GameStore`: dict of games with `create/get`, plus TTL sweep on access.
- `backend/routers/game.py`
  - `POST /api/games` `{source: "chart"|"search"|"theme", query?, rounds: 10, player: "Kenta"}` → builds the track list, returns `PublicGameState`.
  - `GET /api/games/{id}` → `PublicGameState` (round index, `preview_url`, cover blurred? no: cover withheld until reveal, score, status).
  - `POST /api/games/{id}/guess` `{guess, elapsed_ms}` → `judge_guess`, score update, returns verdict + comment. Answer still withheld unless both parts are now correct (then it auto-reveals).
  - `POST /api/games/{id}/reveal` → ends the round, returns title/artist/cover, advances to next round or `finished`.
  - `GET /api/music/search?q=` → used by the setup screen to preview that a search query yields enough playable tracks.
- `backend/main.py`: include the new routers; keep `/api/health`.
- `backend/pyproject.toml`: add dev deps `pytest`, `pytest-asyncio`, `respx`. (`mistralai`, `httpx`, `pydantic` already present.)

### Frontend

Keep the starter's plain-CSS approach and reuse the tokens in `frontend/src/index.css`. Replace the placeholder `App.tsx` body with a screen state machine (`"setup" | "playing" | "reveal" | "results"`); no router library needed.

- `src/api.ts` — typed fetch helpers for the endpoints above (same `/api` relative URLs the starter already uses).
- `src/types.ts` — shared response types mirroring the backend's public models.
- `src/screens/SetupScreen.tsx` — source picker (Top charts / Search), rounds, player name; shows backend/Mistral status using the existing health check.
- `src/screens/PlayScreen.tsx` — `AudioPlayer`, 30 s progress bar, guess input with Enter-to-submit, live judge feedback ("Artist ✔ Title ✘ — so close"), "Reveal" button.
- `src/screens/RevealScreen.tsx` — cover art, title, artist, points earned this round, "Next".
- `src/screens/ResultsScreen.tsx` — final score / max, "Play again" with the same settings.
- `src/components/AudioPlayer.tsx` — wraps `<audio>`; first play requires a user gesture (browser autoplay rules), replay button, reports elapsed time for the speed bonus.
- `src/App.css` — extend existing `.app`, `.badge` classes; keep it mobile-friendly.

## Phases

**Phase 1 — Playable MVP (~1 hour, then pause for your review)**
1. `services/music.py` — Deezer chart + search, `Track` model, preview filtering.
2. `services/llm.py` — `judge_guess` with Mistral JSON mode + fuzzy fallback.
3. `services/game.py` — models, rules, store. `routers/game.py` — create / state / guess / reveal. Wire into `main.py`.
4. Frontend: setup → play → reveal → results loop, single player, chart + search sources.
5. `backend/tests/` — rules, fallback judge, router happy path with mocks. Manual E2E.
6. Copy this plan to `/Users/kyamaguchi/Downloads/vibe_coding_starter/plan.md` and tick off items as they land.

**Phase 2 — Mistral-generated playlists**
7. `generate_playlist(theme)` (large model, JSON list) + Deezer `resolve` with backfill when a proposed track has no preview; "Describe a theme" source on the setup screen; show the resolved playlist size before starting.
8. Difficulty setting: seconds of clip heard (5 / 10 / 30), with the speed bonus scaled accordingly.

**Phase 3 — Depth and polish**
9. Local pass-and-play: several player names, rotating turns, per-player scores on results.
10. Optional extras if time allows: Mistral hints that cost points, post-reveal fun fact, multiple-choice easy mode with Mistral decoys, SQLite leaderboard.

## Verification

- Backend unit/integration: `cd backend && uv run pytest`.
  - Rules: scoring per component, speed bonus boundary, round advance, game over.
  - Judge fallback: misspelt title still marks correct; unrelated guess marks wrong; missing key never raises.
  - Router: create → state has `preview_url` and **no `title`/`artist` keys** → guess → reveal returns them. Deezer mocked with `respx`, Mistral mocked with a fake client.
- Manual E2E: run both servers per `README.md`, open `http://127.0.0.1:3000`, start a 3-round "Top charts" game, confirm audio plays after clicking Play, type a deliberately misspelt title and confirm Mistral marks it correct with a comment, reveal, finish and see the results screen, play again.
- Negative paths: blank `MISTRAL_API_KEY` → setup screen warns and judging reports `source: "fallback"`; Deezer unreachable → create-game returns 502 with a readable message, UI shows it.
