from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers.game import router as game_router
from routers.health import router as health_router

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

app = FastAPI(title="Blind Test API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix="/api")
app.include_router(game_router, prefix="/api")
