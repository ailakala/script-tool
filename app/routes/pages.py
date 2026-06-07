from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import Project

router = APIRouter()


def _project_nav_info(db: Session, current_id: str = "") -> dict:
    """Return nav bar project count info for template rendering."""
    ordered = db.query(Project).order_by(Project.created_at.asc()).all()
    total = len(ordered)
    info = {"project_count": total}
    if total > 0 and current_id:
        for i, p in enumerate(ordered):
            if p.id == current_id:
                info["project_index"] = i + 1
                break
    return info


@router.get("/", response_class=HTMLResponse)
async def index(request: Request, db: Session = Depends(get_db)):
    projects = db.query(Project).order_by(Project.updated_at.desc()).all()
    return request.app.state.templates.TemplateResponse("index.html", {
        "request": request,
        "projects": projects,
        "project_count": len(projects),
    })

@router.get("/projects/new", response_class=HTMLResponse)
async def new_project(request: Request, db: Session = Depends(get_db)):
    total = db.query(Project).count()
    return request.app.state.templates.TemplateResponse("project_new.html", {
        "request": request,
        "project_count": total,
    })

@router.get("/projects/{project_id}", response_class=HTMLResponse)
async def project_workspace(project_id: str, request: Request, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return request.app.state.templates.TemplateResponse("404.html", {
            "request": request, "message": "项目不存在"
        }, status_code=404)
    return request.app.state.templates.TemplateResponse("project.html", {
        "request": request,
        "project": project,
        **_project_nav_info(db, project_id),
    })

@router.get("/projects/{project_id}/stage/{stage}", response_class=HTMLResponse)
async def stage_review(project_id: str, stage: int, request: Request, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return request.app.state.templates.TemplateResponse("404.html", {
            "request": request, "message": "项目不存在"
        }, status_code=404)
    return request.app.state.templates.TemplateResponse("stage_review.html", {
        "request": request,
        "project": project,
        "stage": stage,
        **_project_nav_info(db, project_id),
    })

@router.get("/projects/{project_id}/script", response_class=HTMLResponse)
async def script_view(project_id: str, request: Request, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return request.app.state.templates.TemplateResponse("404.html", {
            "request": request, "message": "项目不存在"
        }, status_code=404)
    return request.app.state.templates.TemplateResponse("script_view.html", {
        "request": request,
        "project": project,
        **_project_nav_info(db, project_id),
    })
