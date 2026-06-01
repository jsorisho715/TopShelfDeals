"""FastAPI app: serve the TopShelf SPA + static assets and mount the API."""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import db
from app.api import router as api_router

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

app = FastAPI(title="TopShelf")


def _scheduler_enabled() -> bool:
    return (os.getenv("ENABLE_SCHEDULER", "1").strip().lower()) not in ("0", "false", "no", "off")


@app.on_event("startup")
def _startup() -> None:
    db.run_migrations()
    # Warm the geocode cache for every active store (one-time, cached to disk) so
    # the location-radius distances are complete on first paint.
    try:
        import threading

        from app.scrape import warm_geocode_cache

        threading.Thread(target=warm_geocode_cache, daemon=True).start()
    except Exception:
        pass
    if _scheduler_enabled():
        from app.scheduler import start_scheduler

        start_scheduler()


@app.on_event("shutdown")
def _shutdown() -> None:
    if _scheduler_enabled():
        from app.scheduler import shutdown_scheduler

        shutdown_scheduler()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(os.path.join(REPO_ROOT, "TopShelf.html"))


@app.get("/.image-slots.state.json")
def image_slots_state():
    path = os.path.join(REPO_ROOT, ".image-slots.state.json")
    if os.path.exists(path):
        return FileResponse(path)
    return JSONResponse({})


app.include_router(api_router)

app.mount(
    "/TopShelf",
    StaticFiles(directory=os.path.join(REPO_ROOT, "topshelf")),
    name="topshelf",
)
