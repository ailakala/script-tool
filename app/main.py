import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app.config import STORAGE_DIR, UPLOADS_DIR, CACHE_DIR, TEXT_STORE_DIR
from app.db import init_db

BASE_DIR = Path(__file__).resolve().parent.parent

_shutdown_task: asyncio.Task | None = None
SHUTDOWN_DELAY = 2  # seconds to wait before shutdown


@asynccontextmanager
async def lifespan(app: FastAPI):
    for d in [STORAGE_DIR, UPLOADS_DIR, CACHE_DIR, TEXT_STORE_DIR]:
        d.mkdir(parents=True, exist_ok=True)
    init_db()
    yield


app = FastAPI(title="AI Script Tool", version="0.1.0", lifespan=lifespan)

templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))
app.state.templates = templates

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

from app.routes.pages import router as pages_router
from app.routes.api import router as api_router
from app.routes.chat import router as chat_router
app.include_router(pages_router)
app.include_router(api_router)
app.include_router(chat_router)


@app.get("/health")
async def health():
    global _shutdown_task
    if _shutdown_task and not _shutdown_task.done():
        _shutdown_task.cancel()
        _shutdown_task = None
    return {"status": "ok"}


@app.post("/api/shutdown")
async def shutdown():
    global _shutdown_task
    if _shutdown_task and not _shutdown_task.done():
        _shutdown_task.cancel()

    async def _delayed_exit():
        await asyncio.sleep(SHUTDOWN_DELAY)
        import sys
        sys.exit(0)

    _shutdown_task = asyncio.create_task(_delayed_exit())
    return {"status": "shutting_down"}
