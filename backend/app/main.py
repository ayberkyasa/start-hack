"""Application entry point. Startup validates local settings before serving."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.health import router as health_router
from app.settings import load_settings
from app.storage.database import open_database


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.settings = load_settings()
    with open_database(app.state.settings.database_path) as repository:
        app.state.repository = repository
        try:
            yield
        finally:
            del app.state.repository


app = FastAPI(title="Simulation Console", version="0.1.0", lifespan=lifespan)
app.include_router(health_router, prefix="/api")
