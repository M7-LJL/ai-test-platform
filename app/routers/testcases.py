from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import Project, Requirement, TestCase, TestSuite
from app.services.xmind_markdown_service import (
    CASE_TYPE_PRIORITY,
    parse_xmind_markdown,
    render_case_from_locked_data,
)

router = APIRouter(tags=["testcases-html"])
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _utcnow() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _append_requirement_tool_result(
    requirement: Requirement,
    tool_name: str,
    summary: str,
    status: str = "completed",
) -> None:
    history: list[dict[str, Any]] = list(requirement.tool_result or [])
    history.append(
        {
            "tool": tool_name,
            "summary": summary,
            "status": status,
            "created_at": _utcnow(),
        }
    )
    requirement.tool_result = history[-8:]


def _ensure_unique_case_id(db: Session, desired_case_id: str) -> str:
    candidate = desired_case_id.strip() if desired_case_id else ""
    if not candidate:
        candidate = f"TC-{uuid4().hex[:8].upper()}"

    exists = db.query(TestCase).filter(TestCase.case_id == candidate).first()
    if exists is None:
        return candidate
    return f"TC-{uuid4().hex[:8].upper()}"


def _source_version(requirement: Requirement) -> str:
    if requirement.reviewed_at is not None:
        return f"reviewed-{requirement.reviewed_at.strftime('%Y%m%d%H%M%S')}"
    if requirement.last_analyzed_at is not None:
        return f"analyzed-{requirement.last_analyzed_at.strftime('%Y%m%d%H%M%S')}"
    return f"generated-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"


def _normalized_title(value: str) -> str:
    return " ".join((value or "").split()).strip().lower()


def _clean_text(value: str) -> str:
    return " ".join((value or "").replace("\u3000", " ").split()).strip()


def _safe_redirect_target(target: str, fallback: str = "/testcases") -> str:
    candidate = (target or "").strip()
    if candidate.startswith("/") and not candidate.startswith("//") and "://" not in candidate:
        return candidate
    return fallback


def _parse_int_list(raw_values: str) -> list[int]:
    values: list[int] = []
    for raw in (raw_values or "").split(","):
        candidate = raw.strip()
        if candidate.isdigit():
            values.append(int(candidate))
    return values


def _split_multiline_lines(value: str) -> list[str]:
    lines: list[str] = []
    for raw in (value or "").splitlines():
        cleaned = raw.strip().lstrip("-").lstrip("•").strip()
        if cleaned:
            lines.append(cleaned)
    return lines


def _storage_case_type_to_render_case_type(case_type: str) -> str:
    normalized = _clean_text(case_type)
    if normalized in {"正向", "正常", "正常流程"}:
        return "正常流程"
    if normalized in {"边界", "边界条件"}:
        return "边界条件"
    if normalized in {"异常", "异常场景"}:
        return "异常场景"
    return "正常流程"


def _normalize_locked_case_data(data: dict[str, Any] | None) -> dict[str, Any]:
    raw = dict(data or {})
    return {
        "scene_name": _clean_text(str(raw.get("scene_name", ""))),
        "user_type": _clean_text(str(raw.get("user_type", ""))),
        "entry": _clean_text(str(raw.get("entry", ""))),
        "business_line": _clean_text(str(raw.get("business_line", ""))),
        "scenario_type": _clean_text(str(raw.get("scenario_type", ""))),
        "channel": _clean_text(str(raw.get("channel", ""))),
        "device_type": _clean_text(str(raw.get("device_type", ""))),
        "payment_method": _clean_text(str(raw.get("payment_method", ""))),
        "business_object": _clean_text(str(raw.get("business_object", ""))),
        "preconditions": [item for item in raw.get("preconditions", []) if _clean_text(str(item))],
        "config_conditions": [item for item in raw.get("config_conditions", []) if _clean_text(str(item))],
        "action": _clean_text(str(raw.get("action", ""))),
        "expected_results": [item for item in raw.get("expected_results", []) if _clean_text(str(item))],
        "assertions": [item for item in raw.get("assertions", []) if _clean_text(str(item))],
        "exception_handling": [item for item in raw.get("exception_handling", []) if _clean_text(str(item))],
        "boundary_conditions": [item for item in raw.get("boundary_conditions", []) if _clean_text(str(item))],
    }


def _fallback_locked_case_data(case: dict[str, Any]) -> dict[str, Any]:
    return _normalize_locked_case_data(
        {
            "scene_name": _clean_text(str(case.get("title", ""))),
            "user_type": "",
            "entry": "",
            "business_line": "",
            "scenario_type": "",
            "channel": "",
            "device_type": "",
            "payment_method": "",
            "business_object": "",
            "preconditions": _split_multiline_lines(str(case.get("preconditions", ""))),
            "config_conditions": [],
            "action": _clean_text(str(case.get("title", ""))),
            "expected_results": _split_multiline_lines(str(case.get("expected", ""))),
            "assertions": [],
            "exception_handling": [],
            "boundary_conditions": [],
        }
    )


def _extract_locked_case_form_payload(
    *,
    scene_name: str,
    user_type: str,
    entry: str,
    business_line: str,
    scenario_type: str,
    channel: str,
    device_type: str,
    payment_method: str,
    business_object: str,
    locked_preconditions: str,
    config_conditions: str,
    action: str,
    expected_results: str,
    assertions: str,
    exception_handling: str,
    boundary_conditions: str,
) -> dict[str, Any]:
    return _normalize_locked_case_data(
        {
            "scene_name": scene_name,
            "user_type": user_type,
            "entry": entry,
            "business_line": business_line,
            "scenario_type": scenario_type,
            "channel": channel,
            "device_type": device_type,
            "payment_method": payment_method,
            "business_object": business_object,
            "preconditions": _split_multiline_lines(locked_preconditions),
            "config_conditions": _split_multiline_lines(config_conditions),
            "action": action,
            "expected_results": _split_multiline_lines(expected_results),
            "assertions": _split_multiline_lines(assertions),
            "exception_handling": _split_multiline_lines(exception_handling),
            "boundary_conditions": _split_multiline_lines(boundary_conditions),
        }
    )


def _has_structured_form_input(payload: dict[str, Any]) -> bool:
    scalar_fields = (
        "scene_name",
        "user_type",
        "entry",
        "business_line",
        "scenario_type",
        "channel",
        "device_type",
        "payment_method",
        "business_object",
        "action",
    )
    list_fields = (
        "preconditions",
        "config_conditions",
        "expected_results",
        "assertions",
        "exception_handling",
        "boundary_conditions",
    )

    if any(_clean_text(str(payload.get(field, ""))) for field in scalar_fields):
        return True
    if any(payload.get(field) for field in list_fields):
        return True
    return False


def _build_testcase_model(
    db: Session,
    requirement: Requirement,
    case: dict[str, Any],
    *,
    source: str,
    source_version: str,
) -> TestCase:
    locked_case_data = _normalize_locked_case_data(case.get("locked_case_data") or _fallback_locked_case_data(case))
    return TestCase(
        project_id=requirement.project_id,
        requirement_id=requirement.id,
        case_id=_ensure_unique_case_id(db, case.get("case_id", "")),
        title=case["title"],
        module=case.get("module") or requirement.title,
        priority=case.get("priority") or CASE_TYPE_PRIORITY.get(case.get("case_type", ""), "P2"),
        case_type=case.get("test_kind") or case.get("case_type") or "正向",
        test_data=case.get("test_data") or "",
        requirement_source=case.get("requirement_source") or "需求原文",
        preconditions=case.get("preconditions") or "",
        steps=case.get("steps") or "",
        expected=case.get("expected") or "",
        status=case.get("status") or "draft",
        source=source,
        review_status="pending_review",
        manually_edited=False,
        locked=False,
        source_version=source_version,
        updated_at=datetime.utcnow(),
        locked_case_data=locked_case_data,
    )


def _generation_impact(existing_cases: list[TestCase]) -> dict[str, int]:
    locked_count = sum(1 for case in existing_cases if case.locked)
    edited_count = sum(1 for case in existing_cases if case.manually_edited)
    protected_count = sum(1 for case in existing_cases if case.locked or case.manually_edited)
    return {
        "total": len(existing_cases),
        "locked": locked_count,
        "edited": edited_count,
        "replaceable": len(existing_cases) - protected_count,
        "protected": protected_count,
    }


def _sync_requirement_cases(
    db: Session,
    requirement: Requirement,
    structured_cases: list[dict[str, Any]],
    *,
    source: str,
    mode: str,
    replaceable_sources: set[str] | None = None,
) -> dict[str, int]:
    existing_cases = (
        db.query(TestCase)
        .filter(TestCase.requirement_id == requirement.id)
        .order_by(TestCase.created_at.asc())
        .all()
    )
    source_version = _source_version(requirement)
    protected_titles = {
        _normalized_title(case.title)
        for case in existing_cases
        if case.locked or case.manually_edited
    }
    all_existing_titles = {_normalized_title(case.title) for case in existing_cases}
    deleted_count = 0

    if mode == "overwrite":
        for testcase in existing_cases:
            if testcase.locked or testcase.manually_edited:
                continue
            if replaceable_sources is not None and testcase.source not in replaceable_sources:
                continue
            db.delete(testcase)
            deleted_count += 1
        blocked_titles = set(protected_titles)
    else:
        blocked_titles = set(all_existing_titles)

    created_count = 0
    skipped_count = 0
    staged_titles = set(blocked_titles)
    for case in structured_cases:
        normalized_title = _normalized_title(case.get("title", ""))
        if not normalized_title or normalized_title in staged_titles:
            skipped_count += 1
            continue
        staged_titles.add(normalized_title)
        testcase = _build_testcase_model(
            db,
            requirement,
            case,
            source=source,
            source_version=source_version,
        )
        db.add(testcase)
        created_count += 1

    impact = _generation_impact(existing_cases)
    impact.update(
        {
            "created": created_count,
            "deleted": deleted_count,
            "skipped": skipped_count,
        }
    )
    return impact


@router.get("/testcases", name="testcase_list")
def list_testcases_page(
    request: Request,
    project_id: str = Query(default=""),
    requirement_id: str = Query(default=""),
    status: str = Query(default=""),
    review_status: str = Query(default=""),
    keyword: str = Query(default=""),
    db: Session = Depends(get_db),
):
    selected_project_id = int(project_id) if project_id.strip().isdigit() else None
    selected_requirement_id = int(requirement_id) if requirement_id.strip().isdigit() else None

    query = (
        db.query(TestCase)
        .options(
            joinedload(TestCase.project),
            joinedload(TestCase.requirement),
            joinedload(TestCase.suite),
        )
        .filter(TestCase.is_archived.is_(False))
        .order_by(TestCase.updated_at.desc(), TestCase.created_at.desc())
    )

    if selected_project_id is not None:
        query = query.filter(TestCase.project_id == selected_project_id)
    if selected_requirement_id is not None:
        query = query.filter(TestCase.requirement_id == selected_requirement_id)
    if status.strip():
        query = query.filter(TestCase.status == status.strip())
    if review_status.strip():
        query = query.filter(TestCase.review_status == review_status.strip())
    if keyword.strip():
        like_pattern = f"%{keyword.strip()}%"
        query = query.filter(
            (TestCase.title.ilike(like_pattern))
            | (TestCase.case_id.ilike(like_pattern))
            | (TestCase.module.ilike(like_pattern))
        )

    projects = db.query(Project).order_by(Project.created_at.desc()).all()
    requirements_query = db.query(Requirement).options(joinedload(Requirement.project))
    if selected_project_id is not None:
        requirements_query = requirements_query.filter(Requirement.project_id == selected_project_id)
    requirements = requirements_query.order_by(Requirement.created_at.desc()).all()

    return templates.TemplateResponse(
        request,
        "testcases/list.html",
        {
            "request": request,
            "testcases": query.all(),
            "projects": projects,
            "requirements": requirements,
            "selected_project_id": selected_project_id,
            "selected_requirement_id": selected_requirement_id,
            "selected_status": status.strip(),
            "selected_review_status": review_status.strip(),
            "keyword": keyword.strip(),
        },
    )


@router.post("/test-suites/create", name="create_test_suite")
def create_test_suite(
    project_id: int = Form(...),
    name: str = Form(...),
    description: str = Form(default=""),
    redirect_to: str = Form(default="/testcases"),
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")

    suite_name = _clean_text(name)
    if not suite_name:
        raise HTTPException(status_code=400, detail="Suite name is required.")

    duplicated_suite = (
        db.query(TestSuite)
        .filter(TestSuite.project_id == project_id, TestSuite.name == suite_name)
        .first()
    )
    if duplicated_suite is not None:
        if duplicated_suite.is_archived:
            duplicated_suite.is_archived = False
            duplicated_suite.description = description.strip() or duplicated_suite.description
            db.commit()
            safe_redirect = redirect_to.strip() or "/testcases"
            return RedirectResponse(url=safe_redirect, status_code=303)
        raise HTTPException(status_code=400, detail="Suite name already exists in current project.")

    suite = TestSuite(
        project_id=project_id,
        name=suite_name,
        description=description.strip() or None,
        is_archived=False,
    )
    db.add(suite)
    db.commit()

    safe_redirect = redirect_to.strip() or "/testcases"
    return RedirectResponse(url=safe_redirect, status_code=303)


@router.get("/testcases/import-markdown", name="import_testcases_markdown")
def import_testcases_markdown_page(
    request: Request,
    requirement_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    requirements = (
        db.query(Requirement)
        .options(joinedload(Requirement.project))
        .order_by(Requirement.created_at.desc())
        .all()
    )
    return templates.TemplateResponse(
        request,
        "testcases/import_markdown.html",
        {
            "request": request,
            "requirements": requirements,
            "selected_requirement_id": requirement_id,
        },
    )


@router.post("/testcases/import-markdown", name="submit_import_testcases_markdown")
async def import_testcases_markdown_submit(
    requirement_id: int = Form(...),
    markdown_file: UploadFile = File(...),
    replace_existing: str | None = Form(default=None),
    db: Session = Depends(get_db),
):
    requirement = db.query(Requirement).filter(Requirement.id == requirement_id).first()
    if requirement is None:
        raise HTTPException(status_code=404, detail="Requirement not found.")

    raw_bytes = await markdown_file.read()
    markdown_content = raw_bytes.decode("utf-8", errors="ignore")
    parsed_cases = parse_xmind_markdown(markdown_content)
    if not parsed_cases:
        raise HTTPException(status_code=400, detail="No test cases could be parsed from markdown.")

    normalized_cases: list[dict[str, Any]] = []
    for case in parsed_cases:
        payload = dict(case)
        payload["locked_case_data"] = _normalize_locked_case_data(
            payload.get("locked_case_data") or _fallback_locked_case_data(payload)
        )
        normalized_cases.append(payload)

    impact = _sync_requirement_cases(
        db,
        requirement,
        normalized_cases,
        source="markdown_imported",
        mode="overwrite" if replace_existing else "append",
    )

    requirement.analysis_status = "ready_for_execution"
    _append_requirement_tool_result(
        requirement,
        "Markdown 导入",
        f"已导入 {impact['created']} 条 Markdown 用例，跳过 {impact['skipped']} 条重复/受保护用例。",
    )
    db.commit()
    return RedirectResponse(
        url=f"/requirements/{requirement.id}?imported={impact['created']}",
        status_code=303,
    )


@router.get("/testcases/{testcase_id}/edit", name="edit_testcase")
def edit_testcase_page(
    testcase_id: int,
    request: Request,
    redirect_to: str = Query(default=""),
    db: Session = Depends(get_db),
):
    testcase = (
        db.query(TestCase)
        .options(joinedload(TestCase.requirement), joinedload(TestCase.project))
        .filter(TestCase.id == testcase_id)
        .first()
    )
    if testcase is None:
        raise HTTPException(status_code=404, detail="Test case not found.")

    testcase.locked_case_data = _normalize_locked_case_data(
        testcase.locked_case_data
        or _fallback_locked_case_data(
            {
                "title": testcase.title,
                "preconditions": testcase.preconditions,
                "expected": testcase.expected,
            }
        )
    )
    suites = (
        db.query(TestSuite)
        .filter(
            TestSuite.project_id == testcase.project_id,
            TestSuite.is_archived.is_(False),
        )
        .order_by(TestSuite.created_at.desc())
        .all()
    )

    return templates.TemplateResponse(
        request,
        "testcases/edit.html",
        {
            "request": request,
            "testcase": testcase,
            "suites": suites,
            "redirect_to": _safe_redirect_target(
                redirect_to,
                f"/requirements/{testcase.requirement_id}" if testcase.requirement_id else "/testcases",
            ),
        },
    )


@router.post("/testcases/{testcase_id}/edit", name="submit_edit_testcase")
def submit_edit_testcase(
    testcase_id: int,
    redirect_to: str = Form(default=""),
    title: str = Form(default=""),
    suite_id: str = Form(default=""),
    module: str = Form(default=""),
    priority: str = Form(default="P2"),
    case_type: str = Form(default="正向"),
    preconditions: str = Form(default=""),
    steps: str = Form(default=""),
    expected: str = Form(default=""),
    test_data: str = Form(default=""),
    requirement_source: str = Form(default=""),
    status: str = Form(default="draft"),
    locked: str | None = Form(default=None),
    scene_name: str = Form(default=""),
    user_type: str = Form(default=""),
    entry: str = Form(default=""),
    business_line: str = Form(default=""),
    scenario_type: str = Form(default=""),
    channel: str = Form(default=""),
    device_type: str = Form(default=""),
    payment_method: str = Form(default=""),
    business_object: str = Form(default=""),
    locked_preconditions: str = Form(default=""),
    config_conditions: str = Form(default=""),
    action: str = Form(default=""),
    expected_results: str = Form(default=""),
    assertions: str = Form(default=""),
    exception_handling: str = Form(default=""),
    boundary_conditions: str = Form(default=""),
    db: Session = Depends(get_db),
):
    testcase = db.query(TestCase).filter(TestCase.id == testcase_id).first()
    if testcase is None:
        raise HTTPException(status_code=404, detail="Test case not found.")

    requirement = None
    if testcase.requirement_id is not None:
        requirement = db.query(Requirement).filter(Requirement.id == testcase.requirement_id).first()

    normalized_suite_id = int(suite_id) if suite_id.strip().isdigit() else None
    if normalized_suite_id is not None:
        suite = (
            db.query(TestSuite)
            .filter(
                TestSuite.id == normalized_suite_id,
                TestSuite.project_id == testcase.project_id,
                TestSuite.is_archived.is_(False),
            )
            .first()
        )
        if suite is None:
            raise HTTPException(status_code=400, detail="Invalid suite for current project.")
        testcase.suite_id = suite.id
    else:
        testcase.suite_id = None

    structured_payload = _extract_locked_case_form_payload(
        scene_name=scene_name or title,
        user_type=user_type,
        entry=entry,
        business_line=business_line,
        scenario_type=scenario_type,
        channel=channel,
        device_type=device_type,
        payment_method=payment_method,
        business_object=business_object,
        locked_preconditions=locked_preconditions,
        config_conditions=config_conditions,
        action=action or title,
        expected_results=expected_results,
        assertions=assertions,
        exception_handling=exception_handling,
        boundary_conditions=boundary_conditions,
    )

    if _has_structured_form_input(structured_payload):
        rendered = render_case_from_locked_data(
            structured_payload,
            module=_clean_text(module) or _clean_text(testcase.module or "") or _clean_text(requirement.title if requirement else ""),
            section="",
            case_type=_storage_case_type_to_render_case_type(case_type),
            priority=_clean_text(priority) or "P2",
            requirement_source=_clean_text(requirement_source) or "人工编辑",
        )
        testcase.title = rendered["title"]
        testcase.module = rendered["module"]
        testcase.priority = rendered["priority"]
        testcase.case_type = rendered.get("test_kind") or case_type.strip() or "正向"
        testcase.preconditions = rendered["preconditions"]
        testcase.steps = rendered["steps"]
        testcase.expected = rendered["expected"]
        testcase.test_data = rendered.get("test_data") or test_data.strip()
        testcase.requirement_source = rendered.get("requirement_source") or "人工编辑"
        testcase.locked_case_data = _normalize_locked_case_data(rendered.get("locked_case_data"))
    else:
        testcase.title = title.strip() or testcase.title
        testcase.module = module.strip() or testcase.module
        testcase.priority = priority.strip() or "P2"
        testcase.case_type = case_type.strip() or "正向"
        testcase.preconditions = preconditions.strip()
        testcase.steps = steps.strip()
        testcase.expected = expected.strip()
        testcase.test_data = test_data.strip()
        testcase.requirement_source = requirement_source.strip() or "人工编辑"
        testcase.locked_case_data = _normalize_locked_case_data(
            testcase.locked_case_data
            or _fallback_locked_case_data(
                {
                    "title": testcase.title,
                    "preconditions": testcase.preconditions,
                    "expected": testcase.expected,
                }
            )
        )

    testcase.status = status.strip() or "draft"
    testcase.locked = locked is not None
    testcase.manually_edited = True
    testcase.source = "manual_edit"
    testcase.review_status = "pending_review"
    testcase.last_editor = "手工编辑"
    testcase.updated_at = datetime.utcnow()
    db.commit()

    safe_redirect = _safe_redirect_target(
        redirect_to,
        f"/requirements/{testcase.requirement_id}" if testcase.requirement_id is not None else "/testcases",
    )
    separator = "&" if "?" in safe_redirect else "?"
    if "edited=" not in safe_redirect:
        safe_redirect = f"{safe_redirect}{separator}edited=1"
    return RedirectResponse(url=safe_redirect, status_code=303)
