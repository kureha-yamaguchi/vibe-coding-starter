"""Game models, pure rules, and the in-memory store.

Rule functions take and mutate models but do no I/O, so they are unit-testable.
`PublicGameState` is the only shape the API returns during a live round and it
carries no title/artist fields, so the answer cannot leak before reveal.
"""

from __future__ import annotations

import time
import uuid
from typing import Literal

from pydantic import BaseModel, Field

from services.llm import JudgeResult
from services.music import Track

SPEED_BONUS_MS = 10_000
POINTS_PER_ROUND = 3  # title + artist + speed bonus
STORE_TTL_SECONDS = 2 * 60 * 60

GameStatus = Literal["playing", "revealed", "finished"]


class Round(BaseModel):
    track: Track
    title_correct: bool = False
    artist_correct: bool = False
    speed_bonus: bool = False
    guesses: list[str] = Field(default_factory=list)
    revealed: bool = False

    @property
    def points(self) -> int:
        return int(self.title_correct) + int(self.artist_correct) + int(self.speed_bonus)


class Game(BaseModel):
    id: str
    player: str
    source: str
    query: str | None = None
    rounds: list[Round]
    current: int = 0
    status: GameStatus = "playing"
    created_at: float = Field(default_factory=time.time)

    @property
    def score(self) -> int:
        return sum(r.points for r in self.rounds)

    @property
    def max_score(self) -> int:
        return POINTS_PER_ROUND * len(self.rounds)

    @property
    def current_round(self) -> Round:
        return self.rounds[self.current]


class GuessOutcome(BaseModel):
    title_correct: bool
    artist_correct: bool
    newly_title: bool
    newly_artist: bool
    speed_bonus: bool
    round_complete: bool


# ---------- public (answer-free) views ----------


class PublicRound(BaseModel):
    index: int
    total: int
    preview_url: str
    title_correct: bool
    artist_correct: bool
    speed_bonus: bool
    guesses: int


class RevealedTrack(BaseModel):
    title: str
    artist: str
    album: str
    cover_url: str
    points: int
    title_correct: bool
    artist_correct: bool
    speed_bonus: bool


class RoundSummary(BaseModel):
    index: int
    title: str
    artist: str
    cover_url: str
    points: int


class PublicGameState(BaseModel):
    id: str
    player: str
    source: str
    query: str | None
    status: GameStatus
    score: int
    max_score: int
    round: PublicRound | None = None
    revealed: RevealedTrack | None = None
    summary: list[RoundSummary] | None = None


def public_state(game: Game) -> PublicGameState:
    state = PublicGameState(
        id=game.id,
        player=game.player,
        source=game.source,
        query=game.query,
        status=game.status,
        score=game.score,
        max_score=game.max_score,
    )
    if game.status == "finished":
        state.summary = [
            RoundSummary(index=i, title=r.track.title, artist=r.track.artist, cover_url=r.track.cover_url, points=r.points)
            for i, r in enumerate(game.rounds)
        ]
        return state

    rnd = game.current_round
    state.round = PublicRound(
        index=game.current,
        total=len(game.rounds),
        preview_url=rnd.track.preview_url,
        title_correct=rnd.title_correct,
        artist_correct=rnd.artist_correct,
        speed_bonus=rnd.speed_bonus,
        guesses=len(rnd.guesses),
    )
    if game.status == "revealed":
        state.revealed = RevealedTrack(
            title=rnd.track.title,
            artist=rnd.track.artist,
            album=rnd.track.album,
            cover_url=rnd.track.cover_url,
            points=rnd.points,
            title_correct=rnd.title_correct,
            artist_correct=rnd.artist_correct,
            speed_bonus=rnd.speed_bonus,
        )
    return state


# ---------- rules ----------


def new_game(player: str, source: str, query: str | None, tracks: list[Track]) -> Game:
    if not tracks:
        raise ValueError("A game needs at least one track.")
    return Game(
        id=uuid.uuid4().hex[:12],
        player=player.strip() or "Player",
        source=source,
        query=query,
        rounds=[Round(track=t) for t in tracks],
    )


def apply_judgement(game: Game, guess: str, judgement: JudgeResult, elapsed_ms: int) -> GuessOutcome:
    if game.status != "playing":
        raise ValueError("No live round to guess on.")
    rnd = game.current_round
    rnd.guesses.append(guess)

    newly_title = judgement.title_correct and not rnd.title_correct
    newly_artist = judgement.artist_correct and not rnd.artist_correct
    rnd.title_correct = rnd.title_correct or judgement.title_correct
    rnd.artist_correct = rnd.artist_correct or judgement.artist_correct

    complete = rnd.title_correct and rnd.artist_correct
    if complete and (newly_title or newly_artist) and elapsed_ms <= SPEED_BONUS_MS:
        rnd.speed_bonus = True
    if complete:
        reveal(game)

    return GuessOutcome(
        title_correct=rnd.title_correct,
        artist_correct=rnd.artist_correct,
        newly_title=newly_title,
        newly_artist=newly_artist,
        speed_bonus=rnd.speed_bonus,
        round_complete=complete,
    )


def reveal(game: Game) -> None:
    if game.status == "finished":
        raise ValueError("Game is already finished.")
    game.current_round.revealed = True
    game.status = "revealed"


def advance(game: Game) -> None:
    if game.status != "revealed":
        raise ValueError("Reveal the current round before moving on.")
    if game.current + 1 >= len(game.rounds):
        game.status = "finished"
    else:
        game.current += 1
        game.status = "playing"


def is_over(game: Game) -> bool:
    return game.status == "finished"


# ---------- store ----------


class GameStore:
    def __init__(self, ttl_seconds: float = STORE_TTL_SECONDS) -> None:
        self._games: dict[str, Game] = {}
        self._ttl = ttl_seconds

    def _sweep(self) -> None:
        cutoff = time.time() - self._ttl
        for game_id in [gid for gid, g in self._games.items() if g.created_at < cutoff]:
            del self._games[game_id]

    def add(self, game: Game) -> Game:
        self._sweep()
        self._games[game.id] = game
        return game

    def get(self, game_id: str) -> Game:
        self._sweep()
        return self._games[game_id]


store = GameStore()
