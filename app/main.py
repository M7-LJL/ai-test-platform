from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.database import Base, engine, ensure_application_schema
from app.routers.projects import router as projects_router
from app.routers.requirements import router as requirements_router
from app.routers.testcases import router as testcases_router
from app.routers.workflow import router as workflow_router
import app.models  # noqa: F401


BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "app" / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

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
        <p>This FastAPI application provides a database-backed test management workflow.</p>
        <ul>
          <li>Visit <a href="/projects">/projects</a> for the HTML project pages</li>
          <li>Create and manage projects</li>
          <li>Upload Markdown requirements and generate structured test cases</li>
          <li>Edit and lock test cases to protect manual updates</li>
          <li>Import or export Markdown test cases</li>
        </ul>
        <p>Open <a href="/docs">/docs</a> for the interactive API documentation.</p>
      </body>
    </html>
    """


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> RedirectResponse:
    return RedirectResponse(url="/static/favicon.svg")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "backend": "sqlalchemy"}

