from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.database import Base


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    requirements: Mapped[list["Requirement"]] = relationship(
        "Requirement",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    test_cases: Mapped[list["TestCase"]] = relationship(
        "TestCase",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    test_suites: Mapped[list["TestSuite"]] = relationship(
        "TestSuite",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    test_plans: Mapped[list["TestPlan"]] = relationship(
        "TestPlan",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    defects: Mapped[list["Defect"]] = relationship(
        "Defect",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    workflows: Mapped[list["TestWorkflow"]] = relationship(
        "TestWorkflow",
        back_populates="project",
        cascade="all, delete-orphan",
    )


class Requirement(Base):
    __tablename__ = "requirements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    parsed_points: Mapped[list[str] | list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    analysis_status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False)
    analysis_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    core_regression_points: Mapped[list[str] | list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    tool_plan: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    tool_result: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    last_analyzed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    project: Mapped["Project"] = relationship("Project", back_populates="requirements")
    test_cases: Mapped[list["TestCase"]] = relationship("TestCase", back_populates="requirement")
    review_points: Mapped[list["RequirementReviewPoint"]] = relationship(
        "RequirementReviewPoint",
        back_populates="requirement",
        cascade="all, delete-orphan",
        order_by="RequirementReviewPoint.sort_order",
    )
    workflows: Mapped[list["TestWorkflow"]] = relationship(
        "TestWorkflow",
        back_populates="requirement",
    )
    test_plans: Mapped[list["TestPlan"]] = relationship(
        "TestPlan",
        back_populates="requirement",
    )
    defects: Mapped[list["Defect"]] = relationship(
        "Defect",
        back_populates="requirement",
    )


class RequirementReviewPoint(Base):
    __tablename__ = "requirement_review_points"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    requirement_id: Mapped[int] = mapped_column(ForeignKey("requirements.id"), nullable=False, index=True)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(20), default="functional", nullable=False)
    module: Mapped[str | None] = mapped_column(String(100), nullable=True)
    context: Mapped[str | None] = mapped_column(String(255), nullable=True)
    requirement_source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    preconditions: Mapped[str | None] = mapped_column(Text, nullable=True)
    steps: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_selected: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_core: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source: Mapped[str] = mapped_column(String(20), default="ai", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    requirement: Mapped["Requirement"] = relationship("Requirement", back_populates="review_points")


class TestSuite(Base):
    __tablename__ = "test_suites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    project: Mapped["Project"] = relationship("Project", back_populates="test_suites")
    test_cases: Mapped[list["TestCase"]] = relationship("TestCase", back_populates="suite")


class TestCase(Base):
    __tablename__ = "test_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    suite_id: Mapped[int | None] = mapped_column(ForeignKey("test_suites.id"), nullable=True, index=True)
    requirement_id: Mapped[int | None] = mapped_column(
        ForeignKey("requirements.id"),
        nullable=True,
        index=True,
    )
    case_id: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    module: Mapped[str | None] = mapped_column(String(100), nullable=True)
    priority: Mapped[str | None] = mapped_column(String(20), nullable=True)
    case_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    test_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    requirement_source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    preconditions: Mapped[str | None] = mapped_column(Text, nullable=True)
    steps: Mapped[str] = mapped_column(Text, nullable=False)
    expected: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False)
    source: Mapped[str] = mapped_column(String(30), default="ai_generated", nullable=False)
    review_status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False)
    last_editor: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    manually_edited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    locked_case_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    project: Mapped["Project"] = relationship("Project", back_populates="test_cases")
    suite: Mapped["TestSuite | None"] = relationship("TestSuite", back_populates="test_cases")
    requirement: Mapped["Requirement | None"] = relationship("Requirement", back_populates="test_cases")
    plan_cases: Mapped[list["TestPlanCase"]] = relationship(
        "TestPlanCase",
        back_populates="test_case",
        cascade="all, delete-orphan",
    )
    defects: Mapped[list["Defect"]] = relationship("Defect", back_populates="test_case")


class TestPlan(Base):
    __tablename__ = "test_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    requirement_id: Mapped[int | None] = mapped_column(
        ForeignKey("requirements.id"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False)
    owner: Mapped[str | None] = mapped_column(String(100), nullable=True)
    planned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    project: Mapped["Project"] = relationship("Project", back_populates="test_plans")
    requirement: Mapped["Requirement | None"] = relationship("Requirement", back_populates="test_plans")
    plan_cases: Mapped[list["TestPlanCase"]] = relationship(
        "TestPlanCase",
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="TestPlanCase.sort_order",
    )


class TestPlanCase(Base):
    __tablename__ = "test_plan_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("test_plans.id"), nullable=False, index=True)
    test_case_id: Mapped[int] = mapped_column(ForeignKey("test_cases.id"), nullable=False, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    run_status: Mapped[str] = mapped_column(String(30), default="untested", nullable=False)
    executed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    result_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    actual_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_result_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    environment_info: Mapped[str | None] = mapped_column(Text, nullable=True)
    attachments: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    plan: Mapped["TestPlan"] = relationship("TestPlan", back_populates="plan_cases")
    test_case: Mapped["TestCase"] = relationship("TestCase", back_populates="plan_cases")
    defects: Mapped[list["Defect"]] = relationship("Defect", back_populates="test_plan_case")


class Defect(Base):
    __tablename__ = "defects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    requirement_id: Mapped[int | None] = mapped_column(
        ForeignKey("requirements.id"),
        nullable=True,
        index=True,
    )
    test_case_id: Mapped[int | None] = mapped_column(
        ForeignKey("test_cases.id"),
        nullable=True,
        index=True,
    )
    test_plan_case_id: Mapped[int | None] = mapped_column(
        ForeignKey("test_plan_cases.id"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    severity: Mapped[str] = mapped_column(String(30), default="major", nullable=False)
    priority: Mapped[str] = mapped_column(String(20), default="P2", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="open", nullable=False)
    steps_to_reproduce: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    actual_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    project: Mapped["Project"] = relationship("Project", back_populates="defects")
    requirement: Mapped["Requirement | None"] = relationship("Requirement", back_populates="defects")
    test_case: Mapped["TestCase | None"] = relationship("TestCase", back_populates="defects")
    test_plan_case: Mapped["TestPlanCase | None"] = relationship("TestPlanCase", back_populates="defects")



class TestWorkflow(Base):
    __tablename__ = "test_workflows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    requirement_id: Mapped[int | None] = mapped_column(ForeignKey("requirements.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False)
    current_stage: Mapped[str] = mapped_column(String(30), default="outline", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    output_base_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    confirmed_stage: Mapped[str | None] = mapped_column(String(30), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    workflow_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_meta: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    project: Mapped["Project"] = relationship("Project", back_populates="workflows")
    requirement: Mapped["Requirement | None"] = relationship("Requirement", back_populates="workflows")
    stages: Mapped[list["WorkflowStage"]] = relationship(
        "WorkflowStage",
        back_populates="workflow",
        cascade="all, delete-orphan",
        order_by="WorkflowStage.sort_order",
    )

class WorkflowStage(Base):
    __tablename__ = "workflow_stages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("test_workflows.id"), nullable=False, index=True)
    stage_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    input_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_prompt_used: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    workflow: Mapped["TestWorkflow"] = relationship("TestWorkflow", back_populates="stages")