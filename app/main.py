from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.config import STORAGE_DIR, UPLOADS_DIR, CACHE_DIR
from app.db import init_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    for d in [STORAGE_DIR, UPLOADS_DIR, CACHE_DIR]:
        d.mkdir(parents=True, exist_ok=True)
    init_db()
    yield

app = FastAPI(title="AI Script Tool", version="0.1.0", lifespan=lifespan)

@app.get("/health")
async def health():
    return {"status": "ok"}
