from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import CaseReview, CaseReviewItem, CaseReviewLog, Project, Requirement, TestCase


router = APIRouter(prefix="/case-reviews", tags=["case-reviews-html"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

APPROVED_CASE_STATUSES = {"approved", "reviewed"}
FINAL_ITEM_DECISIONS = {"approved", "needs_update", "rejected"}


def _parse_optional_int(raw_value: str) -> int | None:
    candidate = (raw_value or "").strip()
    return int(candidate) if candidate.isdigit() else None


def _parse_int_list(raw_values: str) -> list[int]:
    values: list[int] = []
    for raw in (raw_values or "").split(","):
        candidate = raw.strip()
        if candidate.isdigit():
            values.append(int(candidate))
    return values


def _parse_deadline(raw_value: str) -> datetime | None:
    value = (raw_value or "").strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid review deadline.") from exc


def _build_review_stats(items: list[CaseReviewItem]) -> dict[str, int]:
    decisions = Counter(item.decision or "pending" for item in items)
    return {
        "total": len(items),
        "pending": sum(1 for item in items if item.decision not in FINAL_ITEM_DECISIONS),
        "approved": decisions.get("approved", 0),
        "needs_update": decisions.get("needs_update", 0),
        "rejected": decisions.get("rejected", 0),
    }


def _set_case_statuses(cases: list[TestCase], status: str) -> None:
    now = datetime.utcnow()
    for case in cases:
        case.review_status = status
        case.updated_at = now


def _add_review_log(
    db: Session,
    *,
    review_id: int,
    action: str,
    operator_name: str | None,
    content: str,
    review_item_id: int | None = None,
) -> None:
    db.add(
        CaseReviewLog(
            review_id=review_id,
            review_item_id=review_item_id,
            action=action,
            operator_name=operator_name.strip() or None if operator_name else None,
            content=content.strip() or None,
        )
    )


def _wants_json_response(request: Request) -> bool:
    return "application/json" in (request.headers.get("accept") or "")


def _build_review_response_payload(review: CaseReview, *, message: str = "") -> dict[str, object]:
    stats = _build_review_stats(review.items)
    return {
        "ok": True,
        "message": message,
        "review_id": review.id,
        "review_status": review.status,
        "stats": stats,
        "review_completed": review.status == "completed",
    }


def _load_review(
    db: Session,
    review_id: int,
    *,
    include_detail_relations: bool = True,
) -> CaseReview:
    options = [joinedload(CaseReview.items).joinedload(CaseReviewItem.test_case)]
    if include_detail_relations:
        options.extend(
            [
                joinedload(CaseReview.project),
                joinedload(CaseReview.requirement),
                joinedload(CaseReview.items).joinedload(CaseReviewItem.test_case).joinedload(TestCase.requirement),
                joinedload(CaseReview.logs),
            ]
        )
    review = (
        db.query(CaseReview)
        .options(*options)
        .filter(CaseReview.id == review_id)
        .first()
    )
    if review is None:
        raise HTTPException(status_code=404, detail="Case review not found.")
    return review


@router.get("", name="case_review_list")
def list_case_reviews_page(
    request: Request,
    project_id: str = Query(default=""),
    requirement_id: str = Query(default=""),
    status: str = Query(default=""),
    auto_select_requirement_cases: str = Query(default=""),
    prefill_title: str = Query(default=""),
    prefill_summary: str = Query(default=""),
    prefill_reviewer_name: str = Query(default=""),
    prefill_initiator_name: str = Query(default=""),
    db: Session = Depends(get_db),
):
    selected_project_id = _parse_optional_int(project_id)
    selected_requirement_id = _parse_optional_int(requirement_id)

    query = (
        db.query(CaseReview)
        .options(
            joinedload(CaseReview.project),
            joinedload(CaseReview.requirement),
            joinedload(CaseReview.items),
        )
        .order_by(CaseReview.created_at.desc())
    )

    if selected_project_id is not None:
        query = query.filter(CaseReview.project_id == selected_project_id)
    if selected_requirement_id is not None:
        query = query.filter(CaseReview.requirement_id == selected_requirement_id)
    if status.strip():
        query = query.filter(CaseReview.status == status.strip())

    projects = db.query(Project).order_by(Project.created_at.desc()).all()
    requirements_query = db.query(Requirement).options(joinedload(Requirement.project))
    if selected_project_id is not None:
        requirements_query = requirements_query.filter(Requirement.project_id == selected_project_id)
    requirements = requirements_query.order_by(Requirement.created_at.desc()).all()

    testcase_query = (
        db.query(TestCase)
        .options(joinedload(TestCase.project), joinedload(TestCase.requirement), joinedload(TestCase.suite))
        .filter(TestCase.is_archived.is_(False))
        .order_by(TestCase.updated_at.desc(), TestCase.created_at.desc())
    )
    if selected_project_id is not None:
        testcase_query = testcase_query.filter(TestCase.project_id == selected_project_id)
    if selected_requirement_id is not None:
        testcase_query = testcase_query.filter(TestCase.requirement_id == selected_requirement_id)

    return templates.TemplateResponse(
        request,
        "case_reviews/list.html",
        {
            "request": request,
            "case_reviews": query.all(),
            "projects": projects,
            "requirements": requirements,
            "testcases": testcase_query.all(),
            "selected_project_id": selected_project_id,
            "selected_requirement_id": selected_requirement_id,
            "selected_status": status.strip(),
            "auto_select_requirement_cases": auto_select_requirement_cases.strip() == "true",
            "prefill_title": prefill_title.strip(),
            "prefill_summary": prefill_summary.strip(),
            "prefill_reviewer_name": prefill_reviewer_name.strip(),
            "prefill_initiator_name": prefill_initiator_name.strip(),
        },
    )


@router.post("/create", name="case_review_create")
def create_case_review(
    project_id: int = Form(...),
    requirement_id: str = Form(default=""),
    title: str = Form(...),
    initiator_name: str = Form(default=""),
    reviewer_name: str = Form(default=""),
    deadline_at: str = Form(default=""),
    summary: str = Form(default=""),
    selected_case_ids: str = Form(default=""),
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")

    normalized_title = title.strip()
    if not normalized_title:
        raise HTTPException(status_code=400, detail="Review title is required.")

    normalized_requirement_id = _parse_optional_int(requirement_id)
    if normalized_requirement_id is not None:
        requirement = (
            db.query(Requirement)
            .filter(Requirement.id == normalized_requirement_id, Requirement.project_id == project_id)
            .first()
        )
        if requirement is None:
            raise HTTPException(status_code=400, detail="Requirement does not belong to the project.")

    case_ids = _parse_int_list(selected_case_ids)
    if not case_ids:
        raise HTTPException(status_code=400, detail="Please select at least one test case.")

    cases_query = db.query(TestCase).filter(
        TestCase.id.in_(case_ids),
        TestCase.project_id == project_id,
        TestCase.is_archived.is_(False),
    )
    if normalized_requirement_id is not None:
        cases_query = cases_query.filter(TestCase.requirement_id == normalized_requirement_id)
    cases = cases_query.order_by(TestCase.created_at.asc()).all()
    if not cases:
        raise HTTPException(status_code=400, detail="No eligible test cases found for review.")

    review = CaseReview(
        project_id=project_id,
        requirement_id=normalized_requirement_id,
        title=normalized_title,
        status="draft",
        initiator_name=initiator_name.strip() or None,
        reviewer_name=reviewer_name.strip() or None,
        deadline_at=_parse_deadline(deadline_at),
        summary=summary.strip() or None,
        updated_at=datetime.utcnow(),
    )
    db.add(review)
    db.flush()

    for index, case in enumerate(cases):
        db.add(
            CaseReviewItem(
                review_id=review.id,
                test_case_id=case.id,
                sort_order=index,
                case_title_snapshot=case.title,
                priority_snapshot=case.priority,
                item_status="pending",
            )
        )
        if case.review_status in {"draft", "", None}:
            case.review_status = "pending_review"
            case.updated_at = datetime.utcnow()

    _add_review_log(
        db,
        review_id=review.id,
        action="created",
        operator_name=initiator_name,
        content=f"创建评审单，纳入 {len(cases)} 条用例。",
    )

    db.commit()
    return RedirectResponse(url=f"/case-reviews/{review.id}", status_code=303)


@router.get("/my-tasks", name="case_review_my_tasks")
def case_review_my_tasks_page(
    request: Request,
    reviewer_name: str = Query(default=""),
    db: Session = Depends(get_db),
):
    normalized_reviewer_name = reviewer_name.strip()

    query = (
        db.query(CaseReview)
        .options(
            joinedload(CaseReview.project),
            joinedload(CaseReview.requirement),
            joinedload(CaseReview.items).joinedload(CaseReviewItem.test_case),
        )
        .filter(CaseReview.status.in_(("pending", "in_review")))
        .order_by(CaseReview.deadline_at.asc().nulls_last(), CaseReview.created_at.desc())
    )
    if normalized_reviewer_name:
        query = query.filter(CaseReview.reviewer_name == normalized_reviewer_name)

    reviews = query.all()
    pending_item_count = sum(_build_review_stats(review.items)["pending"] for review in reviews)

    return templates.TemplateResponse(
        request,
        "case_reviews/my_tasks.html",
        {
            "request": request,
            "reviewer_name": normalized_reviewer_name,
            "reviews": reviews,
            "pending_review_count": len(reviews),
            "pending_item_count": pending_item_count,
            "build_review_stats": _build_review_stats,
        },
    )


@router.get("/results", name="case_review_results")
def case_review_results_page(
    request: Request,
    project_id: str = Query(default=""),
    db: Session = Depends(get_db),
):
    selected_project_id = _parse_optional_int(project_id)

    query = (
        db.query(CaseReview)
        .options(
            joinedload(CaseReview.project),
            joinedload(CaseReview.requirement),
            joinedload(CaseReview.items),
        )
        .filter(CaseReview.status == "completed")
        .order_by(CaseReview.completed_at.desc(), CaseReview.created_at.desc())
    )
    if selected_project_id is not None:
        query = query.filter(CaseReview.project_id == selected_project_id)

    projects = db.query(Project).order_by(Project.created_at.desc()).all()

    return templates.TemplateResponse(
        request,
        "case_reviews/results.html",
        {
            "request": request,
            "case_reviews": query.all(),
            "projects": projects,
            "selected_project_id": selected_project_id,
            "build_review_stats": _build_review_stats,
        },
    )


@router.get("/{review_id}", name="case_review_detail")
def case_review_detail_page(review_id: int, request: Request, db: Session = Depends(get_db)):
    review = _load_review(db, review_id, include_detail_relations=True)
    stats = _build_review_stats(review.items)
    return templates.TemplateResponse(
        request,
        "case_reviews/detail.html",
        {
            "request": request,
            "review": review,
            "stats": stats,
        },
    )


@router.post("/{review_id}/submit", name="case_review_submit")
def submit_case_review(review_id: int, request: Request, db: Session = Depends(get_db)):
    review = _load_review(db, review_id, include_detail_relations=False)
    if review.status not in {"draft", "pending"}:
        raise HTTPException(status_code=400, detail="Current review cannot be submitted.")

    review.status = "pending"
    review.updated_at = datetime.utcnow()
    _set_case_statuses([item.test_case for item in review.items if item.test_case is not None], "pending_review")
    _add_review_log(
        db,
        review_id=review.id,
        action="submitted",
        operator_name=review.initiator_name,
        content="评审单已提交，等待开始评审。",
    )
    db.commit()
    if _wants_json_response(request):
        return JSONResponse(_build_review_response_payload(review, message="评审单已提交。"))
    return RedirectResponse(url=f"/case-reviews/{review.id}", status_code=303)


@router.post("/{review_id}/start", name="case_review_start")
def start_case_review(review_id: int, request: Request, db: Session = Depends(get_db)):
    review = _load_review(db, review_id, include_detail_relations=False)
    if review.status not in {"draft", "pending", "in_review"}:
        raise HTTPException(status_code=400, detail="Current review cannot be started.")

    review.status = "in_review"
    review.started_at = review.started_at or datetime.utcnow()
    review.updated_at = datetime.utcnow()
    _set_case_statuses([item.test_case for item in review.items if item.test_case is not None], "in_review")
    _add_review_log(
        db,
        review_id=review.id,
        action="started",
        operator_name=review.reviewer_name,
        content="评审执行已开始。",
    )
    db.commit()
    if _wants_json_response(request):
        return JSONResponse(_build_review_response_payload(review, message="已进入评审执行。"))
    return RedirectResponse(url=f"/case-reviews/{review.id}", status_code=303)


@router.post("/{review_id}/items/{item_id}/decision", name="case_review_item_decision")
def update_case_review_item_decision(
    review_id: int,
    item_id: int,
    request: Request,
    decision: str = Form(...),
    comment: str = Form(default=""),
    reviewed_by: str = Form(default=""),
    db: Session = Depends(get_db),
):
    review = _load_review(db, review_id, include_detail_relations=False)
    item = next((candidate for candidate in review.items if candidate.id == item_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Review item not found.")
    if review.status == "completed":
        raise HTTPException(status_code=400, detail="Completed review cannot be changed.")

    normalized_decision = decision.strip()
    if normalized_decision not in FINAL_ITEM_DECISIONS:
        raise HTTPException(status_code=400, detail="Invalid review decision.")

    review.status = "in_review"
    review.started_at = review.started_at or datetime.utcnow()
    review.updated_at = datetime.utcnow()

    item.item_status = "reviewed"
    item.decision = normalized_decision
    item.comment = comment.strip() or None
    item.reviewed_by = reviewed_by.strip() or review.reviewer_name
    item.reviewed_at = datetime.utcnow()
    item.updated_at = datetime.utcnow()

    if item.test_case is not None:
        item.test_case.review_status = normalized_decision
        item.test_case.updated_at = datetime.utcnow()

    _add_review_log(
        db,
        review_id=review.id,
        review_item_id=item.id,
        action="item_decided",
        operator_name=item.reviewed_by,
        content=f"用例 {item.case_title_snapshot} 评审结论：{normalized_decision}",
    )
    db.commit()

    if _wants_json_response(request):
        payload = _build_review_response_payload(review, message="评审结论已保存。")
        payload["item"] = {
            "id": item.id,
            "decision": item.decision,
            "comment": item.comment or "",
            "reviewed_by": item.reviewed_by or "",
            "reviewed_at": item.reviewed_at.isoformat() if item.reviewed_at else "",
            "testcase_review_status": (
                item.test_case.review_status
                if item.test_case is not None and item.test_case.review_status
                else ""
            ),
        }
        return JSONResponse(
            payload
        )
    return RedirectResponse(url=f"/case-reviews/{review.id}", status_code=303)


@router.post("/{review_id}/complete", name="case_review_complete")
def complete_case_review(review_id: int, request: Request, db: Session = Depends(get_db)):
    review = _load_review(db, review_id, include_detail_relations=False)
    if review.status == "completed":
        if _wants_json_response(request):
            return JSONResponse(_build_review_response_payload(review, message="评审已完成。"))
        return RedirectResponse(url=f"/case-reviews/{review.id}", status_code=303)

    stats = _build_review_stats(review.items)
    if stats["pending"] > 0:
        raise HTTPException(status_code=400, detail="请先完成全部评审项，再提交最终评审结论。")

    review.status = "completed"
    review.completed_at = datetime.utcnow()
    review.updated_at = datetime.utcnow()

    for item in review.items:
        if item.test_case is not None and item.decision in FINAL_ITEM_DECISIONS:
            item.test_case.review_status = item.decision
            item.test_case.updated_at = datetime.utcnow()

    _add_review_log(
        db,
        review_id=review.id,
        action="completed",
        operator_name=review.reviewer_name,
        content=(
            f"评审完成：通过 {stats['approved']} 条，需修改 {stats['needs_update']} 条，"
            f"拒绝 {stats['rejected']} 条。"
        ),
    )
    db.commit()
    if _wants_json_response(request):
        return JSONResponse(_build_review_response_payload(review, message="最终评审结论已提交。"))
    return RedirectResponse(url=f"/case-reviews/{review.id}?completed=1", status_code=303)
