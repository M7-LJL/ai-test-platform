from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import Project, Requirement, TestCase, TestPlan, TestPlanCase

router = APIRouter(prefix="/plans", tags=["plans-html"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _parse_int_list(raw_values: str) -> list[int]:
    values: list[int] = []
    for raw in (raw_values or "").split(","):
        candidate = raw.strip()
        if candidate.isdigit():
            values.append(int(candidate))
    return values


def _parse_optional_int(raw_value: str) -> int | None:
    candidate = (raw_value or "").strip()
    return int(candidate) if candidate.isdigit() else None


def _parse_attachments(raw_value: str) -> list[str]:
    return [item.strip() for item in (raw_value or "").splitlines() if item.strip()]


def _build_plan_stats(plan_cases: list[TestPlanCase]) -> dict[str, object]:
    stats = {
        "total": len(plan_cases),
        "untested": sum(1 for item in plan_cases if item.run_status == "untested"),
        "passed": sum(1 for item in plan_cases if item.run_status == "passed"),
        "failed": sum(1 for item in plan_cases if item.run_status == "failed"),
        "blocked": sum(1 for item in plan_cases if item.run_status == "blocked"),
    }
    executed = stats["passed"] + stats["failed"] + stats["blocked"]
    defect_count = sum(len(item.defects) for item in plan_cases)
    latest_executed_at = max((item.executed_at for item in plan_cases if item.executed_at is not None), default=None)
    completion_rate = round((executed / stats["total"]) * 100) if stats["total"] else 0
    pass_rate = round((stats["passed"] / executed) * 100) if executed else 0
    stats.update(
        {
            "executed": executed,
            "defect_count": defect_count,
            "latest_executed_at": latest_executed_at,
            "completion_rate": completion_rate,
            "pass_rate": pass_rate,
        }
    )
    return stats


@router.get("", name="plan_list")
def list_plans_page(
    request: Request,
    project_id: str = Query(default=""),
    requirement_id: str = Query(default=""),
    status: str = Query(default=""),
    db: Session = Depends(get_db),
):
    selected_project_id = _parse_optional_int(project_id)
    selected_requirement_id = _parse_optional_int(requirement_id)

    query = (
        db.query(TestPlan)
        .options(
            joinedload(TestPlan.project),
            joinedload(TestPlan.requirement),
            joinedload(TestPlan.plan_cases),
        )
        .order_by(TestPlan.created_at.desc())
    )

    if selected_project_id is not None:
        query = query.filter(TestPlan.project_id == selected_project_id)
    if selected_requirement_id is not None:
        query = query.filter(TestPlan.requirement_id == selected_requirement_id)
    if status.strip():
        query = query.filter(TestPlan.status == status.strip())

    projects = db.query(Project).order_by(Project.created_at.desc()).all()
    requirements_query = db.query(Requirement).options(joinedload(Requirement.project))
    if selected_project_id is not None:
        requirements_query = requirements_query.filter(Requirement.project_id == selected_project_id)
    requirements = requirements_query.order_by(Requirement.created_at.desc()).all()

    return templates.TemplateResponse(
        request,
        "plans/list.html",
        {
            "request": request,
            "plans": query.all(),
            "projects": projects,
            "requirements": requirements,
            "selected_project_id": selected_project_id,
            "selected_status": status.strip(),
            "selected_requirement_id": selected_requirement_id,
        },
    )


@router.post("/create", name="plan_create")
def create_plan(
    project_id: int = Form(...),
    requirement_id: str = Form(default=""),
    name: str = Form(...),
    description: str = Form(default=""),
    owner: str = Form(default=""),
    selected_case_ids: str = Form(default=""),
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")

    normalized_name = name.strip()
    if not normalized_name:
        raise HTTPException(status_code=400, detail="Plan name is required.")

    normalized_requirement_id = int(requirement_id) if requirement_id.strip().isdigit() else None
    if normalized_requirement_id is not None:
        requirement = (
            db.query(Requirement)
            .filter(Requirement.id == normalized_requirement_id, Requirement.project_id == project_id)
            .first()
        )
        if requirement is None:
            raise HTTPException(status_code=400, detail="Requirement does not belong to the project.")

    plan = TestPlan(
        project_id=project_id,
        requirement_id=normalized_requirement_id,
        name=normalized_name,
        description=description.strip() or None,
        status="draft",
        owner=owner.strip() or None,
        planned_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(plan)
    db.flush()

    case_ids = _parse_int_list(selected_case_ids)
    if case_ids:
        cases = (
            db.query(TestCase)
            .filter(TestCase.id.in_(case_ids), TestCase.project_id == project_id)
            .order_by(TestCase.created_at.asc())
            .all()
        )
        for index, case in enumerate(cases):
            db.add(
                TestPlanCase(
                    plan_id=plan.id,
                    test_case_id=case.id,
                    sort_order=index,
                    run_status="untested",
                )
            )

    db.commit()
    return RedirectResponse(url=f"/plans/{plan.id}", status_code=303)


@router.get("/{plan_id}", name="plan_detail")
def plan_detail_page(plan_id: int, request: Request, db: Session = Depends(get_db)):
    plan = (
        db.query(TestPlan)
        .options(
            joinedload(TestPlan.project),
            joinedload(TestPlan.requirement),
            joinedload(TestPlan.plan_cases).joinedload(TestPlanCase.test_case),
            joinedload(TestPlan.plan_cases).joinedload(TestPlanCase.defects),
        )
        .filter(TestPlan.id == plan_id)
        .first()
    )
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found.")

    plan_cases = sorted(plan.plan_cases, key=lambda item: item.sort_order)
    stats = _build_plan_stats(plan_cases)

    return templates.TemplateResponse(
        request,
        "plans/detail.html",
        {
            "request": request,
            "plan": plan,
            "plan_cases": plan_cases,
            "stats": stats,
        },
    )


@router.post("/{plan_id}/cases/{plan_case_id}/result", name="plan_case_result")
def update_plan_case_result(
    plan_id: int,
    plan_case_id: int,
    run_status: str = Form(...),
    executed_by: str = Form(default=""),
    actual_result: str = Form(default=""),
    environment_info: str = Form(default=""),
    result_comment: str = Form(default=""),
    attachments_text: str = Form(default=""),
    db: Session = Depends(get_db),
):
    plan_case = (
        db.query(TestPlanCase)
        .options(joinedload(TestPlanCase.plan), joinedload(TestPlanCase.test_case))
        .filter(TestPlanCase.id == plan_case_id, TestPlanCase.plan_id == plan_id)
        .first()
    )
    if plan_case is None:
        raise HTTPException(status_code=404, detail="Plan case not found.")

    normalized_status = run_status.strip()
    if normalized_status not in {"untested", "passed", "failed", "blocked"}:
        raise HTTPException(status_code=400, detail="Invalid run status.")

    normalized_executed_by = executed_by.strip() or None
    normalized_actual_result = actual_result.strip() or None
    normalized_environment_info = environment_info.strip() or None
    normalized_result_comment = result_comment.strip() or None
    normalized_attachments = _parse_attachments(attachments_text)

    plan_case.run_status = normalized_status
    plan_case.updated_at = datetime.utcnow()

    if normalized_status == "untested":
        plan_case.executed_by = None
        plan_case.actual_result = None
        plan_case.environment_info = None
        plan_case.result_comment = None
        plan_case.attachments = None
        plan_case.executed_at = None
    else:
        plan_case.executed_by = normalized_executed_by
        plan_case.actual_result = normalized_actual_result or normalized_result_comment
        plan_case.environment_info = normalized_environment_info
        plan_case.result_comment = normalized_result_comment
        plan_case.attachments = normalized_attachments or None
        plan_case.executed_at = datetime.utcnow()
        if plan_case.expected_result_snapshot is None and plan_case.test_case is not None:
            plan_case.expected_result_snapshot = plan_case.test_case.expected

    if plan_case.plan:
        stats = _build_plan_stats(sorted(plan_case.plan.plan_cases, key=lambda item: item.sort_order))
        if stats["executed"] == 0:
            plan_case.plan.status = "draft"
        elif stats["untested"] == 0:
            plan_case.plan.status = "completed"
        else:
            plan_case.plan.status = "in_progress"
        plan_case.plan.updated_at = datetime.utcnow()

    db.commit()
    return RedirectResponse(url=f"/plans/{plan_id}", status_code=303)