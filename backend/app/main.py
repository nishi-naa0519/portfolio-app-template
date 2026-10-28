import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.contact import router as contact_router
from app.api.health import router as health_router
from app.services.contact import ContactServiceProvider


def create_app(
    frontend_dist_dir: Path | None = None,
    contact_service_provider: ContactServiceProvider | None = None,
) -> FastAPI:
    app = FastAPI(title="Portfolio API")
    # Built lazily on the first inquiry, so the app starts without GCP settings.
    app.state.contact_service_provider = contact_service_provider or ContactServiceProvider()
    app.include_router(health_router, prefix="/api")
    app.include_router(contact_router, prefix="/api")

    # In the Docker image the built frontend is served from the same process.
    # Mounted last so that /api/* routes take precedence.
    if frontend_dist_dir is not None and frontend_dist_dir.is_dir():
        app.mount("/", StaticFiles(directory=frontend_dist_dir, html=True), name="frontend")

    return app


# uvicorn only configures its own loggers; this makes app.* INFO logs visible.
logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s - %(message)s")

_frontend_dist_env = os.getenv("FRONTEND_DIST_DIR")
app = create_app(Path(_frontend_dist_env) if _frontend_dist_env else None)
