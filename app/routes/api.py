import json
import asyncio
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse, PlainTextResponse
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import Project, PipelineRun
from app.pipeline.executor import run_pipeline

router = APIRouter(prefix="/api")

@router.post("/projects")
async def create_project(
    title: str = Form(...),
    source_novel: str = Form(""),
    source_author: str = Form(""),
    script_type: str = Form("other"),
    config_json: str = Form("{}"),
    db: Session = Depends(get_db),
):
    project = Project(
        title=title, source_novel=source_novel, source_author=source_author,
        script_type=script_type, config_json=config_json,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return {"id": project.id, "title": project.title}

@router.post("/projects/{project_id}/upload")
async def upload_file(project_id: str, file: UploadFile = File(...),
                      db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "项目不存在")

    content = await file.read()
    filename = file.filename or "upload.txt"

    if filename.endswith(".docx"):
        from app.pipeline.stage0_preprocess import preprocess_docx
        result = preprocess_docx(content)
    elif filename.endswith(".md"):
        text = content.decode("utf-8", errors="replace")
        from app.pipeline.stage0_preprocess import preprocess_markdown
        result = preprocess_markdown(text)
    else:
        text = content.decode("utf-8", errors="replace")
        from app.pipeline.stage0_preprocess import preprocess_text
        result = preprocess_text(text)

    return {
        "filename": filename,
        "chapters": len(result.chapters),
        "total_chars": result.total_chars,
        "title": result.title,
        "errors": result.errors,
    }

@router.post("/projects/{project_id}/paste")
async def paste_text(project_id: str, request: Request,
                     db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "项目不存在")

    body = await request.json()
    text = body.get("text", "")
    if len(text) > 500_000:
        raise HTTPException(400, "文本超过 50 万字上限")

    from app.pipeline.stage0_preprocess import preprocess_text
    result = preprocess_text(text)

    return {
        "chapters": len(result.chapters),
        "total_chars": result.total_chars,
        "title": result.title,
        "errors": result.errors,
        "text": text,
    }

@router.post("/projects/{project_id}/run")
async def run_pipeline_endpoint(project_id: str, request: Request,
                                db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "项目不存在")

    body = await request.json()
    text = body.get("text", "")
    if not text:
        raise HTTPException(400, "请先上传或粘贴小说文本")

    meta = {
        "title": project.title,
        "source_novel": project.source_novel,
        "source_author": project.source_author,
        "script_type": project.script_type,
        "version": "0.1.0",
        "created_at": project.created_at,
        "language": "zh-CN",
    }
    config = project.config()
    config["script_type"] = project.script_type

    run = PipelineRun(project_id=project_id)
    project.status = "processing"
    db.add(run)
    db.commit()

    async def event_stream():
        queue: asyncio.Queue = asyncio.Queue()
        pipeline_state = None

        async def progress_callback(msg):
            await queue.put(msg)

        async def run_pipeline_task():
            nonlocal pipeline_state
            return await run_pipeline(project_id, text, meta, config,
                                      progress_callback=progress_callback)

        task = asyncio.create_task(run_pipeline_task())

        while not task.done() or not queue.empty():
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=0.5)
                yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"

        pipeline_state = task.result()

        project.status = "done" if not pipeline_state.errors else "error"
        db.commit()

        final_msg = {
            "status": "complete",
            "errors": pipeline_state.errors,
            "yaml_text": pipeline_state.stage_results.get("assembly").yaml_text if pipeline_state.stage_results.get("assembly") else "",
        }
        yield f"data: {json.dumps(final_msg, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")

@router.get("/projects/{project_id}/script.yaml")
async def download_script(project_id: str, yaml_text: str = "",
                          db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "项目不存在")
    return PlainTextResponse(yaml_text, media_type="application/x-yaml",
                             headers={"Content-Disposition": f"attachment; filename={project.title}.yaml"})

@router.delete("/projects/{project_id}")
async def delete_project(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "项目不存在")
    db.delete(project)
    db.commit()
    return {"deleted": project_id}
