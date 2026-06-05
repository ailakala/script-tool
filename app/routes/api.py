import json
import asyncio
from dataclasses import asdict
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse, PlainTextResponse
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import Project, PipelineRun, StageCache
from app.pipeline.executor import (run_pipeline, compute_input_hash,
    run_stage_0, run_stage_1, run_stage_2, run_stage_3, run_stage_4, run_stage_5)
from app.pipeline.stage0_preprocess import PreprocessResult, Chapter
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


@router.post("/projects/{project_id}/run-stage/{stage}")
async def run_single_stage(project_id: str, stage: int, request: Request,
                           db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "项目不存在")

    config = project.config()
    config["script_type"] = project.script_type

    meta = {
        "title": project.title,
        "source_novel": project.source_novel,
        "source_author": project.source_author,
        "script_type": project.script_type,
        "version": "0.1.0",
        "created_at": project.created_at,
        "language": "zh-CN",
    }

    run = db.query(PipelineRun).filter(
        PipelineRun.project_id == project_id
    ).order_by(PipelineRun.started_at.desc()).first()

    if not run:
        run = PipelineRun(project_id=project_id, started_at="")
        db.add(run)
        db.commit()

    project.status = "processing"
    run.paused = 0
    run.paused_at_stage = None
    db.commit()

    run_id = run.id  # save before detach
    body_data = await request.json()
    input_text = body_data.get("text", "")

    async def event_stream():
        queue: asyncio.Queue = asyncio.Queue()

        async def notify(msg):
            await queue.put({
                "project_id": project_id,
                "current_stage": stage,
                "stage_status": {stage: "running"},
                "message": msg,
            })

        async def cache_get(pid, stg, input_hash):
            row = db.query(StageCache).filter(
                StageCache.project_id == pid,
                StageCache.stage == stg,
                StageCache.input_hash == input_hash,
            ).first()
            if row and row.output_json:
                try:
                    return _deserialize_stage_result(stg, row.output_json)
                except Exception:
                    return None
            return None

        async def cache_put(pid, stg, input_hash, result):
            existing = db.query(StageCache).filter(
                StageCache.project_id == pid,
                StageCache.stage == stg,
                StageCache.input_hash == input_hash,
            ).first()
            if not existing:
                cache = StageCache(
                    project_id=pid, stage=stg,
                    input_hash=input_hash,
                    output_json=_serialize_stage_result(result),
                )
                db.add(cache)
                db.commit()

        async def run_task():
            provider = None  # use default from factory

            if stage == 0:
                if not input_text:
                    raise ValueError("请提供小说文本")
                return await run_stage_0(project_id, input_text, notify, cache_get, cache_put)

            elif stage == 1:
                s0 = _get_latest_cached(db, project_id, 0)
                if s0 is None:
                    raise ValueError("请先运行 Stage 0")
                if not input_text:
                    raise ValueError("请提供小说文本")
                return await run_stage_1(project_id, input_text, s0.chapters, provider, notify, cache_get, cache_put)

            elif stage == 2:
                s1 = _get_latest_cached(db, project_id, 1)
                if s1 is None:
                    raise ValueError("请先运行 Stage 1")
                return await run_stage_2(project_id, s1, provider, notify, cache_get, cache_put)

            elif stage == 3:
                s2 = _get_latest_cached(db, project_id, 2)
                if s2 is None:
                    raise ValueError("请先运行 Stage 2")
                return await run_stage_3(project_id, s2, config, provider, notify, cache_get, cache_put)

            elif stage == 4:
                s2 = _get_latest_cached(db, project_id, 2)
                s3 = _get_latest_cached(db, project_id, 3)
                s0 = _get_latest_cached(db, project_id, 0)
                if s2 is None or s3 is None or s0 is None:
                    raise ValueError("请先运行 Stage 0-3")
                chapter_texts = {ch.index: ch.content for ch in s0.chapters}
                return await run_stage_4(project_id, s3, s2.characters, chapter_texts,
                                         provider, notify, cache_get, cache_put)

            elif stage == 5:
                s2 = _get_latest_cached(db, project_id, 2)
                s3 = _get_latest_cached(db, project_id, 3)
                s4 = _get_latest_cached(db, project_id, 4)
                if s2 is None or s3 is None or s4 is None:
                    raise ValueError("请先运行 Stage 0-4")
                return await run_stage_5(project_id, meta, config, s2, s3, s4,
                                         notify, cache_get, cache_put)

            raise ValueError(f"未知 stage: {stage}")

        task = asyncio.create_task(run_task())

        while not task.done() or not queue.empty():
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=0.5)
                yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"

        try:
            result = task.result()
        except Exception as e:
            run_obj = db.query(PipelineRun).filter(PipelineRun.id == run_id).first()
            if run_obj:
                run_obj.error_message = str(e)
                run_obj.stage_status_json = json.dumps({stage: "error"})
            project_obj = db.query(Project).filter(Project.id == project_id).first()
            if project_obj:
                project_obj.status = "error"
            db.commit()
            yield f"data: {json.dumps({'status': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
            return

        run_obj = db.query(PipelineRun).filter(PipelineRun.id == run_id).first()
        if run_obj:
            run_obj.current_stage = stage
            statuses = run_obj.stage_status()
            statuses[str(stage)] = "done"
            run_obj.set_stage_status(statuses)

            if stage in (1, 2, 3):
                run_obj.paused = 1
                run_obj.paused_at_stage = stage
            else:
                run_obj.paused = 0
                run_obj.paused_at_stage = None

        project_obj = db.query(Project).filter(Project.id == project_id).first()
        if project_obj:
            if stage in (1, 2, 3):
                project_obj.status = "paused"
            else:
                project_obj.status = "done"

        db.commit()

        final_msg = {"status": "complete", "stage": stage}
        if stage == 5 and hasattr(result, 'yaml_text'):
            final_msg["yaml_text"] = result.yaml_text
        yield f"data: {json.dumps(final_msg, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/projects/{project_id}/resume")
async def resume_pipeline(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "项目不存在")

    run = db.query(PipelineRun).filter(
        PipelineRun.project_id == project_id
    ).order_by(PipelineRun.started_at.desc()).first()

    if not run or not run.paused:
        raise HTTPException(400, "没有暂停的流水线")

    next_stage = (run.paused_at_stage or 0) + 1
    if next_stage > 5:
        raise HTTPException(400, "流水线已完成")

    return {"next_stage": next_stage, "project_id": project_id}


def _get_latest_cached(db: Session, project_id: str, stage: int):
    """Retrieve the latest cached result for a given project+stage."""
    row = db.query(StageCache).filter(
        StageCache.project_id == project_id,
        StageCache.stage == stage,
    ).order_by(StageCache.created_at.desc()).first()
    if row and row.output_json:
        try:
            return _deserialize_stage_result(stage, row.output_json)
        except Exception:
            return None
    return None


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
    if stage == 0:
        result = PreprocessResult(**{k: v for k, v in d.items() if k != "chapters"})
        result.chapters = [Chapter(**c) for c in d.get("chapters", [])]
        return result
    elif stage == 1:
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
