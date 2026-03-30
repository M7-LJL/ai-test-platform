from __future__ import annotations

import io
import re
import zipfile
from datetime import datetime
import json
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import Requirement, TestWorkflow, WorkflowStage
from app.routers.testcases import _append_requirement_tool_result, _sync_requirement_cases
from app.services.ai_service import build_requirement_analysis, can_use_llm, render_requirement_analysis_markdown
from app.services.workflow_ai_service import (
    STAGE_LABELS,
    STAGE_ORDER,
    STAGE_TYPES,
    generate_placeholder_content,
    generate_stage_content,
)
from app.services.xmind_markdown_service import generate_structured_cases, generate_xmind_markdown, parse_xmind_markdown

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


def _form_bool_use_llm(raw: str | None) -> bool:
    if raw is None:
        return False
    return raw.strip().lower() in ("true", "1", "on", "yes")


def _clean_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


IDENTIFIER_PATTERNS: tuple[str, ...] = (
    r"/[A-Za-z0-9/_\-.?=&%:{}]+",
    r"\b[a-z]+(?:_[a-z0-9]+){1,}\b",
    r"\b[A-Za-z][A-Za-z0-9_-]*\.[A-Za-z0-9._/-]+\b",
)


def _extract_identifier_candidates(text: str) -> list[str]:
    normalized = text or ""
    identifiers: list[str] = []
    for pattern in IDENTIFIER_PATTERNS:
        for match in re.findall(pattern, normalized):
            candidate = _clean_text(match)
            if not candidate or len(candidate) < 4:
                continue
            if candidate not in identifiers:
                identifiers.append(candidate)
    return identifiers


def _identifier_evidence_text(workflow: TestWorkflow, stages: dict[str, WorkflowStage]) -> str:
    parts: list[str] = []
    requirement = workflow.requirement
    if requirement is not None:
        if requirement.content:
            parts.append(requirement.content)
        if requirement.review_notes:
            parts.append(requirement.review_notes)
    outline_stage = stages.get("outline")
    if outline_stage and outline_stage.input_content:
        parts.append(outline_stage.input_content)
    return "\n".join(parts)


def _sanitize_generated_output_identifiers(output: str, evidence_text: str) -> str:
    if not output.strip():
        return output
    source = _clean_text(evidence_text).lower()
    if not source:
        return output
    sanitized = output
    for fragment in re.findall(r"`[^`\n]+`", output):
        inner = fragment.strip("`")
        inner_candidates = _extract_identifier_candidates(inner)
        if not inner_candidates:
            continue
        if any(candidate.lower() not in source for candidate in inner_candidates):
            sanitized = sanitized.replace(fragment, "`待确认`")
    for assignment in re.findall(r"\b([a-z]+(?:_[a-z0-9]+){1,})\s*=\s*([^\s，,；;）)\]]+)", output):
        key, value = assignment
        if key.lower() in source:
            continue
        sanitized = re.sub(
            rf"\b{re.escape(key)}\s*=\s*{re.escape(value)}",
            "待确认",
            sanitized,
            flags=re.IGNORECASE,
        )
    for candidate in _extract_identifier_candidates(output):
        if candidate.lower() in source:
            continue
        sanitized = re.sub(re.escape(candidate), "待确认", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"(待确认[\s/、，,;；]*){2,}", "待确认 ", sanitized)
    return sanitized


def _normalized_string_list(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    result: list[str] = []
    for value in values:
        cleaned = _clean_text(value)
        if cleaned and cleaned not in result:
            result.append(cleaned)
    return result


def _truncate_text(text: str, max_chars: int) -> str:
    normalized = (text or "").strip()
    if len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars].rstrip() + "\n\n...（内容已截断，保留前半段重点信息）"


def _normalize_analysis_heading_title(title: str) -> str:
    cleaned = re.sub(r"^\d+\s*[\.\、]\s*", "", (title or "")).strip()
    if "术语" in cleaned or "缩写" in cleaned:
        return "术语与缩写"
    if "测试范围" in cleaned:
        return "测试范围"
    if "候选测试点" in cleaned or cleaned == "测试点":
        return "测试点"
    if "需求疑义" in cleaned or "待确认项" in cleaned:
        return "需求疑义与遗漏"
    if "需求追溯" in cleaned or "术语与追溯" in cleaned:
        return "需求追溯"
    if "自检" in cleaned:
        return "自检"
    return cleaned


def _normalize_analysis_output_markdown(content: str) -> str:
    lines = (content or "").splitlines()
    if not lines:
        return ""

    h2_indices = [
        idx for idx, raw_line in enumerate(lines)
        if re.match(r"^##\s+", raw_line.strip())
    ]
    if not h2_indices:
        return (content or "").strip()

    first_h2_title = re.sub(r"^##\s*", "", lines[h2_indices[0]].strip())
    starts_from_zero = "术语" in first_h2_title or "缩写" in first_h2_title
    next_number = 0 if starts_from_zero else 1

    normalized_lines: list[str] = []
    for raw_line in lines:
        stripped = raw_line.strip()
        if re.match(r"^##\s+", stripped):
            title = re.sub(r"^##\s*", "", stripped)
            normalized_title = _normalize_analysis_heading_title(title)
            normalized_lines.append(f"## {next_number}. {normalized_title}")
            next_number += 1
            continue
        if re.match(r"^###\s+", stripped):
            title = re.sub(r"^###\s*", "", stripped)
            title = re.sub(r"^[一二三四五六七八九十0-9]+[（(]?[补]?[)）]?[\.\、]?\s*", "", title).strip()
            if "功能点穷尽清单" in title:
                normalized_lines.append("### 一、功能点穷尽清单（按维度遍历）")
                continue
            if "真实用户使用场景补充" in title or "真实用户场景补充" in title:
                normalized_lines.append("### 一（补）、真实用户使用场景补充")
                continue
        normalized_lines.append(raw_line)
    return "\n".join(normalized_lines).strip()


def _extract_outline_modules(outline_content: str) -> list[str]:
    modules: list[str] = []
    for raw_line in (outline_content or "").splitlines():
        stripped = raw_line.strip()
        if not stripped.startswith("## "):
            continue
        module_name = _clean_text(stripped[3:])
        if module_name and module_name not in modules:
            modules.append(module_name)
    return modules


def _collect_reviewed_points(requirement: Requirement | None) -> list[dict[str, str]]:
    if requirement is None or not isinstance(requirement.analysis_payload, dict):
        return []

    payload = requirement.analysis_payload
    review_payload = payload.get("review") if isinstance(payload.get("review"), dict) else {}
    reviewed_rows = review_payload.get("reviewed_test_points")
    rows = reviewed_rows if isinstance(reviewed_rows, list) and reviewed_rows else payload.get("test_points", [])
    if not isinstance(rows, list):
        return []

    result: list[dict[str, str]] = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        selected = raw.get("selected")
        if selected is False:
            continue
        title = _clean_text(raw.get("title"))
        if not title:
            continue
        result.append(
            {
                "module": _clean_text(raw.get("module")) or requirement.title,
                "title": title,
                "category": _clean_text(raw.get("category")) or "functional",
                "priority": _clean_text(raw.get("priority")) or "P1",
                "source_refs": _clean_text(raw.get("source_refs")) or _clean_text(raw.get("requirement_source")) or "需求原文",
                "page_or_entry": _clean_text(raw.get("page_or_entry")) or _clean_text(raw.get("context")) or "需求原文",
                "action": _clean_text(raw.get("action")) or title,
                "verification_focus": _clean_text(raw.get("verification_focus")),
                "preconditions": _clean_text(raw.get("preconditions")),
                "user_scenario_tag": _clean_text(raw.get("user_scenario_tag")),
            }
        )
    return result


def _build_review_points_markdown(points: list[dict[str, str]], max_items: int = 24) -> str:
    if not points:
        return "- 暂无人工确认测试点"

    lines: list[str] = []
    for point in points[:max_items]:
        lines.append(f"- 模块：{point['module']} | 类型：{point['category']} | 优先级：{point['priority']}")
        lines.append(f"  - 测试点：{point['title']}")
        lines.append(f"  - 页面/入口：{point['page_or_entry'] or '需求原文'}")
        lines.append(f"  - 动作：{point['action'] or point['title']}")
        if point["preconditions"]:
            lines.append(f"  - 前置条件：{point['preconditions']}")
        if point["verification_focus"]:
            lines.append(f"  - 验证重点：{point['verification_focus']}")
        if point["user_scenario_tag"]:
            lines.append(f"  - 真实用户场景：{point['user_scenario_tag']}")
        lines.append(f"  - 需求来源：{point['source_refs']}")
    if len(points) > max_items:
        lines.append(f"- 其余 {len(points) - max_items} 条人工确认测试点已省略")
    return "\n".join(lines)


def _build_stage_generation_context(
    workflow: TestWorkflow,
    stages: dict[str, WorkflowStage],
    stage_type: str,
    input_content: str,
) -> str:
    if stage_type not in {"analysis", "plan", "cases"}:
        return input_content

    requirement = workflow.requirement
    if requirement is None:
        return input_content

    requirement_title = requirement.title.strip() or workflow.name
    outline_output = (stages.get("outline").output_content if stages.get("outline") else "") or ""
    analysis_output = (stages.get("analysis").output_content if stages.get("analysis") else "") or ""
    plan_output = (stages.get("plan").output_content if stages.get("plan") else "") or ""
    structured_analysis_payload = build_requirement_analysis(
        requirement.content,
        title=requirement_title,
        use_llm=False,
    )
    structured_analysis_markdown = render_requirement_analysis_markdown(
        structured_analysis_payload,
        title=requirement_title,
    )
    modules = _extract_outline_modules(outline_output)
    reviewed_points = _collect_reviewed_points(requirement)
    review_notes = (requirement.review_notes or "").strip()
    core_regression_points = _normalized_string_list(requirement.core_regression_points)

    sections = [
        f"# 需求标题\n{requirement_title}",
        "## 原始需求",
        _truncate_text(requirement.content, 6000) or "（无）",
    ]

    if outline_output.strip():
        sections.extend(
            [
                "## 测试大纲",
                _truncate_text(outline_output, 5000),
            ]
        )

    if modules:
        sections.extend(
            [
                "## 业务模块",
                "\n".join(f"- {module}" for module in modules[:20]),
            ]
        )

    if stage_type in {"plan", "cases"} and reviewed_points:
        sections.extend(
            [
                "## 人工确认测试点",
                _build_review_points_markdown(reviewed_points),
            ]
        )

    if stage_type in {"plan", "cases"} and core_regression_points:
        sections.extend(
            [
                "## 核心回归点",
                "\n".join(f"- {item}" for item in core_regression_points[:20]),
            ]
        )

    if stage_type == "analysis":
        sections.extend(
            [
                "## 分析产出要求",
                "\n".join(
                    [
                        "- 输出完整测试需求分析，不是轻量摘要。",
                        "- 必须包含：术语与缩写、测试范围、按维度穷尽的测试点、真实用户场景补充、需求疑义与遗漏、需求追溯、自检。",
                        "- 测试关注点和需求来源优先引用页面、入口、按钮、状态、规则、配置项和业务场景等真实业务锚点。",
                    ]
                ),
                "## 结构化分析参考",
                _truncate_text(structured_analysis_markdown, 7000),
                "## 当前阶段补充输入",
                _truncate_text(input_content, 5000) or "（无额外补充）",
            ]
        )
    elif stage_type == "plan":
        sections.extend(
            [
                "## 需求分析结果",
                _truncate_text(analysis_output or input_content, 5500) or "（无）",
            ]
        )
    elif stage_type == "cases":
        sections.extend(
            [
                "## 测试计划结果",
                _truncate_text(plan_output or input_content, 5000) or "（无）",
            ]
        )

    if review_notes:
        sections.extend(
            [
                "## 人工补充说明",
                _truncate_text(review_notes, 2000),
            ]
        )

    return "\n\n".join(section for section in sections if section).strip()


def _build_analysis_source_content(
    workflow: TestWorkflow,
    stages: dict[str, WorkflowStage],
    input_content: str,
) -> str:
    requirement = workflow.requirement
    if requirement is None:
        return input_content.strip()

    outline_output = (stages.get("outline").output_content if stages.get("outline") else "") or ""
    analysis_sources = [requirement.content]
    if outline_output.strip():
        analysis_sources.extend(
            [
                "## 测试大纲",
                outline_output.strip(),
            ]
        )
    requirement_content = requirement.content.strip()
    current_input = input_content.strip()
    if current_input and current_input != requirement_content and current_input != outline_output.strip():
        analysis_sources.extend(
            [
                "## 当前阶段补充输入",
                current_input,
            ]
        )
    return "\n\n".join(part for part in analysis_sources if part)


def _sync_requirement_analysis_payload(
    db: Session,
    workflow: TestWorkflow,
    *,
    analysis_content: str,
    analysis_payload: dict[str, object] | None = None,
) -> None:
    if not workflow.requirement_id or not analysis_content.strip():
        return

    requirement = db.query(Requirement).filter(Requirement.id == workflow.requirement_id).first()
    if requirement is None:
        return

    payload = analysis_payload or build_requirement_analysis(
        analysis_content,
        title=requirement.title,
        use_llm=False,
    )
    requirement.analysis_payload = payload
    requirement.parsed_points = [
        point["title"]
        for point in payload.get("selected_points", [])
        if isinstance(point, dict) and point.get("title")
    ]
    requirement.last_analyzed_at = datetime.utcnow()


def _sync_workflow_cases_to_testcases(
    db: Session,
    workflow: TestWorkflow,
    *,
    cases_content: str,
) -> dict[str, int]:
    if not workflow.requirement_id:
        return {"created": 0, "deleted": 0, "skipped": 0, "protected": 0, "total": 0, "locked": 0, "edited": 0, "replaceable": 0}

    requirement = db.query(Requirement).filter(Requirement.id == workflow.requirement_id).first()
    if requirement is None:
        return {"created": 0, "deleted": 0, "skipped": 0, "protected": 0, "total": 0, "locked": 0, "edited": 0, "replaceable": 0}

    parsed_cases = parse_xmind_markdown(cases_content)
    looks_like_placeholder = "测试用例占位" in cases_content and "依据输入摘要" in cases_content
    parsed_cases_have_details = any(
        (case.get("steps") or "").strip() or (case.get("expected") or "").strip()
        for case in parsed_cases
    )
    if looks_like_placeholder or not parsed_cases or not parsed_cases_have_details:
        parsed_cases = generate_structured_cases(
            requirement.title,
            requirement.content,
            analysis_payload=requirement.analysis_payload,
        )
    if not parsed_cases:
        raise HTTPException(status_code=400, detail="测试用例阶段产出未能解析为可落库的用例，请先调整内容格式。")

    impact = _sync_requirement_cases(
        db,
        requirement,
        parsed_cases,
        source="workflow_generated",
        mode="overwrite",
        replaceable_sources={"workflow_generated"},
    )
    requirement.analysis_status = "ready_for_execution"
    _append_requirement_tool_result(
        requirement,
        "工作流生成用例",
        f"已从工作流同步 {impact['created']} 条测试用例，保留 {impact['protected']} 条受保护用例。",
    )
    return impact

def _mark_workflow_started(workflow: TestWorkflow) -> None:
    now = datetime.utcnow()
    if workflow.started_at is None:
        workflow.started_at = now
    workflow.updated_at = now
    if workflow.status == "draft":
        workflow.status = "in_progress"
    if workflow.current_stage not in STAGE_TYPES:
        workflow.current_stage = STAGE_TYPES[0]


def _advance_workflow(
    workflow: TestWorkflow,
    stages: dict[str, WorkflowStage],
    stage_type: str,
    output_content: str,
) -> None:
    now = datetime.utcnow()
    idx = STAGE_ORDER[stage_type]
    next_types = [t for t in STAGE_TYPES if STAGE_ORDER[t] == idx + 1]

    if next_types:
        next_stage = stages.get(next_types[0])
        if next_stage and not next_stage.input_content:
            next_stage.input_content = output_content
        workflow.current_stage = next_types[0]
        workflow.status = "in_progress"
        workflow.completed_at = None
    else:
        workflow.current_stage = stage_type
        workflow.status = "completed"
        workflow.completed_at = now

    workflow.updated_at = now


STAGE_PREREQUISITES: dict[str, tuple[str, ...]] = {
    "plan": ("analysis",),
    "cases": ("plan",),
    "prepare": ("cases",),
    "execute": ("prepare",),
    "defects": ("execute",),
    "report": ("execute",),
}


def _validate_stage_prerequisites(
    workflow: TestWorkflow,
    stages: dict[str, WorkflowStage],
    stage_type: str,
) -> None:
    required_stage_types = STAGE_PREREQUISITES.get(stage_type, ())
    missing_labels = [
        STAGE_LABELS.get(required_stage_type, required_stage_type)
        for required_stage_type in required_stage_types
        if not ((stages.get(required_stage_type).output_content if stages.get(required_stage_type) else "") or "").strip()
    ]
    if missing_labels:
        raise HTTPException(
            status_code=400,
            detail=f"当前阶段前还需要先完成：{'、'.join(missing_labels)}",
        )

    if stage_type in ("plan", "cases"):
        review_status = workflow.requirement.analysis_status if workflow.requirement else None
        if review_status not in ("reviewed", "ready_for_execution"):
            raise HTTPException(
                status_code=400,
                detail="生成测试计划或测试用例前请先完成人工确认。",
            )


@router.post("/{workflow_id}/stage/{stage_type}/generate")
def generate_stage(
    workflow_id: int,
    stage_type: str,
    use_llm: str = Form("false"),
    db: Session = Depends(get_db),
):
    generated_count = None
    wf = _get_workflow(db, workflow_id)
    _ensure_stages(db, wf)
    stages = _stages_dict(wf)
    if stage_type not in stages:
        raise HTTPException(status_code=400, detail=f"无效阶段: {stage_type}")
    _validate_stage_prerequisites(wf, stages, stage_type)
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
    _mark_workflow_started(wf)
    current.status = "running"
    db.commit()
    want_llm = _form_bool_use_llm(use_llm)
    try:
        if want_llm:
            if not can_use_llm():
                raise HTTPException(
                    status_code=400,
                    detail="已选择使用大模型，但未配置 LLM_API_KEY，请在 .env 中配置或取消勾选「工作流使用大模型」。",
                )
            if stage_type == "analysis" and wf.requirement is not None:
                analysis_input = _build_analysis_source_content(wf, stages, input_content)
                analysis_payload = build_requirement_analysis(
                    analysis_input,
                    title=wf.requirement.title,
                    use_llm=True,
                )
                result = {
                    "output": render_requirement_analysis_markdown(
                        analysis_payload,
                        title=wf.requirement.title,
                    ),
                    "prompt_used": "llm_structured_analysis_from_requirement",
                    "analysis_payload": analysis_payload,
                }
            else:
                stage_context = _build_stage_generation_context(wf, stages, stage_type, input_content)
                result = generate_stage_content(stage_type, stage_context)
        else:
            if stage_type == "analysis" and wf.requirement is not None:
                analysis_payload = build_requirement_analysis(
                    _build_analysis_source_content(wf, stages, input_content),
                    title=wf.requirement.title,
                    use_llm=False,
                )
                result = {
                    "output": render_requirement_analysis_markdown(
                        analysis_payload,
                        title=wf.requirement.title,
                    ),
                    "prompt_used": "rule_generated_analysis_from_requirement",
                    "analysis_payload": analysis_payload,
                }
            elif stage_type == "cases" and wf.requirement is not None:
                result = {
                    "output": generate_xmind_markdown(
                        wf.requirement.title,
                        wf.requirement.content,
                        analysis_payload=wf.requirement.analysis_payload,
                    ),
                    "prompt_used": "rule_generated_cases_from_requirement_analysis",
                }
            else:
                result = generate_placeholder_content(stage_type, input_content)
        evidence_text = _identifier_evidence_text(wf, stages)
        original_output = result["output"]
        result["output"] = _sanitize_generated_output_identifiers(result["output"], evidence_text)
        if stage_type == "analysis" and original_output != result["output"]:
            result.pop("analysis_payload", None)
        if stage_type == "analysis":
            result["output"] = _normalize_analysis_output_markdown(result["output"])
        current.output_content = result["output"]
        current.ai_prompt_used = result["prompt_used"]
        current.status = "completed"
        current.completed_at = datetime.utcnow()
        if stage_type == "analysis":
            _sync_requirement_analysis_payload(
                db,
                wf,
                analysis_content=result["output"],
                analysis_payload=result.get("analysis_payload"),
            )
        elif stage_type == "cases":
            impact = _sync_workflow_cases_to_testcases(
                db,
                wf,
                cases_content=result["output"],
            )
            generated_count = impact["created"]
        _advance_workflow(wf, stages, stage_type, result["output"])
        db.commit()
    except HTTPException:
        current.status = "failed"
        wf.updated_at = datetime.utcnow()
        db.commit()
        raise
    except Exception as exc:
        current.status = "failed"
        wf.status = "failed"
        wf.updated_at = datetime.utcnow()
        db.commit()
        raise HTTPException(status_code=500, detail=f"AI 生成失败: {exc}")
    if wf.requirement_id:
        redirect_url = f"/requirements/{wf.requirement_id}#wf-stage-{stage_type}"
        if generated_count is not None:
            redirect_url = f"/requirements/{wf.requirement_id}?generated={generated_count}#generated-testcases"
        return RedirectResponse(url=redirect_url, status_code=303)
    return RedirectResponse(url=f"/workflow/{workflow_id}?stage={stage_type}", status_code=303)


@router.post("/{workflow_id}/stage/{stage_type}/save")
def save_stage(
    workflow_id: int,
    stage_type: str,
    input_content: str = Form(""),
    output_content: str = Form(""),
    db: Session = Depends(get_db),
):
    generated_count = None
    wf = _get_workflow(db, workflow_id)
    _ensure_stages(db, wf)
    stages = _stages_dict(wf)
    if stage_type not in stages:
        raise HTTPException(status_code=400, detail=f"无效阶段: {stage_type}")
    current = stages[stage_type]
    now = datetime.utcnow()
    if input_content.strip():
        current.input_content = input_content.strip()
        wf.updated_at = now
    if output_content.strip():
        _validate_stage_prerequisites(wf, stages, stage_type)
        _mark_workflow_started(wf)
        normalized_output = output_content.strip()
        if stage_type == "analysis":
            normalized_output = _normalize_analysis_output_markdown(normalized_output)
        current.output_content = normalized_output
        current.status = "completed"
        current.completed_at = now
        if stage_type == "analysis":
            _sync_requirement_analysis_payload(
                db,
                wf,
                analysis_content=normalized_output,
            )
        elif stage_type == "cases":
            impact = _sync_workflow_cases_to_testcases(
                db,
                wf,
                cases_content=normalized_output,
            )
            generated_count = impact["created"]
        _advance_workflow(wf, stages, stage_type, normalized_output)
    db.commit()
    if wf.requirement_id:
        redirect_url = f"/requirements/{wf.requirement_id}#wf-stage-{stage_type}"
        if generated_count is not None:
            redirect_url = f"/requirements/{wf.requirement_id}?generated={generated_count}#generated-testcases"
        return RedirectResponse(url=redirect_url, status_code=303)
    return RedirectResponse(url=f"/workflow/{workflow_id}?stage={stage_type}", status_code=303)

@router.post("/{workflow_id}/stage/{stage_type}/confirm")
def confirm_stage(
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
    if not (current.output_content or "").strip():
        raise HTTPException(status_code=400, detail="当前阶段没有可确认的输出内容")
    now = datetime.utcnow()
    if wf.started_at is None:
        wf.started_at = now
    wf.confirmed_stage = stage_type
    wf.updated_at = now
    idx = STAGE_ORDER[stage_type]
    next_types = [t for t in STAGE_TYPES if STAGE_ORDER[t] == idx + 1]
    if next_types:
        wf.current_stage = next_types[0]
        wf.status = "in_progress"
        wf.completed_at = None
    else:
        wf.current_stage = stage_type
        wf.status = "completed"
        wf.completed_at = now
    db.commit()
    if wf.requirement_id:
        return RedirectResponse(url=f"/requirements/{wf.requirement_id}#wf-stage-{stage_type}", status_code=303)
    return RedirectResponse(url=f"/workflow/{workflow_id}?stage={stage_type}", status_code=303)


@router.post("/{workflow_id}/meta")
def update_workflow_meta(
    workflow_id: int,
    output_base_path: str = Form(""),
    workflow_version: str = Form(""),
    source_type: str = Form(""),
    source_meta: str = Form(""),
    db: Session = Depends(get_db),
):
    wf = _get_workflow(db, workflow_id)
    wf.output_base_path = output_base_path.strip() or None
    wf.workflow_version = workflow_version.strip() or None
    wf.source_type = source_type.strip() or None
    raw_meta = source_meta.strip()
    if raw_meta:
        try:
            wf.source_meta = json.loads(raw_meta)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"source_meta 必须是合法 JSON: {exc}") from exc
    else:
        wf.source_meta = None
    wf.updated_at = datetime.utcnow()
    db.commit()
    if wf.requirement_id:
        return RedirectResponse(url=f"/requirements/{wf.requirement_id}#ai-workflow", status_code=303)
    return RedirectResponse(url=f"/workflow/{workflow_id}", status_code=303)

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

    safe_name = "".join(char if char.isascii() and (char.isalnum() or char in "-_.") else "_" for char in (wf.name or "workflow"))
    safe_name = safe_name.strip("._") or "workflow"
    download_name = f"workflow-{safe_name}-{wf.id}.zip"
    utf8_name = quote(f"workflow-{wf.name or 'workflow'}-{wf.id}.zip")
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=\"{download_name}\"; filename*=UTF-8''{utf8_name}"
        },
    )


@router.post("/{workflow_id}/delete")
def delete_workflow(workflow_id: int, db: Session = Depends(get_db)):
    wf = _get_workflow(db, workflow_id)
    db.delete(wf)
    db.commit()
    return RedirectResponse(url=f"/projects/{wf.project_id}", status_code=303)
