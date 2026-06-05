import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = BASE_DIR / "storage"
UPLOADS_DIR = STORAGE_DIR / "uploads"
CACHE_DIR = STORAGE_DIR / "cache"
DATABASE_URL = f"sqlite:///{STORAGE_DIR / 'db.sqlite'}"

for d in [STORAGE_DIR, UPLOADS_DIR, CACHE_DIR]:
    d.mkdir(parents=True, exist_ok=True)

AI_PROVIDER = os.getenv("SCRIPT_TOOL_AI_PROVIDER", "claude")
AI_MODEL = os.getenv("SCRIPT_TOOL_AI_MODEL", "claude-sonnet-4-6")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
LOCAL_LLM_URL = os.getenv("SCRIPT_TOOL_LOCAL_LLM_URL", "http://localhost:8000/v1")

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_PASTE_CHARS = 500_000
