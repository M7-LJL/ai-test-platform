from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import Project, Requirement, RequirementReviewPoint
from app.services.ai_service import build_requirement_analysis, can_use_llm
from app.services.xmind_markdown_service import generate_structured_cases, generate_xmind_markdown

router = APIRouter(tags=["requirements-html"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

CATEGORY_LABELS = {
    "functional": "功能点",
    "boundary": "边界点",
    "exception": "异常点",
}


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


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\u3000", " ").split()).strip()


def _normalized_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        cleaned = _clean_text(item)
        if cleaned and cleaned not in items:
            items.append(cleaned)
    return items


def _analysis_payload_dict(requirement: Requirement) -> dict[str, Any]:
    return requirement.analysis_payload if isinstance(requirement.analysis_payload, dict) else {}


def _normalized_selected_points(payload: dict[str, Any]) -> list[dict[str, str]]:
    points = payload.get("selected_points", [])
    if not isinstance(points, list):
        return []

    normalized_points: list[dict[str, str]] = []
    for point in points:
        if not isinstance(point, dict):
            continue
        title = _clean_text(point.get("title"))
        if not title:
            continue
        category = _clean_text(point.get("category")).lower() or "functional"
        if category not in CATEGORY_LABELS:
            category = "functional"
        normalized_points.append(
            {
                "title": title,
                "category": category,
                "module": _clean_text(point.get("module")) or "默认模块",
                "context": _clean_text(point.get("context")) or "需求原文",
                "requirement_source": _clean_text(point.get("requirement_source")) or title,
            }
        )
    return normalized_points


def _build_analysis_sections(requirement: Requirement) -> list[dict[str, Any]]:
    payload = _analysis_payload_dict(requirement)
    return [
        {"title": "需求漏洞", "items": _normalized_string_list(payload.get("gaps"))},
        {"title": "测试标准", "items": _normalized_string_list(payload.get("test_standards"))},
    ]


def _build_summary_sections(requirement: Requirement) -> list[dict[str, Any]]:
    payload = _analysis_payload_dict(requirement)
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    return [
        {"title": "系统流程", "items": _normalized_string_list(summary.get("system_flow"))},
        {"title": "核心规则", "items": _normalized_string_list(summary.get("core_rules"))},
        {"title": "主要风险", "items": _normalized_string_list(summary.get("main_risks"))},
        {"title": "测试重点", "items": _normalized_string_list(summary.get("test_focus"))},
    ]


def _build_scenario_sections(requirement: Requirement) -> list[dict[str, Any]]:
    grouped_items: dict[str, list[dict[str, str]]] = {
        "functional": [],
        "boundary": [],
        "exception": [],
    }
    for point in _normalized_selected_points(_analysis_payload_dict(requirement)):
        grouped_items[point["category"]].append(point)

    return [
        {"title": "功能点", "items": grouped_items["functional"]},
        {"title": "边界点", "items": grouped_items["boundary"]},
        {"title": "异常点", "items": grouped_items["exception"]},
    ]


def _build_review_point_rows(requirement: Requirement) -> list[dict[str, Any]]:
    if requirement.review_points:
        return [
            {
                "id": point.id,
                "selected": point.is_selected,
                "is_core": point.is_core,
                "category": point.category or "functional",
                "module": point.module or "",
                "title": point.title,
                "context": point.context or "需求原文",
                "requirement_source": point.requirement_source or point.title,
                "source": point.source or "ai",
            }
            for point in requirement.review_points
        ]

    return [
        {
            "id": "",
            "selected": True,
            "is_core": False,
            "category": point["category"],
            "module": point["module"],
            "title": point["title"],
            "context": point["context"],
            "requirement_source": point["requirement_source"],
            "source": "ai",
        }
        for point in _normalized_selected_points(_analysis_payload_dict(requirement))
    ]


def _normalized_custom_points(requirement: Requirement) -> list[str]:
    payload = _analysis_payload_dict(requirement)
    review = payload.get("review") if isinstance(payload.get("review"), dict) else {}
    return _normalized_string_list(review.get("custom_points"))


def _normalized_core_regression_points(requirement: Requirement) -> list[str]:
    stored = _normalized_string_list(requirement.core_regression_points)
    if stored:
        return stored
    payload = _analysis_payload_dict(requirement)
    review = payload.get("review") if isinstance(payload.get("review"), dict) else {}
    return _normalized_string_list(review.get("core_regression_points"))


def _append_tool_result(requirement: Requirement, tool_name: str, summary: str) -> None:
    history = list(requirement.tool_result or [])
    history.append(
        {
            "tool": tool_name,
            "summary": summary,
            "status": "completed",
            "created_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        }
    )
    requirement.tool_result = history[-8:]


def _parse_review_points_payload(raw_payload: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(raw_payload or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _parse_deleted_ids(raw_deleted_ids: str) -> set[int]:
    deleted_ids: set[int] = set()
    for raw_id in (raw_deleted_ids or "").split(","):
        candidate = raw_id.strip()
        if candidate.isdigit():
            deleted_ids.add(int(candidate))
    return deleted_ids


def _build_tool_plan(requirement: Requirement) -> list[dict[str, str]]:
    payload = _analysis_payload_dict(requirement)
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    risks = _normalized_string_list(summary.get("main_risks"))
    core_points = _normalized_core_regression_points(requirement)
    selected_points = _normalized_selected_points(payload)

    plan: list[dict[str, str]] = []
    if core_points:
        plan.append(
            {
                "tool": "UI 自动化",
                "scope": "核心回归链路",
                "target": "覆盖已选核心回归点",
                "reason": f"优先沉淀 {min(len(core_points), 5)} 条高价值回归点，降低重复回归成本。",
            }
        )

    if any(point["category"] == "functional" for point in selected_points):
        plan.append(
            {
                "tool": "接口测试",
                "scope": "主流程与关键数据校验",
                "target": "验证主流程状态流转和结果数据",
                "reason": "功能点覆盖较多，接口层更适合快速校验结果一致性和批量回归。",
            }
        )

    if any(point["category"] == "boundary" for point in selected_points):
        plan.append(
            {
                "tool": "参数化边界测试",
                "scope": "阈值、空值和上下限场景",
                "target": "覆盖边界条件前、中、后样本",
                "reason": "当前需求含边界点，建议通过参数化样本提高边界验证完整度。",
            }
        )

    if any(point["category"] == "exception" for point in selected_points) or risks:
        plan.append(
            {
                "tool": "异常注入与日志核对",
                "scope": "失败、超时、拦截和兜底场景",
                "target": "验证异常反馈、日志留痕和兜底逻辑",
                "reason": risks[0] if risks else "当前需求存在异常处理场景，需要单独验证失败链路是否闭环。",
            }
        )

    if not plan:
        plan.append(
            {
                "tool": "手工探索测试",
                "scope": "需求主流程",
                "target": "快速确认页面流程和结果反馈",
                "reason": "当前结构化测试点较少，先用手工探索补足业务理解。",
            }
        )

    return plan[:4]


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

    llm_unavailable = use_llm and not can_use_llm()
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
    requirement.analysis_status = "draft"
    requirement.reviewed_at = None
    requirement.core_regression_points = []
    requirement.tool_plan = []
    for review_point in list(requirement.review_points):
        db.delete(review_point)
    requirement.last_analyzed_at = datetime.utcnow()
    db.commit()

    redirect_url = f"/requirements/{requirement_id}?reanalyzed=1"
    if llm_unavailable:
        redirect_url += "&llm_unavailable=1"
    return RedirectResponse(url=redirect_url, status_code=303)


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
    reviewed: int | None = Query(default=None),
    tool_planned: int | None = Query(default=None),
    review_required: int | None = Query(default=None),
    edited: int | None = Query(default=None),
    llm_unavailable: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    requirement = (
        db.query(Requirement)
        .options(
            joinedload(Requirement.project),
            joinedload(Requirement.test_cases),
            joinedload(Requirement.review_points),
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
            "reviewed": reviewed,
            "tool_planned": tool_planned,
            "review_required": review_required,
            "edited": edited,
            "llm_unavailable": llm_unavailable,
            "estimated_case_count": estimated_case_count,
            "analysis_sections": _build_analysis_sections(requirement),
            "summary_sections": _build_summary_sections(requirement),
            "scenario_sections": _build_scenario_sections(requirement),
            "review_point_rows": _build_review_point_rows(requirement),
            "custom_points": _normalized_custom_points(requirement),
            "core_regression_points": _normalized_core_regression_points(requirement),
            "tool_plan": list(requirement.tool_plan or []),
            "tool_result": list(requirement.tool_result or []),
        },
    )


@router.post("/requirements/{requirement_id}/review", name="requirement_review")
def review_requirement(
    requirement_id: int,
    review_points_payload: str = Form(default="[]"),
    deleted_point_ids: str = Form(default=""),
    custom_points: str = Form(default=""),
    review_notes: str = Form(default=""),
    db: Session = Depends(get_db),
):
    requirement = (
        db.query(Requirement)
        .options(joinedload(Requirement.review_points))
        .filter(Requirement.id == requirement_id)
        .first()
    )
    if requirement is None:
        raise HTTPException(status_code=404, detail="Requirement not found.")

    payload_rows = _parse_review_points_payload(review_points_payload)
    deleted_ids = _parse_deleted_ids(deleted_point_ids)
    existing_points = {point.id: point for point in requirement.review_points if point.id is not None}
    kept_ids: set[int] = set()
    core_regression_points: list[str] = []
    selected_points: list[dict[str, str]] = []

    for index, row in enumerate(payload_rows):
        title = _clean_text(row.get("title"))
        if not title:
            continue

        point_id_raw = _clean_text(row.get("id"))
        point_id = int(point_id_raw) if point_id_raw.isdigit() else None
        point = existing_points.get(point_id) if point_id is not None else None
        if point is None:
            point = RequirementReviewPoint(requirement_id=requirement.id)
            db.add(point)
        else:
            kept_ids.add(point.id)

        category = _clean_text(row.get("category")).lower() or "functional"
        if category not in CATEGORY_LABELS:
            category = "functional"

        point.title = title
        point.category = category
        point.module = _clean_text(row.get("module")) or None
        point.context = _clean_text(row.get("context")) or "需求原文"
        point.requirement_source = _clean_text(row.get("requirement_source")) or title
        point.preconditions = _clean_text(row.get("preconditions")) or None
        point.steps = _clean_text(row.get("steps")) or None
        point.expected = _clean_text(row.get("expected")) or None
        point.priority = _clean_text(row.get("priority")) or "P2"
        point.is_selected = bool(row.get("selected"))
        point.is_core = bool(row.get("is_core"))
        point.source = _clean_text(row.get("source")) or point.source or "manual"
        point.sort_order = index
        point.updated_at = datetime.utcnow()

        if point.is_selected:
            selected_points.append(
                {
                    "title": point.title,
                    "category": point.category,
                    "module": point.module or requirement.title,
                    "context": point.context or "需求原文",
                    "requirement_source": point.requirement_source or point.title,
                }
            )
        if point.is_selected and point.is_core and point.title not in core_regression_points:
            core_regression_points.append(point.title)

    for point_id, point in existing_points.items():
        if point_id in deleted_ids or point_id not in kept_ids:
            db.delete(point)

    custom_point_lines = _normalized_string_list(custom_points.splitlines())
    analysis_payload = dict(_analysis_payload_dict(requirement))
    review = analysis_payload.get("review") if isinstance(analysis_payload.get("review"), dict) else {}
    review["custom_points"] = custom_point_lines
    review["core_regression_points"] = core_regression_points
    analysis_payload["review"] = review
    analysis_payload["selected_points"] = selected_points

    requirement.analysis_payload = analysis_payload
    requirement.parsed_points = [point["title"] for point in selected_points]
    requirement.review_notes = review_notes.strip() or None
    requirement.core_regression_points = core_regression_points
    requirement.analysis_status = "reviewed"
    requirement.reviewed_at = datetime.utcnow()
    _append_tool_result(
        requirement,
        "人工确认",
        f"已确认 {len(selected_points)} 条测试点，选出 {len(core_regression_points)} 条核心回归点。",
    )
    db.commit()

    return RedirectResponse(url=f"/requirements/{requirement_id}?reviewed=1", status_code=303)


@router.post("/requirements/{requirement_id}/tool-plan", name="requirement_tool_plan")
def create_requirement_tool_plan(requirement_id: int, db: Session = Depends(get_db)):
    requirement = db.query(Requirement).filter(Requirement.id == requirement_id).first()
    if requirement is None:
        raise HTTPException(status_code=404, detail="Requirement not found.")

    requirement.tool_plan = _build_tool_plan(requirement)
    _append_tool_result(
        requirement,
        "工具规划",
        f"已生成 {len(requirement.tool_plan or [])} 条测试工具与执行策略建议。",
    )
    db.commit()

    return RedirectResponse(url=f"/requirements/{requirement_id}?tool_planned=1", status_code=303)