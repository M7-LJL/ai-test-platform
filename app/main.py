from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import Base, engine, ensure_application_schema, get_db
from app.models import Defect, Project, Requirement, TestCase, TestPlan, TestPlanCase, TestWorkflow
from app.routers.defects import router as defects_router
from app.routers.plans import router as plans_router
from app.routers.projects import router as projects_router
from app.routers.requirements import router as requirements_router
from app.routers.testcases import router as testcases_router
from app.routers.workflow import router as workflow_router
import app.models  # noqa: F401


BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "app" / "static"
TEMPLATES_DIR = BASE_DIR / "app" / "templates"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

app = FastAPI(
    title="Test Management MVP",
    description="A FastAPI-based test management platform powered by SQLAlchemy.",
    version="0.2.0",
)

Base.metadata.create_all(bind=engine)
ensure_application_schema()

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(projects_router)
app.include_router(requirements_router)
app.include_router(testcases_router)
app.include_router(workflow_router)
app.include_router(defects_router)
app.include_router(plans_router)


def _build_trend_series(records: list[object], days: int = 7) -> tuple[list[str], list[int]]:
    today = datetime.utcnow().date()
    timeline = [today - timedelta(days=offset) for offset in range(days - 1, -1, -1)]
    counts = {item: 0 for item in timeline}

    for record in records:
        created_at = getattr(record, "created_at", None)
        if created_at is None:
            continue
        created_date = created_at.date()
        if created_date in counts:
            counts[created_date] += 1

    labels = [item.strftime("%m-%d") for item in timeline]
    values = [counts[item] for item in timeline]
    return labels, values


def _build_conic_gradient(items: list[dict[str, object]], colors: list[str]) -> str:
    total = sum(int(item["value"]) for item in items if int(item["value"]) > 0)
    if total <= 0:
        return "conic-gradient(#e2e8f0 0deg 360deg)"

    start = 0.0
    segments: list[str] = []
    for index, item in enumerate(items):
        value = int(item["value"])
        if value <= 0:
            continue
        end = start + (value / total) * 360
        color = colors[index % len(colors)]
        segments.append(f"{color} {start:.1f}deg {end:.1f}deg")
        start = end

    if start < 360:
        segments.append(f"#e2e8f0 {start:.1f}deg 360deg")
    return "conic-gradient(" + ", ".join(segments) + ")"


@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    project_count = db.query(Project).count()
    requirement_count = db.query(Requirement).count()
    testcase_count = db.query(TestCase).count()
    plan_count = db.query(TestPlan).count()
    defect_count = db.query(Defect).count()
    workflow_count = db.query(TestWorkflow).count()

    recent_threshold = datetime.utcnow() - timedelta(days=6)
    recent_requirements = (
        db.query(Requirement)
        .filter(Requirement.created_at >= recent_threshold)
        .order_by(Requirement.created_at.asc())
        .all()
    )
    recent_defects = (
        db.query(Defect)
        .filter(Defect.created_at >= recent_threshold)
        .order_by(Defect.created_at.asc())
        .all()
    )
    trend_labels, requirement_trend = _build_trend_series(recent_requirements)
    _, defect_trend = _build_trend_series(recent_defects)

    workflow_stage_map = {
        "outline": "测试大纲",
        "analysis": "需求分析",
        "cases": "用例编写",
        "defects": "缺陷跟踪",
        "report": "报告输出",
    }
    workflow_counter = Counter(
        workflow_stage_map.get(item.current_stage, item.current_stage or "未分类")
        for item in db.query(TestWorkflow).all()
    )
    workflow_distribution = [
        {"label": label, "value": workflow_counter.get(label, 0)}
        for label in workflow_stage_map.values()
    ]
    workflow_gradient = _build_conic_gradient(
        workflow_distribution,
        ["#4f46e5", "#22c55e", "#f59e0b", "#ef4444", "#06b6d4"],
    )

    plan_case_counter = Counter(item.run_status or "untested" for item in db.query(TestPlanCase).all())
    executed_plan_cases = (
        db.query(TestPlanCase)
        .filter(TestPlanCase.run_status.in_(("passed", "failed", "blocked")))
        .all()
    )
    execution_distribution = [
        {"label": "未执行", "value": plan_case_counter.get("untested", 0)},
        {"label": "通过", "value": plan_case_counter.get("passed", 0)},
        {"label": "失败", "value": plan_case_counter.get("failed", 0)},
        {"label": "阻塞", "value": plan_case_counter.get("blocked", 0)},
    ]
    execution_gradient = _build_conic_gradient(
        execution_distribution,
        ["#cbd5e1", "#22c55e", "#ef4444", "#f59e0b"],
    )

    executed_total = (
        plan_case_counter.get("passed", 0)
        + plan_case_counter.get("failed", 0)
        + plan_case_counter.get("blocked", 0)
    )
    pass_rate = round((plan_case_counter.get("passed", 0) / executed_total) * 100) if executed_total else 0
    total_plan_cases = sum(item["value"] for item in execution_distribution)
    completion_rate = round((executed_total / total_plan_cases) * 100) if total_plan_cases else 0
    linked_execution_defect_count = db.query(Defect).filter(Defect.test_plan_case_id.is_not(None)).count()
    latest_execution_at = max((item.executed_at for item in executed_plan_cases if item.executed_at is not None), default=None)

    recent_projects = db.query(Project).order_by(Project.created_at.desc()).limit(5).all()
    recent_plans = db.query(TestPlan).order_by(TestPlan.created_at.desc()).limit(5).all()
    recent_defect_items = db.query(Defect).order_by(Defect.created_at.desc()).limit(5).all()

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "today_label": datetime.now().strftime("%Y年%m月%d日 %H:%M"),
            "metric_cards": [
                {"label": "项目总数", "value": project_count, "note": f"工作流 {workflow_count} 条", "tone": "blue"},
                {"label": "需求总数", "value": requirement_count, "note": f"近 7 天新增 {sum(requirement_trend)} 条", "tone": "orange"},
                {"label": "测试用例", "value": testcase_count, "note": f"执行计划 {plan_count} 个，完成率 {completion_rate}%", "tone": "green"},
                {"label": "缺陷总数", "value": defect_count, "note": f"执行关联缺陷 {linked_execution_defect_count} 条", "tone": "cyan"},
            ],
            "trend_labels": trend_labels,
            "requirement_trend": requirement_trend,
            "defect_trend": defect_trend,
            "workflow_distribution": workflow_distribution,
            "workflow_gradient": workflow_gradient,
            "execution_distribution": execution_distribution,
            "execution_gradient": execution_gradient,
            "recent_projects": recent_projects,
            "recent_plans": recent_plans,
            "recent_defects": recent_defect_items,
            "plan_count": plan_count,
            "executed_total": executed_total,
            "pass_rate": pass_rate,
            "completion_rate": completion_rate,
            "linked_execution_defect_count": linked_execution_defect_count,
            "latest_execution_label": latest_execution_at.strftime("%m-%d %H:%M") if latest_execution_at else "-",
        },
    )


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> RedirectResponse:
    return RedirectResponse(url="/static/favicon.svg")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "backend": "sqlalchemy"}

