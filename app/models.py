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
    test_cases: Mapped[list["TestCase"]] = relationship(
        "TestCase",
        back_populates="requirement",
    )
    review_points: Mapped[list["RequirementReviewPoint"]] = relationship(
        "RequirementReviewPoint",
        back_populates="requirement",
        cascade="all, delete-orphan",
        order_by="RequirementReviewPoint.sort_order",
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


class TestCase(Base):
    __tablename__ = "test_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
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

    manually_edited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    source_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    locked_case_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    project: Mapped["Project"] = relationship("Project", back_populates="test_cases")
    requirement: Mapped[Requirement | None] = relationship("Requirement", back_populates="test_cases")