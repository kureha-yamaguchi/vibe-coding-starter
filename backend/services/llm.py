"""Mistral integration: judges free-text guesses (and, later, generates playlists).

Every call has a deterministic fallback so the game keeps working when the API
key is missing or the request fails; `JudgeResult.source` says which path ran.
"""

from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Literal

from pydantic import BaseModel

logger = logging.getLogger(__name__)

JUDGE_MODEL = os.getenv("MISTRAL_JUDGE_MODEL", "mistral-small-latest")
PLAYLIST_MODEL = os.getenv("MISTRAL_PLAYLIST_MODEL", "mistral-large-latest")
FUZZY_THRESHOLD = 0.82


class JudgeResult(BaseModel):
    title_correct: bool
    artist_correct: bool
    comment: str = ""
    source: Literal["mistral", "fallback"]


def has_api_key() -> bool:
    return bool(os.getenv("MISTRAL_API_KEY", "").strip())


def normalise(text: str) -> str:
    """Lowercase, strip accents and punctuation, collapse whitespace."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"\(.*?\)|\[.*?\]", " ", text)  # drop "(feat. X)" style suffixes
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _matches(guess: str, answer: str) -> bool:
    g, a = normalise(guess), normalise(answer)
    if not g or not a:
        return False
    if a in g or (len(g) >= 4 and g in a):
        return True
    return SequenceMatcher(None, g, a).ratio() >= FUZZY_THRESHOLD


def fuzzy_judge(guess: str, title: str, artist: str) -> JudgeResult:
    title_ok = _matches(guess, title)
    artist_ok = _matches(guess, artist)
    if title_ok and artist_ok:
        comment = "Both right!"
    elif title_ok:
        comment = "Title's right. Who sings it?"
    elif artist_ok:
        comment = "Artist's right. What's the song?"
    else:
        comment = "Not this one. Keep listening."
    return JudgeResult(title_correct=title_ok, artist_correct=artist_ok, comment=comment, source="fallback")


_JUDGE_SYSTEM = """You are the referee of a music blind test (song-guessing game).
You receive the hidden answer (song title and artist) and a player's free-text guess.
Decide whether the guess correctly names the TITLE, the ARTIST, or both.

Be forgiving of: typos, missing accents or punctuation, different capitalisation,
omitted "(feat. X)" or "(Remix)" suffixes, a missing leading "The", a well-known
nickname or alias for the artist, an unambiguous shortened title.
Be strict about: a different song by the same artist (title wrong), a different
artist with a similar name, a guess that is only a vague description.
If the guess mentions several candidates, only accept it if the correct one is clearly intended.

Reply with ONLY a JSON object:
{"title_correct": boolean, "artist_correct": boolean, "comment": string}
"comment" is at most 12 words, playful, addressed to the player.
NEVER reveal or hint at the title or artist in the comment unless the player already got that part right."""


def _scrub_comment(comment: str, result_title: bool, result_artist: bool, title: str, artist: str) -> str:
    """Belt-and-braces: drop the comment if it leaks a part the player has not found."""
    norm = normalise(comment)
    if not result_title and normalise(title) and normalise(title) in norm:
        return ""
    if not result_artist and normalise(artist) and normalise(artist) in norm:
        return ""
    return comment.strip()[:200]


async def judge_guess(guess: str, title: str, artist: str) -> JudgeResult:
    if not has_api_key():
        return fuzzy_judge(guess, title, artist)

    try:
        from mistralai import Mistral

        client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
        response = await client.chat.complete_async(
            model=JUDGE_MODEL,
            temperature=0,
            max_tokens=120,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _JUDGE_SYSTEM},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"hidden_title": title, "hidden_artist": artist, "player_guess": guess},
                        ensure_ascii=False,
                    ),
                },
            ],
        )
        content = response.choices[0].message.content
        if not isinstance(content, str):
            raise ValueError("unexpected content type from Mistral")
        data = json.loads(content)
        title_ok = bool(data.get("title_correct"))
        artist_ok = bool(data.get("artist_correct"))
        comment = _scrub_comment(str(data.get("comment", "")), title_ok, artist_ok, title, artist)
        return JudgeResult(title_correct=title_ok, artist_correct=artist_ok, comment=comment, source="mistral")
    except Exception as exc:  # noqa: BLE001 - any failure must degrade gracefully
        logger.warning("Mistral judge failed, using fuzzy fallback: %s", exc)
        return fuzzy_judge(guess, title, artist)
