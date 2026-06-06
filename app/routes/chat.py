"""AI chat endpoint with SSE streaming."""

import json

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from fastapi import Depends

from app.db import get_db
from app.models import Project
from app.ai.factory import create_ai_provider

router = APIRouter(prefix="/api")

CHAT_SYSTEM_PROMPT = (
    "You are a professional script writing assistant. "
    "Help users with translation, polishing, summarization, "
    "and script writing questions. Reply in Chinese by default."
)


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

    try:
        provider = create_ai_provider(provider=model_override)
    except ValueError:
        provider = create_ai_provider()

    async def event_stream():
        full_text = ""
        try:
            async for chunk in provider.generate_stream(message, system=CHAT_SYSTEM_PROMPT):
                full_text += chunk
                yield f"data: {json.dumps({'delta': chunk}, ensure_ascii=False)}\n\n"
        except Exception as e:
            if not full_text:
                yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
