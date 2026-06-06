import json
import asyncio
from dataclasses import asdict
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse, PlainTextResponse, HTMLResponse
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import Project, PipelineRun, StageCache
from app.pipeline.executor import (run_pipeline, compute_input_hash,
    run_stage_0, run_stage_1, run_stage_2, run_stage_3, run_stage_4, run_stage_5)
from app.config import TEXT_STORE_DIR
from app.pipeline.stage0_preprocess import PreprocessResult, Chapter
from app.pipeline.stage1_chapter_analysis import ChapterAnalysis
from app.pipeline.stage2_cross_chapter_synthesis import GlobalAnalysis
from app.pipeline.stage3_script_structure import ScriptStructure, ScenePlan
from app.pipeline.stage4_scene_generation import GeneratedScene

router = APIRouter(prefix="/api")


def _text_path(project_id: str) -> str:
    return TEXT_STORE_DIR / f"{project_id}.txt"


def _save_text(project_id: str, text: str):
    _text_path(project_id).write_text(text, encoding="utf-8")


def _load_text(project_id: str) -> str:
    p = _text_path(project_id)
    if p.exists():
        return p.read_text(encoding="utf-8")
    return ""


def _render_import_result(title: str, stats: dict) -> HTMLResponse:
    """Generate HTML status card for HTMX upload/paste responses."""
    errors_html = ""
    if stats.get("errors"):
        items = "".join(f"<li>{e}</li>" for e in stats["errors"])
        errors_html = (
            f'<div style="margin-top:0.75em;padding:0.75em;background:#fef3c7;'
            f'border-radius:6px;font-size:0.9em;color:#92400e">'
            f'<strong>⚠ 警告：</strong><ul style="margin:0.25em 0 0;padding-left:1.25em">{items}</ul>'
            f'</div>'
        )

    items_html = "".join(
        f"<div style=\"display:flex;justify-content:space-between;padding:0.4em 0;border-bottom:1px solid #f3f4f6\">"
        f"<span style=\"color:#6b7280\">{k}</span><strong>{v}</strong></div>"
        for k, v in stats.get("items", [])
    )

    return HTMLResponse(content=f"""<div id="upload-result" style="background:#f0fdf4;border:1px solid #86efac;border-radius:8px;padding:1em;margin-top:0.5em;animation:scaleIn 0.3s ease">
<div style="display:flex;align-items:center;gap:0.5em;margin-bottom:0.75em">
    <span style="font-size:1.5em">{stats.get("icon", "✅")}</span>
    <strong style="font-size:1.05em;color:#166534">{title}</strong>
</div>
{items_html}
{errors_html}
</div>""")

@router.post("/projects")
async def create_project(
    request: Request,
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

    # HTMX request → return HTML modal fragment
    if request.headers.get("HX-Request"):
        return HTMLResponse(content=f"""<div id="create-modal-overlay" style="position:fixed;inset:0;background:rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;z-index:9999;animation:fadeIn 0.2s ease">
<div id="create-modal" style="background:#fff;border-radius:12px;padding:2em;text-align:center;max-width:400px;box-shadow:0 20px 60px rgba(0,0,0,0.3);animation:scaleIn 0.3s ease">
<img src="https://media.tenor.com/WQ3LQ6sUkQcAAAAi/peach-goma-pc.gif" alt="celebrate" style="width:120px;height:120px;border-radius:12px;margin-bottom:0.5em">
<h2 style="margin:0.5em 0;font-size:1.2em">项目创建成功！🎉</h2>
<p style="color:#6b7280;margin-bottom:1.5em">「{title}」已就绪</p>
<div style="display:flex;gap:0.5em;justify-content:center">
<a href="/projects/{project.id}" style="display:inline-block;padding:0.5em 1.25em;background:var(--accent, #2563eb);color:#fff;border-radius:6px;text-decoration:none;font-size:0.95em">前往项目工作台</a>
<button onclick="document.getElementById('create-modal-overlay').remove()" style="padding:0.5em 1.25em;background:#e5e7eb;color:#1a1a1a;border:none;border-radius:6px;cursor:pointer;font-size:0.95em">✕ 关闭</button>
</div>
</div>
</div>
<script>
setTimeout(function() {{
    var overlay = document.getElementById('create-modal-overlay');
    if (overlay) {{
        overlay.style.transition = 'opacity 0.3s';
        overlay.style.opacity = '0';
        setTimeout(function() {{ if (overlay.parentNode) overlay.remove(); }}, 300);
    }}
}}, 3000);
</script>
""")

    return {"id": project.id, "title": project.title}

@router.post("/projects/{project_id}/upload")
async def upload_file(project_id: str, request: Request,
                      file: UploadFile = File(...),
                      db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "项目不存在")

    content = await file.read()
    filename = file.filename or "upload.txt"

    if filename.endswith(".docx"):
        from app.pipeline.stage0_preprocess import preprocess_docx
        result = preprocess_docx(content)
        text = ""
    elif filename.endswith(".md"):
        text = content.decode("utf-8", errors="replace")
        from app.pipeline.stage0_preprocess import preprocess_markdown
        result = preprocess_markdown(text)
    else:
        text = content.decode("utf-8", errors="replace")
        from app.pipeline.stage0_preprocess import preprocess_text
        result = preprocess_text(text)

    # Save text so pipeline can read it later
    _save_text(project_id, text)

    resp_data = {
        "filename": filename,
        "chapters": len(result.chapters),
        "total_chars": result.total_chars,
        "title": result.title,
        "errors": result.errors,
    }

    if request.headers.get("HX-Request"):
        return _render_import_result("导入成功！", {
            "icon": "✅",
            "items": [
                ("文件名", filename),
                ("章节数", f"{len(result.chapters)} 章"),
                ("总字数", f"{result.total_chars:,}"),
            ],
            "errors": result.errors,
        })

    return resp_data

@router.post("/projects/{project_id}/paste")
async def paste_text(project_id: str, request: Request,
                     db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "项目不存在")

    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
        text = body.get("text", "")
    else:
        form = await request.form()
        text = form.get("text", "")
    if len(text) > 500_000:
        raise HTTPException(400, "文本超过 50 万字上限")

    from app.pipeline.stage0_preprocess import preprocess_text
    result = preprocess_text(text)

    # Save text so pipeline can read it later
    _save_text(project_id, text)

    resp_data = {
        "chapters": len(result.chapters),
        "total_chars": result.total_chars,
        "title": result.title,
        "errors": result.errors,
        "text": text,
    }

    if request.headers.get("HX-Request"):
        return _render_import_result("解析完成！", {
            "icon": "✅",
            "items": [
                ("章节数", f"{len(result.chapters)} 章"),
                ("总字数", f"{result.total_chars:,}"),
            ],
            "errors": result.errors,
        })

    return resp_data

@router.post("/projects/{project_id}/run")
async def run_pipeline_endpoint(project_id: str, request: Request,
                                db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "项目不存在")

    body = await request.json()
    text = body.get("text", "") or _load_text(project_id)
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
                _inject_percent(msg)
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
    input_text = body_data.get("text", "") or _load_text(project_id)

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
                _inject_percent(msg)
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
async def download_script(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "项目不存在")

    # Read yaml_text from StageCache (stage 5)
    cache_row = db.query(StageCache).filter(
        StageCache.project_id == project_id,
        StageCache.stage == 5,
    ).order_by(StageCache.created_at.desc()).first()

    yaml_text = ""
    if cache_row and cache_row.output_json:
        try:
            data = json.loads(cache_row.output_json)
            yaml_text = data.get("yaml_text", "")
        except (json.JSONDecodeError, TypeError):
            pass

    if not yaml_text:
        raise HTTPException(404, "剧本 YAML 尚未生成，请先运行流水线")

    return PlainTextResponse(yaml_text, media_type="application/x-yaml",
                             headers={"Content-Disposition": f"attachment; filename={project.title}.yaml"})


@router.put("/projects/{project_id}/stage/5")
async def save_edited_script(project_id: str, request: Request,
                              db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "项目不存在")

    body = await request.json()
    yaml_text = body.get("yaml_text", "")

    cache_row = db.query(StageCache).filter(
        StageCache.project_id == project_id,
        StageCache.stage == 5,
    ).order_by(StageCache.created_at.desc()).first()

    if not cache_row:
        raise HTTPException(404, "剧本尚未生成，无法保存")

    # Update the yaml_text inside the cached output_json
    try:
        data = json.loads(cache_row.output_json)
    except (json.JSONDecodeError, TypeError):
        data = {}
    data["yaml_text"] = yaml_text
    cache_row.output_json = json.dumps(data, ensure_ascii=False)
    db.commit()

    return {"status": "saved"}


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


def _inject_percent(msg: dict):
    """Add percent field based on completed stages."""
    stage_status = msg.get("stage_status", {})
    if stage_status:
        done = sum(1 for v in stage_status.values() if v == "done")
        current = msg.get("current_stage", -1)
        if done == 0 and current >= 0:
            # Step-by-step mode: only current stage in status, assume previous stages done
            msg["percent"] = min(current * 100 // 6, 100)
        else:
            msg["percent"] = min(done * 100 // 6, 100)
    elif msg.get("status") == "complete" and "stage" in msg:
        # Single-stage completion message
        msg["percent"] = (msg["stage"] + 1) * 100 // 6
