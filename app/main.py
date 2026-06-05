from fastapi import FastAPI
from app.config import STORAGE_DIR, UPLOADS_DIR, CACHE_DIR

app = FastAPI(title="AI Script Tool", version="0.1.0")

@app.on_event("startup")
async def startup():
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

@app.get("/health")
async def health():
    return {"status": "ok"}
