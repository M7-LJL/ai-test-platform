from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import Project
from app.services.report_service import generate_report


router = APIRouter(tags=["projects-html"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/projects", name="project_list")
def list_projects_page(request: Request, db: Session = Depends(get_db)):
    projects = db.query(Project).order_by(Project.created_at.desc()).all()
    return templates.TemplateResponse(
        request,
        "projects/list.html",
        {"projects": projects},
    )


@router.get("/projects/new", name="project_new")
def new_project_page(request: Request):
    return templates.TemplateResponse(request, "projects/new.html", {})


@router.post("/projects/new", name="project_create")
def create_project_page(
    name: str = Form(...),
    description: str = Form(default=""),
    db: Session = Depends(get_db),
):
    normalized_name = name.strip()
    normalized_description = description.strip() or None

    if not normalized_name:
        raise HTTPException(status_code=400, detail="Project name is required.")

    project = Project(name=normalized_name, description=normalized_description)
    db.add(project)
    db.commit()
    db.refresh(project)

    return RedirectResponse(url="/projects", status_code=303)


@router.post("/projects/{project_id}/delete", name="project_delete")
def delete_project_page(project_id: int, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")

    # ORM cascade on Project relationships removes linked requirements and test cases.
    db.delete(project)
    db.commit()

    return RedirectResponse(url="/projects", status_code=303)


@router.get("/projects/{project_id}", name="project_detail")
def project_detail_page(project_id: int, request: Request, db: Session = Depends(get_db)):
    project = (
        db.query(Project)
        .options(
            joinedload(Project.requirements),
            joinedload(Project.test_cases),
        )
        .filter(Project.id == project_id)
        .first()
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")

    requirements = sorted(project.requirements, key=lambda item: item.created_at, reverse=True)
    test_cases = sorted(project.test_cases, key=lambda item: item.created_at, reverse=True)
    return templates.TemplateResponse(
        request,
        "projects/detail.html",
        {
            "project": project,
            "requirements": requirements,
            "test_cases": test_cases,
        },
    )


@router.get("/projects/{id}/report", response_class=HTMLResponse, name="project_report")
def project_report_page(id: int) -> HTMLResponse:
    try:
        return HTMLResponse(content=generate_report(id, export_url=f"/projects/{id}/report/export"))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/projects/{id}/report/export", name="project_report_export")
def export_project_report(id: int) -> Response:
    try:
        content = generate_report(id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return Response(
        content=content,
        media_type="text/html",
        headers={"Content-Disposition": f'attachment; filename="project_{id}_report.html"'},
    )
