from __future__ import annotations

import io
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import Requirement, TestWorkflow, WorkflowStage
from app.services.workflow_ai_service import (
    STAGE_LABELS,
    STAGE_ORDER,
    STAGE_TYPES,
    generate_stage_content,
)
from app.services.ai_service import can_use_llm

router = APIRouter(prefix="/workflow", tags=["workflow-html"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _get_workflow(db: Session, workflow_id: int) -> TestWorkflow:
    wf = (
        db.query(TestWorkflow)
        .options(
            joinedload(TestWorkflow.stages),
            joinedload(TestWorkflow.project),
            joinedload(TestWorkflow.requirement),
        )
        .filter(TestWorkflow.id == workflow_id)
        .first()
    )
    if not wf:
        raise HTTPException(status_code=404, detail="工作流不存在")
    return wf


def _ensure_stages(db: Session, workflow: TestWorkflow) -> None:
    existing = {s.stage_type for s in workflow.stages}
    for stage_type in STAGE_TYPES:
        if stage_type not in existing:
            db.add(WorkflowStage(
                workflow_id=workflow.id,
                stage_type=stage_type,
                sort_order=STAGE_ORDER[stage_type],
            ))
    db.commit()
    db.refresh(workflow)


def _stages_dict(workflow: TestWorkflow) -> dict[str, WorkflowStage]:
    return {s.stage_type: s for s in workflow.stages}


@router.get("/new")
def new_workflow_redirect():
    """Standalone workflow creation is removed; redirect to projects."""
    return RedirectResponse(url="/projects", status_code=303)


@router.get("/{workflow_id}")
def workflow_detail(
    request: Request,
    workflow_id: int,
    stage: str = "outline",
    db: Session = Depends(get_db),
):
    wf = _get_workflow(db, workflow_id)
    _ensure_stages(db, wf)
    stages = _stages_dict(wf)

    if stage not in stages:
        stage = wf.current_stage

    current = stages[stage]
    stage_list = sorted(wf.stages, key=lambda s: STAGE_ORDER.get(s.stage_type, 99))

    return templates.TemplateResponse("workflow/detail.html", {
        "request": request,
        "workflow": wf,
        "stages": stage_list,
        "current_stage": current,
        "active_stage": stage,
        "stage_labels": STAGE_LABELS,
        "stage_types": STAGE_TYPES,
        "can_use_llm": can_use_llm(),
    })


@router.post("/{workflow_id}/stage/{stage_type}/generate")
def generate_stage(
    workflow_id: int,
    stage_type: str,
    db: Session = Depends(get_db),
):
    wf = _get_workflow(db, workflow_id)
    _ensure_stages(db, wf)
    stages = _stages_dict(wf)

    if stage_type not in stages:
        raise HTTPException(status_code=400, detail=f"无效阶段: {stage_type}")

    current = stages[stage_type]
    input_content = current.input_content or ""

    if not input_content.strip():
        prev_types = [t for t in STAGE_TYPES if STAGE_ORDER[t] < STAGE_ORDER[stage_type]]
        for pt in reversed(prev_types):
            prev = stages.get(pt)
            if prev and prev.output_content:
                input_content = prev.output_content
                break

    if not input_content.strip():
        raise HTTPException(status_code=400, detail="无输入内容，请先填写或完成上一阶段")

    current.status = "running"
    db.commit()

    try:
        result = generate_stage_content(stage_type, input_content)
        current.output_content = result["output"]
        current.ai_prompt_used = result["prompt_used"]
        current.status = "completed"
        current.completed_at = datetime.utcnow()

        idx = STAGE_ORDER[stage_type]
        next_types = [t for t in STAGE_TYPES if STAGE_ORDER[t] == idx + 1]
        if next_types:
            next_stage = stages.get(next_types[0])
            if next_stage and not next_stage.input_content:
                next_stage.input_content = result["output"]
            wf.current_stage = next_types[0]

        wf.status = "completed" if stage_type == "report" else "in_progress"
        db.commit()
    except Exception as exc:
        current.status = "failed"
        db.commit()
        raise HTTPException(status_code=500, detail=f"AI 生成失败: {exc}")

    if wf.requirement_id:
        return RedirectResponse(url=f"/requirements/{wf.requirement_id}#wf-stage-{stage_type}", status_code=303)
    return RedirectResponse(url=f"/workflow/{workflow_id}?stage={stage_type}", status_code=303)


@router.post("/{workflow_id}/stage/{stage_type}/save")
def save_stage(
    workflow_id: int,
    stage_type: str,
    input_content: str = Form(""),
    output_content: str = Form(""),
    db: Session = Depends(get_db),
):
    wf = _get_workflow(db, workflow_id)
    _ensure_stages(db, wf)
    stages = _stages_dict(wf)

    if stage_type not in stages:
        raise HTTPException(status_code=400, detail=f"无效阶段: {stage_type}")

    current = stages[stage_type]
    if input_content.strip():
        current.input_content = input_content.strip()
    if output_content.strip():
        current.output_content = output_content.strip()
        current.status = "completed"
        current.completed_at = datetime.utcnow()

        idx = STAGE_ORDER[stage_type]
        next_types = [t for t in STAGE_TYPES if STAGE_ORDER[t] == idx + 1]
        if next_types:
            next_stage = stages.get(next_types[0])
            if next_stage and not next_stage.input_content:
                next_stage.input_content = output_content.strip()

    db.commit()
    if wf.requirement_id:
        return RedirectResponse(url=f"/requirements/{wf.requirement_id}#wf-stage-{stage_type}", status_code=303)
    return RedirectResponse(url=f"/workflow/{workflow_id}?stage={stage_type}", status_code=303)


@router.get("/{workflow_id}/export")
def export_workflow(workflow_id: int, db: Session = Depends(get_db)):
    wf = _get_workflow(db, workflow_id)
    _ensure_stages(db, wf)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for stage in sorted(wf.stages, key=lambda s: STAGE_ORDER.get(s.stage_type, 99)):
            label = STAGE_LABELS.get(stage.stage_type, stage.stage_type)
            if stage.output_content:
                zf.writestr(
                    f"{STAGE_ORDER[stage.stage_type]+1}-{label}.md",
                    stage.output_content,
                )
    buf.seek(0)

    filename = f"workflow-{wf.name}-{wf.id}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@router.post("/{workflow_id}/delete")
def delete_workflow(workflow_id: int, db: Session = Depends(get_db)):
    wf = _get_workflow(db, workflow_id)
    db.delete(wf)
    db.commit()
    return RedirectResponse(url=f"/projects/{wf.project_id}", status_code=303)
