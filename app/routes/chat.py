"""AI chat endpoint with SSE streaming."""

import json

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from fastapi import Depends

from app.db import get_db
from app.models import Project
from app.ai.factory import create_ai_provider
from app import config as app_config

router = APIRouter(prefix="/api")

CHAT_SYSTEM_PROMPT = (
    "You are a professional script writing assistant. "
    "Help users with translation, polishing, summarization, "
    "and script writing questions. Reply in Chinese by default."
)

# Provider → (env var name, friendly name for error messages)
PROVIDER_KEY_MAP = {
    "claude":   (app_config.ANTHROPIC_API_KEY, "SCRIPT_TOOL_ANTHROPIC_API_KEY"),
    "openai":   (app_config.OPENAI_API_KEY,    "SCRIPT_TOOL_OPENAI_API_KEY"),
    "deepseek": (app_config.DEEPSEEK_API_KEY,  "SCRIPT_TOOL_DEEPSEEK_API_KEY"),
    "gemini":   (app_config.GEMINI_API_KEY,    "SCRIPT_TOOL_GEMINI_API_KEY"),
    "local":    (True, ""),  # local always considered "configured"
}


@router.post("/projects/{project_id}/chat")
async def chat(project_id: str, request: Request, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "Project not found")

    body = await request.json()
    message = body.get("message", "").strip()
    model_override = body.get("model", "").strip() or None

    if not message:
        raise HTTPException(400, "Message cannot be empty")

    # Resolve provider
    provider_key = model_override or app_config.AI_PROVIDER
    try:
        provider = create_ai_provider(provider=model_override)
    except ValueError:
        return StreamingResponse(
            _error_stream(f"未知模型 '{model_override}'，请选择可用模型"),
            media_type="text/event-stream",
        )

    # Check if API key is configured
    key_info = PROVIDER_KEY_MAP.get(provider_key)
    if key_info and not key_info[0]:
        return StreamingResponse(
            _error_stream(f"未配置 {key_info[1]}，请在 .env 文件中设置该环境变量后重启"),
            media_type="text/event-stream",
        )

    async def event_stream():
        full_text = ""
        try:
            async for chunk in provider.generate_stream(message, system=CHAT_SYSTEM_PROMPT):
                full_text += chunk
                yield f"data: {json.dumps({'delta': chunk}, ensure_ascii=False)}\n\n"
        except Exception as e:
            if not full_text:
                err_msg = str(e)
                # 友好的常见错误翻译
                if "401" in err_msg or "Unauthorized" in err_msg or "Incorrect API key" in err_msg:
                    err_msg = f"API Key 无效或未配置，请检查 {key_info[1] if key_info else '对应环境变量'}"
                yield f"data: {json.dumps({'error': err_msg}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _error_stream(message: str):
    """Generate a single-error SSE stream."""
    async def gen():
        yield f"data: {json.dumps({'error': message}, ensure_ascii=False)}\n\n"
    return gen()
