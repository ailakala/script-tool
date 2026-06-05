import json
import asyncio
from dataclasses import asdict
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse, PlainTextResponse
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import Project, PipelineRun, StageCache
from app.pipeline.executor import run_pipeline, compute_input_hash
from app.pipeline.stage1_chapter_analysis import ChapterAnalysis
from app.pipeline.stage2_cross_chapter_synthesis import GlobalAnalysis
from app.pipeline.stage3_script_structure import ScriptStructure, ScenePlan
from app.pipeline.stage4_scene_generation import GeneratedScene

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

            async def cache_get(pid, stage, input_hash):
                row = db.query(StageCache).filter(
                    StageCache.project_id == pid,
                    StageCache.stage == stage,
                    StageCache.input_hash == input_hash,
                ).first()
                if row and row.output_json:
                    try:
                        return _deserialize_stage_result(stage, row.output_json)
                    except Exception:
                        return None
                return None

            async def cache_put(pid, stage, input_hash, result):
                existing = db.query(StageCache).filter(
                    StageCache.project_id == pid,
                    StageCache.stage == stage,
                    StageCache.input_hash == input_hash,
                ).first()
                if not existing:
                    cache = StageCache(
                        project_id=pid, stage=stage,
                        input_hash=input_hash,
                        output_json=_serialize_stage_result(result),
                    )
                    db.add(cache)
                    db.commit()

            return await run_pipeline(project_id, text, meta, config,
                                      progress_callback=progress_callback,
                                      cache_get=cache_get, cache_put=cache_put)

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

# ── Cache helpers ────────────────────────────────────────────────────

def _serialize_stage_result(result) -> str:
    if isinstance(result, list):
        return json.dumps([asdict(item) for item in result], ensure_ascii=False, default=str)
    return json.dumps(asdict(result), ensure_ascii=False, default=str)


def _deserialize_stage_result(stage: int, data: str):
    d = json.loads(data)
    if stage == 1:
        return [ChapterAnalysis(**item) for item in d]
    elif stage == 2:
        return GlobalAnalysis(**d)
    elif stage == 3:
        structure = ScriptStructure(**{k: v for k, v in d.items() if k != "scenes"})
        structure.scenes = [ScenePlan(**s) for s in d.get("scenes", [])]
        return structure
    elif stage == 4:
        return [GeneratedScene(**item) for item in d]
    elif stage == 5:
        from app.pipeline.stage5_assembly import AssemblyResult
        return AssemblyResult(**d)
    return d


@router.get("/projects/{project_id}/stage/{stage}")
async def get_stage_result(project_id: str, stage: int, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "项目不存在")

    caches = db.query(StageCache).filter(
        StageCache.project_id == project_id,
        StageCache.stage == stage,
    ).order_by(StageCache.created_at.desc()).all()

    if not caches:
        return {"stage": stage, "status": "not_run", "data": None}

    latest = caches[0]
    try:
        data = json.loads(latest.output_json)
        return {
            "stage": stage,
            "status": "cached",
            "input_hash": latest.input_hash,
            "created_at": latest.created_at,
            "data": data,
        }
    except (json.JSONDecodeError, TypeError):
        return {"stage": stage, "status": "error", "data": None}


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "项目不存在")
    db.delete(project)
    db.commit()
    return {"deleted": project_id}
