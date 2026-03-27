from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import Defect, Project, Requirement, TestCase, TestPlanCase

router = APIRouter(prefix="/defects", tags=["defects-html"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("", name="defect_list")
def list_defects_page(
    request: Request,
    project_id: str = Query(default=""),
    requirement_id: str = Query(default=""),
    severity: str = Query(default=""),
    status: str = Query(default=""),
    db: Session = Depends(get_db),
):
    selected_project_id = int(project_id) if project_id.strip().isdigit() else None
    selected_requirement_id = int(requirement_id) if requirement_id.strip().isdigit() else None

    query = (
        db.query(Defect)
        .options(
            joinedload(Defect.project),
            joinedload(Defect.requirement),
            joinedload(Defect.test_case),
            joinedload(Defect.test_plan_case),
        )
        .order_by(Defect.created_at.desc())
    )

    if selected_project_id is not None:
        query = query.filter(Defect.project_id == selected_project_id)
    if selected_requirement_id is not None:
        query = query.filter(Defect.requirement_id == selected_requirement_id)
    if severity.strip():
        query = query.filter(Defect.severity == severity.strip())
    if status.strip():
        query = query.filter(Defect.status == status.strip())

    projects = db.query(Project).order_by(Project.created_at.desc()).all()
    requirements_query = db.query(Requirement).options(joinedload(Requirement.project))
    if selected_project_id is not None:
        requirements_query = requirements_query.filter(Requirement.project_id == selected_project_id)
    requirements = requirements_query.order_by(Requirement.created_at.desc()).all() 
    return templates.TemplateResponse(
        request,
        "defects/list.html",
        {
            "request": request,
            "defects": query.all(),
            "projects": projects,
            "requirements": requirements,
            "selected_project_id": selected_project_id,
            "selected_requirement_id": selected_requirement_id,
            "selected_severity": severity.strip(),
            "selected_status": status.strip(),
        },
    )


@router.post("/create", name="defect_create")
def create_defect(
    project_id: int = Form(...),
    requirement_id: str = Form(default=""),
    test_case_id: str = Form(default=""),
    test_plan_case_id: str = Form(default=""),
    title: str = Form(default=""),
    severity: str = Form(default="major"),
    priority: str = Form(default="P2"),
    steps_to_reproduce: str = Form(default=""),
    expected_result: str = Form(default=""),
    actual_result: str = Form(default=""),
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")

    normalized_requirement_id = int(requirement_id) if requirement_id.strip().isdigit() else None
    normalized_test_case_id = int(test_case_id) if test_case_id.strip().isdigit() else None
    normalized_plan_case_id = int(test_plan_case_id) if test_plan_case_id.strip().isdigit() else None

    plan_case = None
    testcase = None
    requirement = None

    if normalized_requirement_id is not None:
        requirement = (
            db.query(Requirement)
            .filter(Requirement.id == normalized_requirement_id, Requirement.project_id == project_id)
            .first()
        )
        if requirement is None:
            raise HTTPException(status_code=400, detail="Requirement does not belong to the project.")

    if normalized_test_case_id is not None:
        testcase = (
            db.query(TestCase)
            .filter(TestCase.id == normalized_test_case_id, TestCase.project_id == project_id)
            .first()
        )
        if testcase is None:
            raise HTTPException(status_code=400, detail="Test case does not belong to the project.")

    if normalized_plan_case_id is not None:
        plan_case = (
            db.query(TestPlanCase)
            .options(joinedload(TestPlanCase.test_case), joinedload(TestPlanCase.plan))
            .filter(TestPlanCase.id == normalized_plan_case_id)
            .first()
        )
        if plan_case is None:
            raise HTTPException(status_code=400, detail="Plan case not found.")
        testcase = plan_case.test_case or testcase
        if normalized_requirement_id is None and plan_case.plan is not None:
            normalized_requirement_id = plan_case.plan.requirement_id

    normalized_title = title.strip()
    if not normalized_title:
        if testcase is not None:
            normalized_title = f"执行失败：{testcase.title}"
        else:
            normalized_title = "新建缺陷"

    normalized_steps = steps_to_reproduce.strip()
    normalized_expected = expected_result.strip()
    normalized_actual = actual_result.strip()
    if plan_case is not None:
        if not normalized_steps and testcase is not None:
            normalized_steps = testcase.steps or ""
        if not normalized_expected:
            normalized_expected = plan_case.expected_result_snapshot or (testcase.expected if testcase is not None else "") or ""
        if not normalized_actual:
            execution_context = [item for item in [plan_case.actual_result, plan_case.result_comment, plan_case.environment_info] if item]
            normalized_actual = "\n\n".join(execution_context)

    defect = Defect(
        project_id=project_id,
        requirement_id=requirement.id if requirement else normalized_requirement_id,
        test_case_id=testcase.id if testcase else normalized_test_case_id,
        test_plan_case_id=plan_case.id if plan_case else normalized_plan_case_id,
        title=normalized_title,
        severity=severity.strip() or "major",
        priority=priority.strip() or "P2",
        status="open",
        steps_to_reproduce=normalized_steps or None,
        expected_result=normalized_expected or None,
        actual_result=normalized_actual or None,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(defect)
    db.commit()
    db.refresh(defect)

    return RedirectResponse(url=f"/defects/{defect.id}", status_code=303)


@router.get("/{defect_id}", name="defect_detail")
def defect_detail_page(defect_id: int, request: Request, db: Session = Depends(get_db)):
    defect = (
    db.query(Defect)
    .options(
        joinedload(Defect.project),
        joinedload(Defect.requirement),
        joinedload(Defect.test_case),
        joinedload(Defect.test_plan_case).joinedload(TestPlanCase.test_case),
        joinedload(Defect.test_plan_case).joinedload(TestPlanCase.plan),
    )
    .filter(Defect.id == defect_id)
    .first()
)
    if defect is None:
        raise HTTPException(status_code=404, detail="Defect not found.")

    return templates.TemplateResponse(
        request,
        "defects/detail.html",
        {
            "request": request,
            "defect": defect,
        },
    )


@router.post("/{defect_id}/update", name="defect_update")
def update_defect(
    defect_id: int,
    title: str = Form(...),
    severity: str = Form(...),
    priority: str = Form(...),
    status: str = Form(...),
    steps_to_reproduce: str = Form(default=""),
    expected_result: str = Form(default=""),
    actual_result: str = Form(default=""),
    db: Session = Depends(get_db),
):
    defect = db.query(Defect).filter(Defect.id == defect_id).first()
    if defect is None:
        raise HTTPException(status_code=404, detail="Defect not found.")

    defect.title = title.strip() or defect.title
    defect.severity = severity.strip() or defect.severity
    defect.priority = priority.strip() or defect.priority
    defect.status = status.strip() or defect.status
    defect.steps_to_reproduce = steps_to_reproduce.strip() or None
    defect.expected_result = expected_result.strip() or None
    defect.actual_result = actual_result.strip() or None
    defect.updated_at = datetime.utcnow()

    db.commit()
    return RedirectResponse(url=f"/defects/{defect.id}", status_code=303)