from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import html
import re
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.database import Base, engine
from app.routers.projects import router as projects_router
from app.routers.requirements import router as requirements_router
from app.routers.testcases import router as testcases_router
import app.models  # noqa: F401


BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "app" / "static"
REPORTS_DIR = Path(os.getenv("REPORTS_DIR", str(BASE_DIR / "reports")))
STATIC_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="Test Management MVP",
    description="A minimal FastAPI-based test management platform.",
    version="0.1.0",
)
Base.metadata.create_all(bind=engine)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(projects_router)
app.include_router(requirements_router)
app.include_router(testcases_router)


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)


class ProjectRecord(ProjectCreate):
    id: str
    created_at: str
    requirement_ids: list[str] = Field(default_factory=list)
    test_case_ids: list[str] = Field(default_factory=list)
    report_ids: list[str] = Field(default_factory=list)


class RequirementRecord(BaseModel):
    id: str
    project_id: str
    source_name: str
    content: str
    extracted_points: list[str]
    created_at: str


class TestCaseCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    steps: str = Field(..., min_length=1)
    expected_result: str = Field(..., min_length=1)
    source: str = Field(default="manual", max_length=50)
    requirement_id: str | None = None


class TestCaseRecord(TestCaseCreate):
    id: str
    project_id: str
    created_at: str


class ReportRecord(BaseModel):
    id: str
    project_id: str
    file_name: str
    file_path: str
    total_cases: int
    manual_cases: int
    ai_cases: int
    created_at: str


projects: dict[str, ProjectRecord] = {}
requirements_store: dict[str, RequirementRecord] = {}
test_cases_store: dict[str, TestCaseRecord] = {}
reports_store: dict[str, ReportRecord] = {}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_project(project_id: str) -> ProjectRecord:
    project = projects.get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return project


def get_requirement(project_id: str, requirement_id: str) -> RequirementRecord:
    requirement = requirements_store.get(requirement_id)
    if requirement is None or requirement.project_id != project_id:
        raise HTTPException(status_code=404, detail="Requirement not found.")
    return requirement


def simulate_ai_extract_test_points(requirement_text: str) -> list[str]:
    # This keeps the MVP self-contained while preserving the AI workflow.
    raw_chunks = re.split(r"[\r\n]+|(?<=[.!?])\s+|(?<=[。！？])", requirement_text)
    candidate_chunks: list[str] = []

    for chunk in raw_chunks:
        cleaned = re.sub(r"^\s*[-*0-9.)]+\s*", "", chunk).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        if len(cleaned) >= 8:
            candidate_chunks.append(cleaned)

    if not candidate_chunks:
        fallback = requirement_text.strip()
        if fallback:
            candidate_chunks.append(re.sub(r"\s+", " ", fallback))

    extracted_points: list[str] = []
    for index, chunk in enumerate(candidate_chunks[:10], start=1):
        snippet = chunk if len(chunk) <= 120 else f"{chunk[:117]}..."
        extracted_points.append(f"Validate scenario {index}: {snippet}")

    return extracted_points


def build_test_case_from_point(
    project_id: str,
    point: str,
    requirement_id: str | None,
    source: str,
) -> TestCaseRecord:
    case_id = uuid4().hex[:8]
    test_case = TestCaseRecord(
        id=case_id,
        project_id=project_id,
        title=point,
        steps=f"1. Open the target flow.\n2. Execute the scenario described by: {point}",
        expected_result=f"The system behaves as expected for: {point}",
        source=source,
        requirement_id=requirement_id,
        created_at=now_iso(),
    )
    test_cases_store[case_id] = test_case
    projects[project_id].test_case_ids.append(case_id)
    return test_case


def render_report_html(project: ProjectRecord, cases: list[TestCaseRecord], report: ReportRecord) -> str:
    rows = "\n".join(
        (
            "<tr>"
            f"<td>{index}</td>"
            f"<td>{html.escape(case.title)}</td>"
            f"<td>{html.escape(case.source)}</td>"
            f"<td><pre>{html.escape(case.steps)}</pre></td>"
            f"<td><pre>{html.escape(case.expected_result)}</pre></td>"
            "</tr>"
        )
        for index, case in enumerate(cases, start=1)
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Test Report - {html.escape(project.name)}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 32px; color: #1f2937; }}
    h1, h2 {{ margin-bottom: 8px; }}
    .meta {{ margin-bottom: 24px; }}
    .cards {{ display: flex; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }}
    .card {{ border: 1px solid #d1d5db; border-radius: 8px; padding: 16px; min-width: 180px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border: 1px solid #d1d5db; padding: 12px; text-align: left; vertical-align: top; }}
    th {{ background: #f3f4f6; }}
    pre {{ white-space: pre-wrap; margin: 0; font-family: inherit; }}
  </style>
</head>
<body>
  <h1>Test Report</h1>
  <div class="meta">
    <p><strong>Project:</strong> {html.escape(project.name)}</p>
    <p><strong>Generated at:</strong> {html.escape(report.created_at)}</p>
    <p><strong>Report ID:</strong> {html.escape(report.id)}</p>
  </div>

  <div class="cards">
    <div class="card"><strong>Total cases</strong><br />{report.total_cases}</div>
    <div class="card"><strong>Manual cases</strong><br />{report.manual_cases}</div>
    <div class="card"><strong>AI-derived cases</strong><br />{report.ai_cases}</div>
  </div>

  <h2>Case Details</h2>
  <table>
    <thead>
      <tr>
        <th>#</th>
        <th>Title</th>
        <th>Source</th>
        <th>Steps</th>
        <th>Expected Result</th>
      </tr>
    </thead>
    <tbody>
      {rows}
    </tbody>
  </table>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return """
    <html>
      <head>
        <title>Test Management MVP</title>
        <link rel="icon" href="/static/favicon.svg" type="image/svg+xml" />
      </head>
      <body style="font-family: Arial, sans-serif; margin: 32px;">
        <h1>Test Management Platform MVP</h1>
        <p>This FastAPI application provides a minimal test management workflow.</p>
        <ul>
          <li>Visit <a href="/projects">/projects</a> for the HTML project pages</li>
          <li>Create and list projects</li>
          <li>Upload requirement text and simulate AI test point extraction</li>
          <li>Create manual or AI-derived test cases</li>
          <li>Generate HTML test reports</li>
        </ul>
        <p>Open <a href="/docs">/docs</a> for the interactive API documentation.</p>
      </body>
    </html>
    """


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> RedirectResponse:
    return RedirectResponse(url="/static/favicon.svg")


@app.post("/projects", response_model=ProjectRecord)
def create_project(payload: ProjectCreate) -> ProjectRecord:
    project_id = uuid4().hex[:8]
    project = ProjectRecord(
        id=project_id,
        name=payload.name,
        description=payload.description,
        created_at=now_iso(),
    )
    projects[project_id] = project
    return project


@app.get("/api/projects", response_model=list[ProjectRecord])
def list_projects() -> list[ProjectRecord]:
    return list(projects.values())


@app.post("/projects/{project_id}/requirements", response_model=RequirementRecord)
async def upload_requirement(
    project_id: str,
    requirement_text: str | None = Form(default=None),
    requirement_file: UploadFile | None = File(default=None),
) -> RequirementRecord:
    project = get_project(project_id)

    file_text = ""
    source_name = "inline-text"
    if requirement_file is not None:
        raw_bytes = await requirement_file.read()
        file_text = raw_bytes.decode("utf-8", errors="ignore")
        source_name = requirement_file.filename or "uploaded.txt"

    content = (requirement_text or "").strip() or file_text.strip()
    if not content:
        raise HTTPException(
            status_code=400,
            detail="Provide requirement_text or upload a text file.",
        )

    requirement_id = uuid4().hex[:8]
    record = RequirementRecord(
        id=requirement_id,
        project_id=project_id,
        source_name=source_name,
        content=content,
        extracted_points=simulate_ai_extract_test_points(content),
        created_at=now_iso(),
    )
    requirements_store[requirement_id] = record
    project.requirement_ids.append(requirement_id)
    return record


@app.get("/projects/{project_id}/requirements", response_model=list[RequirementRecord])
def list_requirements(project_id: str) -> list[RequirementRecord]:
    project = get_project(project_id)
    return [requirements_store[requirement_id] for requirement_id in project.requirement_ids]


@app.post("/projects/{project_id}/test-cases", response_model=TestCaseRecord)
def create_test_case(project_id: str, payload: TestCaseCreate) -> TestCaseRecord:
    get_project(project_id)

    if payload.requirement_id is not None:
        get_requirement(project_id, payload.requirement_id)

    case_id = uuid4().hex[:8]
    test_case = TestCaseRecord(
        id=case_id,
        project_id=project_id,
        title=payload.title,
        steps=payload.steps,
        expected_result=payload.expected_result,
        source=payload.source,
        requirement_id=payload.requirement_id,
        created_at=now_iso(),
    )
    test_cases_store[case_id] = test_case
    projects[project_id].test_case_ids.append(case_id)
    return test_case


@app.post(
    "/projects/{project_id}/test-cases/from-requirement/{requirement_id}",
    response_model=list[TestCaseRecord],
)
def create_test_cases_from_requirement(project_id: str, requirement_id: str) -> list[TestCaseRecord]:
    requirement = get_requirement(project_id, requirement_id)

    created_cases = [
        build_test_case_from_point(
            project_id=project_id,
            point=point,
            requirement_id=requirement_id,
            source="ai-simulated",
        )
        for point in requirement.extracted_points
    ]
    return created_cases


@app.get("/projects/{project_id}/test-cases", response_model=list[TestCaseRecord])
def list_test_cases(project_id: str) -> list[TestCaseRecord]:
    project = get_project(project_id)
    return [test_cases_store[test_case_id] for test_case_id in project.test_case_ids]


@app.post("/projects/{project_id}/reports", response_model=ReportRecord)
def generate_report(project_id: str) -> ReportRecord:
    project = get_project(project_id)
    cases = [test_cases_store[test_case_id] for test_case_id in project.test_case_ids]

    if not cases:
        raise HTTPException(status_code=400, detail="No test cases found for this project.")

    report_id = uuid4().hex[:8]
    file_name = f"report_{project_id}_{report_id}.html"
    file_path = REPORTS_DIR / file_name

    manual_cases = sum(1 for case in cases if case.source == "manual")
    ai_cases = len(cases) - manual_cases

    report = ReportRecord(
        id=report_id,
        project_id=project_id,
        file_name=file_name,
        file_path=str(file_path),
        total_cases=len(cases),
        manual_cases=manual_cases,
        ai_cases=ai_cases,
        created_at=now_iso(),
    )
    file_path.write_text(render_report_html(project, cases, report), encoding="utf-8")

    reports_store[report_id] = report
    project.report_ids.append(report_id)
    return report


@app.get("/projects/{project_id}/reports", response_model=list[ReportRecord])
def list_reports(project_id: str) -> list[ReportRecord]:
    project = get_project(project_id)
    return [reports_store[report_id] for report_id in project.report_ids]


@app.get("/reports/{report_id}")
def view_report(report_id: str) -> FileResponse:
    report = reports_store.get(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found.")
    return FileResponse(report.file_path, media_type="text/html", filename=report.file_name)
