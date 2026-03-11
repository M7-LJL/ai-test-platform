from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import Project, Requirement
from app.services.ai_service import analyze_requirement
from app.services.xmind_markdown_service import generate_structured_cases, generate_xmind_markdown


router = APIRouter(tags=["requirements-html"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/requirements/new", name="requirement_new")
def new_requirement_page(
    request: Request,
    project_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    projects = db.query(Project).order_by(Project.created_at.desc()).all()
    return templates.TemplateResponse(
        request,
        "requirements/new.html",
        {
            "projects": projects,
            "selected_project_id": project_id,
        },
    )


@router.post("/requirements/", name="requirement_create")
def create_requirement(
    project_id: int = Form(...),
    title: str = Form(...),
    content: str = Form(...),
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")

    normalized_title = title.strip()
    normalized_content = content.strip()
    if not normalized_title or not normalized_content:
        raise HTTPException(status_code=400, detail="Title and content are required.")

    requirement = Requirement(
        project_id=project_id,
        title=normalized_title,
        content=normalized_content,
        parsed_points=analyze_requirement(normalized_content),
    )
    db.add(requirement)
    db.commit()
    db.refresh(requirement)

    return RedirectResponse(url=f"/requirements/{requirement.id}", status_code=303)


@router.post("/requirements/{requirement_id}/reanalyze", name="requirement_reanalyze")
def reanalyze_requirement(requirement_id: int, db: Session = Depends(get_db)):
    requirement = db.query(Requirement).filter(Requirement.id == requirement_id).first()
    if requirement is None:
        raise HTTPException(status_code=404, detail="Requirement not found.")

    requirement.parsed_points = analyze_requirement(requirement.content)
    db.commit()

    return RedirectResponse(url=f"/requirements/{requirement_id}?reanalyzed=1", status_code=303)


@router.get("/requirements/{requirement_id}/xmind-markdown", name="requirement_xmind_markdown")
def export_requirement_xmind_markdown(requirement_id: int, db: Session = Depends(get_db)) -> PlainTextResponse:
    requirement = db.query(Requirement).filter(Requirement.id == requirement_id).first()
    if requirement is None:
        raise HTTPException(status_code=404, detail="Requirement not found.")

    markdown = generate_xmind_markdown(requirement.title, requirement.content)
    safe_title = f"requirement_{requirement_id}_xmind"
    headers = {
        "Content-Disposition": f'attachment; filename="{safe_title}.md"',
    }
    return PlainTextResponse(content=markdown, media_type="text/markdown; charset=utf-8", headers=headers)


@router.get("/requirements/{requirement_id}", name="requirement_detail")
def requirement_detail(
    requirement_id: int,
    request: Request,
    generated: int | None = Query(default=None),
    imported: int | None = Query(default=None),
    reanalyzed: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    requirement = (
        db.query(Requirement)
        .options(
            joinedload(Requirement.project),
            joinedload(Requirement.test_cases),
        )
        .filter(Requirement.id == requirement_id)
        .first()
    )
    if requirement is None:
        raise HTTPException(status_code=404, detail="Requirement not found.")

    estimated_case_count = len(generate_structured_cases(requirement.title, requirement.content))

    return templates.TemplateResponse(
        request,
        "requirements/detail.html",
        {
            "requirement": requirement,
            "generated": generated,
            "imported": imported,
            "reanalyzed": reanalyzed,
            "estimated_case_count": estimated_case_count,
        },
    )
