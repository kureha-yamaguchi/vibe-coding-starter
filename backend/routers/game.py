from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from services import game as rules
from services import llm, music
from services.game import PublicGameState, public_state, store

router = APIRouter(tags=["game"])


class CreateGameRequest(BaseModel):
    source: Literal["chart", "search"] = "chart"
    query: str | None = Field(default=None, max_length=120)
    rounds: int = Field(default=10, ge=1, le=30)
    player: str = Field(default="Player", max_length=40)


class GuessRequest(BaseModel):
    guess: str = Field(min_length=1, max_length=200)
    elapsed_ms: int = Field(default=0, ge=0)


class GuessResponse(BaseModel):
    title_correct: bool
    artist_correct: bool
    newly_title: bool
    newly_artist: bool
    speed_bonus: bool
    round_complete: bool
    comment: str
    source: Literal["mistral", "fallback"]
    state: PublicGameState


def _load(game_id: str) -> rules.Game:
    try:
        return store.get(game_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Game not found (it may have expired).") from exc


@router.get("/llm/status")
async def llm_status() -> dict[str, object]:
    return {"configured": llm.has_api_key(), "judge_model": llm.JUDGE_MODEL}


@router.get("/music/search")
async def music_search(q: str = Query(min_length=1, max_length=120)) -> dict[str, int]:
    try:
        tracks = await music.search_tracks(q)
    except music.MusicError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"count": len(tracks)}


@router.post("/games", response_model=PublicGameState)
async def create_game(body: CreateGameRequest) -> PublicGameState:
    try:
        tracks = await music.build_playlist(body.source, body.query, body.rounds)
    except music.MusicError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    game = store.add(rules.new_game(body.player, body.source, body.query, tracks))
    return public_state(game)


@router.get("/games/{game_id}", response_model=PublicGameState)
async def get_game(game_id: str) -> PublicGameState:
    return public_state(_load(game_id))


@router.post("/games/{game_id}/guess", response_model=GuessResponse)
async def guess(game_id: str, body: GuessRequest) -> GuessResponse:
    game = _load(game_id)
    if game.status != "playing":
        raise HTTPException(status_code=409, detail="No live round to guess on.")
    track = game.current_round.track
    judgement = await llm.judge_guess(body.guess, track.title, track.artist)
    outcome = rules.apply_judgement(game, body.guess, judgement, body.elapsed_ms)
    return GuessResponse(
        **outcome.model_dump(),
        comment=judgement.comment,
        source=judgement.source,
        state=public_state(game),
    )


@router.post("/games/{game_id}/reveal", response_model=PublicGameState)
async def reveal(game_id: str) -> PublicGameState:
    game = _load(game_id)
    if game.status == "finished":
        raise HTTPException(status_code=409, detail="Game is already finished.")
    if game.status == "playing":
        rules.reveal(game)
    return public_state(game)


@router.post("/games/{game_id}/next", response_model=PublicGameState)
async def next_round(game_id: str) -> PublicGameState:
    game = _load(game_id)
    try:
        rules.advance(game)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return public_state(game)
