from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import Project, Requirement
from app.services.ai_service import build_requirement_analysis
from app.services.xmind_markdown_service import generate_structured_cases, generate_xmind_markdown

router = APIRouter(tags=["requirements-html"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _decode_markdown_bytes(raw_bytes: bytes) -> str:
    if not raw_bytes:
        return ""

    for encoding in ("utf-8", "utf-8-sig", "gbk", "gb18030", "utf-16", "utf-16-le", "utf-16-be"):
        try:
            text = raw_bytes.decode(encoding)
            if text.strip():
                return text
        except UnicodeDecodeError:
            continue

    return raw_bytes.decode("utf-8", errors="ignore").strip()


def _extract_title_from_markdown(filename: str, content: str) -> str:
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            title = line.lstrip("#").strip()
            if title:
                return title
        cleaned = line.lstrip("-*0123456789.、 ").strip()
        if cleaned:
            return cleaned[:120]

    base_name = Path(filename or "未命名需求").stem.strip()
    return base_name or "未命名需求"


def _new_requirement_context(
    request: Request,
    projects: list[Project],
    *,
    selected_project_id: int | None = None,
    error_message: str = "",
    form_data: dict[str, str] | None = None,
):
    return {
        "request": request,
        "projects": projects,
        "selected_project_id": selected_project_id,
        "error_message": error_message,
        "form_data": form_data or {},
    }


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
        _new_requirement_context(
            request,
            projects,
            selected_project_id=project_id,
        ),
    )


@router.post("/requirements/", name="requirement_create")
async def create_requirement(
    request: Request,
    project_id: int = Form(...),
    markdown_file: UploadFile | None = File(default=None),
    markdown_filename_text: str = Form(default=""),
    markdown_content_text: str = Form(default=""),
    fallback_content: str = Form(default=""),
    db: Session = Depends(get_db),
):
    projects = db.query(Project).order_by(Project.created_at.desc()).all()
    project = db.query(Project).filter(Project.id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")

    uploaded_filename = ""
    uploaded_content = ""
    if markdown_file is not None and markdown_file.filename:
        uploaded_filename = markdown_file.filename.strip()
        raw_bytes = await markdown_file.read()
        uploaded_content = _decode_markdown_bytes(raw_bytes)

    persisted_filename = (markdown_filename_text or "").strip()
    persisted_content = (markdown_content_text or "").strip()
    pasted_content = (fallback_content or "").strip()

    final_filename = uploaded_filename or persisted_filename
    final_content = uploaded_content or persisted_content or pasted_content

    if not final_content:
        return templates.TemplateResponse(
            request,
            "requirements/new.html",
            _new_requirement_context(
                request,
                projects,
                selected_project_id=project_id,
                error_message="请上传 Markdown 文件，或直接粘贴需求正文。",
                form_data={
                    "project_id": str(project_id),
                    "markdown_filename_text": final_filename,
                    "markdown_content_text": persisted_content,
                    "fallback_content": pasted_content,
                },
            ),
            status_code=400,
        )

    title = _extract_title_from_markdown(final_filename, final_content)
    analysis_payload = build_requirement_analysis(final_content, title=title)
    parsed_points = [
        point["title"]
        for point in analysis_payload.get("selected_points", [])
        if isinstance(point, dict) and point.get("title")
    ]

    requirement = Requirement(
        project_id=project_id,
        title=title.strip(),
        content=final_content.strip(),
        parsed_points=parsed_points,
        analysis_payload=analysis_payload,
        analysis_status="draft",
        last_analyzed_at=datetime.utcnow(),
    )
    db.add(requirement)
    db.commit()
    db.refresh(requirement)

    return RedirectResponse(url=f"/requirements/{requirement.id}", status_code=303)


@router.post("/requirements/{requirement_id}/reanalyze", name="requirement_reanalyze")
def reanalyze_requirement(
    requirement_id: int,
    use_llm: bool = Form(default=False),
    db: Session = Depends(get_db),
):
    requirement = db.query(Requirement).filter(Requirement.id == requirement_id).first()
    if requirement is None:
        raise HTTPException(status_code=404, detail="Requirement not found.")

    analysis_payload = build_requirement_analysis(
        requirement.content,
        title=requirement.title,
        use_llm=use_llm,
    )
    requirement.analysis_payload = analysis_payload
    requirement.parsed_points = [
        point["title"]
        for point in analysis_payload.get("selected_points", [])
        if isinstance(point, dict) and point.get("title")
    ]
    requirement.last_analyzed_at = datetime.utcnow()
    db.commit()

    return RedirectResponse(url=f"/requirements/{requirement_id}?reanalyzed=1", status_code=303)


@router.get("/requirements/{requirement_id}/xmind-markdown", name="requirement_xmind_markdown")
def export_requirement_xmind_markdown(requirement_id: int, db: Session = Depends(get_db)) -> PlainTextResponse:
    requirement = db.query(Requirement).filter(Requirement.id == requirement_id).first()
    if requirement is None:
        raise HTTPException(status_code=404, detail="Requirement not found.")

    markdown = generate_xmind_markdown(
        requirement.title,
        requirement.content,
        analysis_payload=requirement.analysis_payload,
    )
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

    estimated_case_count = len(
        generate_structured_cases(
            requirement.title,
            requirement.content,
            analysis_payload=requirement.analysis_payload,
        )
    )

    return templates.TemplateResponse(
        request,
        "requirements/detail.html",
        {
            "request": request,
            "requirement": requirement,
            "generated": generated,
            "imported": imported,
            "reanalyzed": reanalyzed,
            "estimated_case_count": estimated_case_count,
        },
    )