from collections.abc import Generator
import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


BASE_DIR = Path(__file__).resolve().parent.parent


def _normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgresql://") and "+psycopg" not in database_url:
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


default_sqlite_path = (BASE_DIR / "test_management.db").as_posix()
SQLALCHEMY_DATABASE_URL = _normalize_database_url(
    os.getenv("DATABASE_URL", f"sqlite:///{default_sqlite_path}")
)

engine_kwargs: dict[str, object] = {"pool_pre_ping": True}
if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(SQLALCHEMY_DATABASE_URL, **engine_kwargs)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


class Base(DeclarativeBase):
    pass

# app/database.py
def ensure_application_schema() -> None:
    inspector = inspect(engine)

    existing_tables = set(inspector.get_table_names())
    if "requirements" in existing_tables:
        requirement_columns = {column["name"] for column in inspector.get_columns("requirements")}
        requirement_additions = {
            "analysis_status": "ALTER TABLE requirements ADD COLUMN analysis_status VARCHAR(30) DEFAULT 'draft' NOT NULL",
            "analysis_payload": "ALTER TABLE requirements ADD COLUMN analysis_payload JSON",
            "review_notes": "ALTER TABLE requirements ADD COLUMN review_notes TEXT",
            "core_regression_points": "ALTER TABLE requirements ADD COLUMN core_regression_points JSON",
            "tool_plan": "ALTER TABLE requirements ADD COLUMN tool_plan JSON",
            "tool_result": "ALTER TABLE requirements ADD COLUMN tool_result JSON",
            "last_analyzed_at": "ALTER TABLE requirements ADD COLUMN last_analyzed_at DATETIME",
            "reviewed_at": "ALTER TABLE requirements ADD COLUMN reviewed_at DATETIME",
        }
        missing_requirement_columns = [
            ddl for name, ddl in requirement_additions.items() if name not in requirement_columns
        ]
    else:
        missing_requirement_columns = []

    if "test_suites" in existing_tables:
        suite_columns = {column["name"] for column in inspector.get_columns("test_suites")}
        suite_column_map = {
            "is_archived": "ALTER TABLE test_suites ADD COLUMN is_archived BOOLEAN DEFAULT 0 NOT NULL",
        }
        suite_additions = [
            ddl for name, ddl in suite_column_map.items() if name not in suite_columns
        ]
    else:
        suite_additions = []

    if "test_cases" in existing_tables:
        testcase_columns = {column["name"] for column in inspector.get_columns("test_cases")}
        testcase_additions = {
            "source": "ALTER TABLE test_cases ADD COLUMN source VARCHAR(30) DEFAULT 'ai_generated' NOT NULL",
            "review_status": "ALTER TABLE test_cases ADD COLUMN review_status VARCHAR(30) DEFAULT 'draft' NOT NULL",
            "case_type": "ALTER TABLE test_cases ADD COLUMN case_type VARCHAR(20)",
            "test_data": "ALTER TABLE test_cases ADD COLUMN test_data TEXT",
            "requirement_source": "ALTER TABLE test_cases ADD COLUMN requirement_source VARCHAR(255)",
            "manually_edited": "ALTER TABLE test_cases ADD COLUMN manually_edited BOOLEAN DEFAULT 0 NOT NULL",
            "locked": "ALTER TABLE test_cases ADD COLUMN locked BOOLEAN DEFAULT 0 NOT NULL",
            "source_version": "ALTER TABLE test_cases ADD COLUMN source_version VARCHAR(50)",
            "locked_case_data": "ALTER TABLE test_cases ADD COLUMN locked_case_data JSON",
            "last_editor": "ALTER TABLE test_cases ADD COLUMN last_editor VARCHAR(100)",
            "is_archived": "ALTER TABLE test_cases ADD COLUMN is_archived BOOLEAN DEFAULT 0 NOT NULL",
            "updated_at": "ALTER TABLE test_cases ADD COLUMN updated_at DATETIME",
        }
        missing_testcase_columns = [
            ddl for name, ddl in testcase_additions.items() if name not in testcase_columns
        ]
    else:
        missing_testcase_columns = []

    if "test_workflows" in existing_tables:
        workflow_columns =  {column["name"] for column in inspector.get_columns("test_workflows")}
        workflow_additions = {

            "requirement_id": "ALTER TABLE test_workflows ADD COLUMN requirement_id INTEGER REFERENCES requirements(id)",
            "output_base_path": "ALTER TABLE test_workflows ADD COLUMN output_base_path VARCHAR(500)",
            "confirmed_stage": "ALTER TABLE test_workflows ADD COLUMN confirmed_stage VARCHAR(30)",
            "started_at": "ALTER TABLE test_workflows ADD COLUMN started_at DATETIME",
            "updated_at": "ALTER TABLE test_workflows ADD COLUMN updated_at DATETIME",
            "completed_at": "ALTER TABLE test_workflows ADD COLUMN completed_at DATETIME",
            "workflow_version": "ALTER TABLE test_workflows ADD COLUMN workflow_version VARCHAR(20)",
            "source_type": "ALTER TABLE test_workflows ADD COLUMN source_type VARCHAR(50)",
            "source_meta": "ALTER TABLE test_workflows ADD COLUMN source_meta JSON",
        }
        missing_workflow_columns = [
            ddl for name, ddl in workflow_additions.items() if name not in workflow_columns
        ]
    else:
        missing_workflow_columns = []

    if "test_plan_cases" in existing_tables:
        test_plan_case_columns = {column["name"] for column in inspector.get_columns("test_plan_cases")}
        test_plan_case_additions = {
            "actual_result": "ALTER TABLE test_plan_cases ADD COLUMN actual_result TEXT",
            "expected_result_snapshot": "ALTER TABLE test_plan_cases ADD COLUMN expected_result_snapshot TEXT",
            "environment_info": "ALTER TABLE test_plan_cases ADD COLUMN environment_info TEXT",
            "attachments": "ALTER TABLE test_plan_cases ADD COLUMN attachments JSON",
        }
        missing_test_plan_case_columns = [
            ddl for name, ddl in test_plan_case_additions.items() if name not in test_plan_case_columns
        ]
    else:
        missing_test_plan_case_columns = []

    with engine.begin() as connection:
        for ddl in (
            *missing_requirement_columns,
            *suite_additions,
            *missing_testcase_columns,
            *missing_workflow_columns,
            *missing_test_plan_case_columns,
        ):
            connection.execute(text(ddl))


    from app.models import (
        CaseReview,
        CaseReviewItem,
        CaseReviewLog,
        RequirementReviewPoint,
        TestWorkflow,
        WorkflowStage,
    )

    RequirementReviewPoint.__table__.create(bind=engine, checkfirst=True)
    CaseReview.__table__.create(bind=engine, checkfirst=True)
    CaseReviewItem.__table__.create(bind=engine, checkfirst=True)
    CaseReviewLog.__table__.create(bind=engine, checkfirst=True)
    TestWorkflow.__table__.create(bind=engine, checkfirst=True)
    WorkflowStage.__table__.create(bind=engine, checkfirst=True)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
