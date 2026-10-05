"""FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api.routes_runs import repos_router, router as runs_router
from app.config import get_settings
from app.db.session import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # For local dev / tests we create tables on startup. Production uses Alembic.
    init_db()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="RepoSage",
        version=__version__,
        description="Codebase Onboarding & Tech-Debt Copilot",
        lifespan=lifespan,
    )

    @app.get("/health", tags=["meta"])
    def health() -> dict:
        return {"status": "ok", "version": __version__, "environment": settings.environment}

    app.include_router(runs_router)
    app.include_router(repos_router)
    return app


app = create_app()
