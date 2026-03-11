from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import Requirement, TestCase
from app.services.xmind_markdown_service import CASE_TYPE_PRIORITY, generate_structured_cases, parse_xmind_markdown


router = APIRouter(tags=["testcases-html"])
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _extract_point_title(point: object) -> str:
    if isinstance(point, str):
        return point.strip()
    if isinstance(point, dict):
        for key in ("title", "name", "point", "content"):
            value = point.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return str(point).strip()


def _build_case_steps(point_title: str) -> str:
    return "\n".join(
        [
            "1. 准备测试环境并打开目标页面。",
            f"2. 执行与“{point_title}”相关的操作步骤。",
            "3. 记录系统返回结果并核对提示信息。",
        ]
    )


def _build_case_expected(point_title: str) -> str:
    return f"系统应正确满足“{point_title}”对应的业务预期，并展示正确结果。"


def _infer_priority(point_title: str) -> str:
    high_priority_keywords = ("登录", "支付", "下单", "注册", "权限", "安全")
    if any(keyword in point_title for keyword in high_priority_keywords):
        return "P1"
    return "P2"


def _ensure_unique_case_id(db: Session, desired_case_id: str) -> str:
    candidate = desired_case_id.strip() if desired_case_id else ""
    if not candidate:
        candidate = f"TC-{uuid4().hex[:8].upper()}"

    exists = db.query(TestCase).filter(TestCase.case_id == candidate).first()
    if exists is None:
        return candidate
    return f"TC-{uuid4().hex[:8].upper()}"


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

    if replace_existing:
        db.query(TestCase).filter(TestCase.requirement_id == requirement.id).delete()

    imported_count = 0
    for case in parsed_cases:
        testcase = TestCase(
            project_id=requirement.project_id,
            requirement_id=requirement.id,
            case_id=_ensure_unique_case_id(db, case.get("case_id", "")),
            title=case["title"],
            module=case.get("module") or requirement.title,
            priority=case.get("priority") or CASE_TYPE_PRIORITY.get(case.get("case_type", ""), "P2"),
            preconditions=case.get("preconditions") or "",
            steps=case.get("steps") or "",
            expected=case.get("expected") or "",
            status=case.get("status") or "draft",
        )
        db.add(testcase)
        imported_count += 1

    db.commit()
    return RedirectResponse(
        url=f"/requirements/{requirement.id}?imported={imported_count}",
        status_code=303,
    )


@router.post("/testcases/generate-from-requirement/{requirement_id}", name="generate_testcases")
def generate_testcases_from_requirement(requirement_id: int, db: Session = Depends(get_db)):
    requirement = db.query(Requirement).filter(Requirement.id == requirement_id).first()
    if requirement is None:
        raise HTTPException(status_code=404, detail="Requirement not found.")

    structured_cases = generate_structured_cases(requirement.title, requirement.content)
    db.query(TestCase).filter(TestCase.requirement_id == requirement.id).delete()
    created_testcases: list[TestCase] = []

    for case in structured_cases:
        testcase = TestCase(
            project_id=requirement.project_id,
            requirement_id=requirement.id,
            case_id=f"TC-{uuid4().hex[:8].upper()}",
            title=case["title"],
            module=case["module"],
            priority=case["priority"],
            preconditions=case["preconditions"],
            steps=case["steps"],
            expected=case["expected"],
            status=case["status"],
        )
        db.add(testcase)
        created_testcases.append(testcase)

    db.commit()

    generated_count = len(created_testcases)
    return RedirectResponse(
        url=f"/requirements/{requirement_id}?generated={generated_count}",
        status_code=303,
    )
