"""Application entry point. Startup does not initialize external integrations."""

from fastapi import FastAPI

from app.api.health import router as health_router

app = FastAPI(title="Simulation Console", version="0.1.0")
app.include_router(health_router, prefix="/api")
