import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.health import router as health_router


def create_app(frontend_dist_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title="Portfolio API")
    app.include_router(health_router, prefix="/api")

    # In the Docker image the built frontend is served from the same process.
    # Mounted last so that /api/* routes take precedence.
    if frontend_dist_dir is not None and frontend_dist_dir.is_dir():
        app.mount("/", StaticFiles(directory=frontend_dist_dir, html=True), name="frontend")

    return app


_frontend_dist_env = os.getenv("FRONTEND_DIST_DIR")
app = create_app(Path(_frontend_dist_env) if _frontend_dist_env else None)
