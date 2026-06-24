"""PHeRef Web Portal application entry point."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import __version__
from .routers import api, pages

APP_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title="PHeRef Web Portal",
    version=__version__,
    description="UI-based Health Information Exchange for the Philippine eReferral (PHeRef) Connectathon.",
)

app.include_router(api.router)
pages.register(app)

app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict:
    return {"status": "ok", "version": __version__}
