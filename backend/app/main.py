"""Application entry point. Startup validates local settings before serving."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.health import router as health_router
from app.settings import load_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.settings = load_settings()
    yield


app = FastAPI(title="Simulation Console", version="0.1.0", lifespan=lifespan)
app.include_router(health_router, prefix="/api")
