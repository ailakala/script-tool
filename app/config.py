import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
STORAGE_DIR = BASE_DIR / "storage"
UPLOADS_DIR = STORAGE_DIR / "uploads"
CACHE_DIR = STORAGE_DIR / "cache"
TEXT_STORE_DIR = STORAGE_DIR / "texts"
# 跨文件系统检测：代码在 WSL 路径但 Python 在 Windows 上运行时，
# SQLite 无法在 UNC 路径上加锁，自动重定向到 Windows 本机路径
_storage_path = str(STORAGE_DIR / "db.sqlite")
if _storage_path.startswith(r"\\wsl.localhost") or _storage_path.startswith("//wsl.localhost"):
    _win_user = os.environ.get("USERNAME", "default")
    DATABASE_URL = os.getenv("SCRIPT_TOOL_DATABASE_URL", f"sqlite:///C:/Users/{_win_user}/script_tool.db")
else:
    DATABASE_URL = os.getenv("SCRIPT_TOOL_DATABASE_URL", f"sqlite:///{STORAGE_DIR / 'db.sqlite'}")

AI_PROVIDER = os.getenv("SCRIPT_TOOL_AI_PROVIDER", "claude")
AI_MODEL = os.getenv("SCRIPT_TOOL_AI_MODEL", "claude-sonnet-4-6")
ANTHROPIC_API_KEY = os.getenv("SCRIPT_TOOL_ANTHROPIC_API_KEY")
OPENAI_API_KEY = os.getenv("SCRIPT_TOOL_OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("SCRIPT_TOOL_OPENAI_BASE_URL")
DEEPSEEK_API_KEY = os.getenv("SCRIPT_TOOL_DEEPSEEK_API_KEY")
DEEPSEEK_MODEL = os.getenv("SCRIPT_TOOL_DEEPSEEK_MODEL", "deepseek-chat")
LOCAL_LLM_URL = os.getenv("SCRIPT_TOOL_LOCAL_LLM_URL", "http://localhost:1234/v1")
LOCAL_LLM_API_KEY = os.getenv("SCRIPT_TOOL_LOCAL_LLM_API_KEY", "not-needed")

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_PASTE_CHARS = 500_000
