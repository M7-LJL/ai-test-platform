from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload, subqueryload

from app.database import get_db
from app.models import Project, Requirement, RequirementReviewPoint, TestWorkflow, WorkflowStage
from app.services.ai_service import build_requirement_analysis, can_use_llm
from app.services.xmind_markdown_service import generate_structured_cases, generate_xmind_markdown
from app.services.workflow_ai_service import STAGE_TYPES, STAGE_ORDER, STAGE_LABELS
from app.services.ai_service import can_use_llm as _can_use_llm

router = APIRouter(tags=["requirements-html"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

CATEGORY_LABELS = {
    "functional": "功能点",
    "boundary": "边界点",
    "exception": "异常点",
}
DIMENSION_LABELS = {
    "角色/用户": "角色/用户",
    "页面/入口": "页面/入口",
    "操作/动作": "操作/动作",
    "接口/数据": "接口/数据",
    "状态/流程": "状态/流程",
    "规则/约束": "规则/约束",
    "非功能": "非功能",
    "关联/依赖": "关联/依赖",
    "隐性需求/界面状态": "隐性需求/界面状态",
}
TYPE_LABELS = {
    "normal": "正常",
    "boundary": "边界",
    "exception": "异常",
    "user_scene": "真实用户场景",
}
COVERAGE_STATUS_LABELS = {
    "covered": "已覆盖",
    "partial": "部分覆盖",
    "missing": "未覆盖/未说明",
}
GENERIC_PHRASES = ("验证功能", "校验页面反馈", "结果符合需求预期", "观察页面反馈")
REPEAT_SCENE_KEYWORDS = ("首次", "第一次", "再次", "第二次", "重复", "连续", "多次", "重试", "重复提交", "再进入", "二次")
STATE_SCENE_KEYWORDS = ("草稿", "已提交", "审核中", "已通过", "已驳回", "已关闭", "已完成", "状态")


def _decode_markdown_bytes(raw_bytes: bytes) -> str:
    if not raw_bytes:
        return ""

    for encoding in ("utf-8", "utf-8-sig", "gbk", "gb18030", "utf-16", "utf-16-le", "utf-16-be"):
        try:
            text = raw_bytes.decode(encoding)
            if text.strip():
                return text
        except UnicodeDecodeError:
            continue

    return raw_bytes.decode("utf-8", errors="ignore").strip()


def _extract_title_from_markdown(filename: str, content: str) -> str:
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            title = line.lstrip("#").strip()
            if title:
                return title
        cleaned = line.lstrip("-*0123456789.、 ").strip()
        if cleaned:
            return cleaned[:120]

    base_name = Path(filename or "未命名需求").stem.strip()
    return base_name or "未命名需求"


def _new_requirement_context(
    request: Request,
    projects: list[Project],
    *,
    selected_project_id: int | None = None,
    error_message: str = "",
    form_data: dict[str, str] | None = None,
):
    return {
        "request": request,
        "projects": projects,
        "selected_project_id": selected_project_id,
        "error_message": error_message,
        "form_data": form_data or {},
    }


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\u3000", " ").split()).strip()


def _normalized_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        cleaned = _clean_text(item)
        if cleaned and cleaned not in items:
            items.append(cleaned)
    return items


def _analysis_payload_dict(requirement: Requirement) -> dict[str, Any]:
    return requirement.analysis_payload if isinstance(requirement.analysis_payload, dict) else {}


def _normalized_selected_points(payload: dict[str, Any]) -> list[dict[str, str]]:
    points = payload.get("selected_points", [])
    if not isinstance(points, list):
        return []

    normalized_points: list[dict[str, str]] = []
    for point in points:
        if not isinstance(point, dict):
            continue
        title = _clean_text(point.get("title"))
        if not title:
            continue
        category = _clean_text(point.get("category")).lower() or "functional"
        if category not in CATEGORY_LABELS:
            category = "functional"
        normalized_points.append(
            {
                "title": title,
                "category": category,
                "module": _clean_text(point.get("module")) or "默认模块",
                "context": _clean_text(point.get("context")) or "需求原文",
                "requirement_source": _clean_text(point.get("requirement_source")) or title,
            }
        )
    return normalized_points


def _build_analysis_sections(requirement: Requirement) -> list[dict[str, Any]]:
    payload = _analysis_payload_dict(requirement)
    return [
        {"title": "需求漏洞", "items": _normalized_string_list(payload.get("gaps"))},
        {"title": "测试标准", "items": _normalized_string_list(payload.get("test_standards"))},
    ]


def _build_summary_sections(requirement: Requirement) -> list[dict[str, Any]]:
    payload = _analysis_payload_dict(requirement)
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    return [
        {"title": "系统流程", "items": _normalized_string_list(summary.get("system_flow"))},
        {"title": "核心规则", "items": _normalized_string_list(summary.get("core_rules"))},
        {"title": "主要风险", "items": _normalized_string_list(summary.get("main_risks"))},
        {"title": "测试重点", "items": _normalized_string_list(summary.get("test_focus"))},
    ]


def _build_scenario_sections(requirement: Requirement) -> list[dict[str, Any]]:
    grouped_items: dict[str, list[dict[str, str]]] = {
        "functional": [],
        "boundary": [],
        "exception": [],
    }
    for point in _normalized_selected_points(_analysis_payload_dict(requirement)):
        grouped_items[point["category"]].append(point)

    return [
        {"title": "功能点", "items": grouped_items["functional"]},
        {"title": "边界点", "items": grouped_items["boundary"]},
        {"title": "异常点", "items": grouped_items["exception"]},
    ]


def _normalized_terms_rows(payload: dict[str, Any]) -> list[dict[str, str]]:
    rows = payload.get("terms", [])
    if not isinstance(rows, list):
        return []
    normalized_rows: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        term = _clean_text(row.get("term"))
        meaning = _clean_text(row.get("meaning"))
        if not term or not meaning:
            continue
        source_refs = row.get("source_refs") if isinstance(row.get("source_refs"), list) else []
        normalized_rows.append(
            {
                "term": term,
                "meaning": meaning,
                "source_refs": "；".join(_normalized_string_list(source_refs)) or "需求原文",
            }
        )
    return normalized_rows


def _normalized_scope_items_rows(payload: dict[str, Any]) -> list[dict[str, str]]:
    rows = payload.get("scope_items", [])
    if not isinstance(rows, list):
        return []
    normalized_rows: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item_id = _clean_text(row.get("id"))
        name = _clean_text(row.get("name"))
        if not name:
            continue
        source_refs = row.get("source_refs") if isinstance(row.get("source_refs"), list) else []
        normalized_rows.append(
            {
                "id": item_id or "",
                "name": name,
                "dimension": DIMENSION_LABELS.get(_clean_text(row.get("dimension")), _clean_text(row.get("dimension")) or "操作/动作"),
                "module": _clean_text(row.get("module")) or "默认模块",
                "role": _clean_text(row.get("role")) or "未说明",
                "page_or_entry": _clean_text(row.get("page_or_entry")) or "需求原文",
                "object": _clean_text(row.get("object")) or name,
                "rule_summary": _clean_text(row.get("rule_summary")) or name,
                "priority": _clean_text(row.get("priority")) or "P2",
                "testable": "是" if bool(row.get("testable", True)) else "否",
                "source_refs": "；".join(_normalized_string_list(source_refs)) or "需求原文",
                "notes": _clean_text(row.get("notes")),
            }
        )
    return normalized_rows


def _build_scope_sections(requirement: Requirement) -> list[dict[str, Any]]:
    payload = _analysis_payload_dict(requirement)
    rows = _normalized_scope_items_rows(payload)
    grouped: dict[str, list[dict[str, str]]] = {label: [] for label in DIMENSION_LABELS.values()}
    for row in rows:
        grouped.setdefault(row["dimension"], [])
        grouped[row["dimension"]].append(row)
    return [
        {"title": dimension, "items": grouped.get(dimension, [])}
        for dimension in DIMENSION_LABELS.values()
    ]


def _normalized_test_point_rows(payload: dict[str, Any]) -> list[dict[str, str]]:
    rows = payload.get("test_points", [])
    if not isinstance(rows, list):
        return []
    normalized_rows: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = _clean_text(row.get("title"))
        if not title:
            continue
        source_refs = row.get("source_refs") if isinstance(row.get("source_refs"), list) else []
        preconditions = row.get("preconditions") if isinstance(row.get("preconditions"), list) else []
        verification_focus = row.get("verification_focus") if isinstance(row.get("verification_focus"), list) else []
        text_blob = " ".join(
            [
                _clean_text(row.get("title")),
                _clean_text(row.get("action")),
                _clean_text(row.get("user_scenario_tag")),
                "；".join(_normalized_string_list(preconditions)),
            ]
        )
        is_repeat_scene = any(keyword in text_blob for keyword in REPEAT_SCENE_KEYWORDS)
        is_state_scene = any(keyword in text_blob for keyword in STATE_SCENE_KEYWORDS)
        normalized_rows.append(
            {
                "id": _clean_text(row.get("id")) or "",
                "scope_item_id": _clean_text(row.get("scope_item_id")) or "",
                "title": title,
                "type": TYPE_LABELS.get(_clean_text(row.get("type")).lower(), _clean_text(row.get("type")) or "正常"),
                "category": CATEGORY_LABELS.get(_clean_text(row.get("category")).lower(), "功能点"),
                "module": _clean_text(row.get("module")) or "默认模块",
                "role": _clean_text(row.get("role")) or "未说明",
                "page_or_entry": _clean_text(row.get("page_or_entry")) or "需求原文",
                "preconditions": "；".join(_normalized_string_list(preconditions)),
                "action": _clean_text(row.get("action")) or title,
                "verification_focus": "；".join(_normalized_string_list(verification_focus)),
                "user_scenario": "是" if bool(row.get("user_scenario")) else "否",
                "user_scenario_tag": _clean_text(row.get("user_scenario_tag")) or "-",
                "priority": _clean_text(row.get("priority")) or "P2",
                "source_refs": "；".join(_normalized_string_list(source_refs)) or "需求原文",
                "scene_bucket": "重复/二次操作场景" if is_repeat_scene else ("状态变化场景" if is_state_scene else "常规场景"),
                "is_repeat_scene": "是" if is_repeat_scene else "否",
            }
        )
    return normalized_rows


def _normalized_gap_rows(payload: dict[str, Any]) -> list[dict[str, str]]:
    rows = payload.get("gaps", [])
    if not isinstance(rows, list):
        return []
    normalized_rows: list[dict[str, str]] = []
    for item in rows:
        if isinstance(item, str):
            text = _clean_text(item)
            if text:
                normalized_rows.append({"dimension": "待确认", "question": text, "suggestion": "", "source_refs": "需求原文"})
        elif isinstance(item, dict):
            question = _clean_text(item.get("question"))
            if question:
                source_refs = item.get("source_refs") if isinstance(item.get("source_refs"), list) else []
                normalized_rows.append(
                    {
                        "dimension": _clean_text(item.get("dimension")) or "待确认",
                        "question": question,
                        "suggestion": _clean_text(item.get("suggestion")),
                        "source_refs": "；".join(_normalized_string_list(source_refs)) or "需求原文",
                    }
                )
    return normalized_rows


def _build_special_issue_sections(payload: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    special_sections = {"known_issues": [], "prelaunch_checks": [], "general_gaps": []}
    for row in _normalized_gap_rows(payload):
        question = row["question"]
        if question.startswith("已知问题："):
            normalized_row = dict(row)
            normalized_row["question"] = question.replace("已知问题：", "", 1).strip()
            special_sections["known_issues"].append(normalized_row)
        elif question.startswith("上线检查项："):
            normalized_row = dict(row)
            normalized_row["question"] = question.replace("上线检查项：", "", 1).strip()
            special_sections["prelaunch_checks"].append(normalized_row)
        else:
            special_sections["general_gaps"].append(row)
    return special_sections


def _normalized_generic_test_point_rows(payload: dict[str, Any]) -> list[dict[str, str]]:
    rows = _normalized_test_point_rows(payload)
    generic_rows: list[dict[str, str]] = []
    for row in rows:
        matched_phrase = next(
            (phrase for phrase in GENERIC_PHRASES if phrase in row["title"] or phrase in row["action"]),
            "",
        )
        if not matched_phrase:
            continue
        generic_rows.append(
            {
                "title": row["title"],
                "module": row["module"],
                "type": row["type"],
                "action": row["action"],
                "verification_focus": row["verification_focus"] or "-",
                "source_refs": row["source_refs"],
                "reason": f"命中空洞短语：{matched_phrase}",
            }
        )
    return generic_rows


def _normalized_traceability_rows(payload: dict[str, Any]) -> list[dict[str, str]]:
    rows = payload.get("traceability", [])
    if not isinstance(rows, list):
        return []
    normalized_rows: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        scope_item_id = _clean_text(row.get("scope_item_id"))
        if not scope_item_id:
            continue
        point_ids = row.get("test_point_ids") if isinstance(row.get("test_point_ids"), list) else []
        source_refs = row.get("source_refs") if isinstance(row.get("source_refs"), list) else []
        normalized_rows.append(
            {
                "scope_item_id": scope_item_id,
                "test_point_ids": "、".join(_normalized_string_list(point_ids)) or "-",
                "source_refs": "；".join(_normalized_string_list(source_refs)) or "需求原文",
            }
        )
    return normalized_rows


def _build_coverage_sections(requirement: Requirement) -> list[dict[str, str]]:
    payload = _analysis_payload_dict(requirement)
    coverage = payload.get("coverage_check") if isinstance(payload.get("coverage_check"), dict) else {}
    mapping = {
        "roles": "角色/用户",
        "pages_entries": "页面/入口",
        "actions": "操作/动作",
        "data_fields": "接口/数据",
        "states_flows": "状态/流程",
        "rules_constraints": "规则/约束",
        "non_functional": "非功能",
        "dependencies": "关联/依赖",
        "implicit_states": "隐性需求/界面状态",
    }
    return [
        {
            "label": label,
            "status": COVERAGE_STATUS_LABELS.get(_clean_text(coverage.get(key)).lower(), "未覆盖/未说明"),
            "status_code": _clean_text(coverage.get(key)).lower() or "missing",
        }
        for key, label in mapping.items()
    ]


def _build_consistency_sections(requirement: Requirement) -> list[dict[str, Any]]:
    payload = _analysis_payload_dict(requirement)
    consistency = payload.get("consistency_check") if isinstance(payload.get("consistency_check"), dict) else {}
    return [
        {
            "title": "原文锚定",
            "items": ["已建立原文对应关系" if _clean_text(consistency.get("anchoring_status")).lower() == "anchored" else "部分内容仍需补充原文锚定"],
        },
        {"title": "术语歧义", "items": _normalized_string_list(consistency.get("ambiguous_terms"))},
        {"title": "模糊表述", "items": _normalized_string_list(consistency.get("fuzzy_phrases"))},
        {"title": "我的理解是", "items": _normalized_string_list(consistency.get("my_understanding"))},
    ]


def _build_quality_summary(requirement: Requirement) -> dict[str, Any]:
    payload = _analysis_payload_dict(requirement)
    quality = payload.get("quality_report") if isinstance(payload.get("quality_report"), dict) else {}
    scope_rows = _normalized_scope_items_rows(payload)
    test_point_rows = _normalized_test_point_rows(payload)
    special_sections = _build_special_issue_sections(payload)
    gap_rows = special_sections["general_gaps"]
    return {
        "score": int(quality.get("score", 0) or 0),
        "needs_review": bool(quality.get("needs_review")),
        "missing_source_count": int(quality.get("missing_source_count", 0) or 0),
        "generic_statement_count": int(quality.get("generic_statement_count", 0) or 0),
        "scope_count": len(scope_rows),
        "test_point_count": len(test_point_rows),
        "gap_count": len(gap_rows),
        "term_count": len(_normalized_terms_rows(payload)),
        "known_issue_count": len(special_sections["known_issues"]),
        "prelaunch_check_count": len(special_sections["prelaunch_checks"]),
    }


def _build_review_point_rows(requirement: Requirement) -> list[dict[str, Any]]:
    payload = _analysis_payload_dict(requirement)
    payload_test_points = _normalized_test_point_rows(payload)
    payload_test_points_map = {row["title"]: row for row in payload_test_points}
    review_payload = payload.get("review") if isinstance(payload.get("review"), dict) else {}
    reviewed_test_points = review_payload.get("reviewed_test_points", [])
    if isinstance(reviewed_test_points, list) and reviewed_test_points:
        rows: list[dict[str, Any]] = []
        for row in reviewed_test_points:
            if not isinstance(row, dict):
                continue
            rows.append(
                {
                    "id": _clean_text(row.get("id")),
                    "selected": bool(row.get("selected", True)),
                    "is_core": bool(row.get("is_core")),
                    "category": _clean_text(row.get("category")).lower() or "functional",
                    "module": _clean_text(row.get("module")) or "",
                    "title": _clean_text(row.get("title")),
                    "context": _clean_text(row.get("context")) or "需求原文",
                    "requirement_source": _clean_text(row.get("requirement_source")) or _clean_text(row.get("title")),
                    "source": _clean_text(row.get("source")) or "ai",
                    "priority": _clean_text(row.get("priority")) or "P2",
                    "source_refs": _clean_text(row.get("source_refs")) or "需求原文",
                    "user_scenario": bool(row.get("user_scenario")),
                    "user_scenario_tag": _clean_text(row.get("user_scenario_tag")) or "",
                    "page_or_entry": _clean_text(row.get("page_or_entry")) or "需求原文",
                    "preconditions": _clean_text(row.get("preconditions")) or "",
                    "action": _clean_text(row.get("action")) or _clean_text(row.get("title")),
                    "verification_focus": _clean_text(row.get("verification_focus")) or "",
                }
            )
        if rows:
            return rows

    if requirement.review_points:
        rows = []
        for point in requirement.review_points:
            matched = payload_test_points_map.get(point.title, {})
            rows.append(
                {
                    "id": point.id,
                    "selected": point.is_selected,
                    "is_core": point.is_core,
                    "category": point.category or "functional",
                    "module": point.module or "",
                    "title": point.title,
                    "context": point.context or matched.get("page_or_entry") or "需求原文",
                    "requirement_source": point.requirement_source or point.title,
                    "source": point.source or "ai",
                    "priority": point.priority or matched.get("priority") or "P2",
                    "source_refs": matched.get("source_refs") or point.requirement_source or point.title,
                    "user_scenario": matched.get("user_scenario") == "是",
                    "user_scenario_tag": matched.get("user_scenario_tag") if matched.get("user_scenario") == "是" else "",
                    "page_or_entry": matched.get("page_or_entry") or point.context or "需求原文",
                    "preconditions": matched.get("preconditions") or "",
                    "action": matched.get("action") or point.title,
                    "verification_focus": matched.get("verification_focus") or "",
                }
            )
        return rows

    return [
        {
            "id": "",
            "selected": True,
            "is_core": False,
            "category": point["category"],
            "module": point["module"],
            "title": point["title"],
            "context": point["page_or_entry"],
            "requirement_source": point["source_refs"],
            "source": "ai",
            "priority": point["priority"],
            "source_refs": point["source_refs"],
            "user_scenario": point["user_scenario"] == "是",
            "user_scenario_tag": point["user_scenario_tag"] if point["user_scenario"] == "是" else "",
            "page_or_entry": point["page_or_entry"],
            "preconditions": point["preconditions"],
            "action": point["action"],
            "verification_focus": point["verification_focus"],
        }
        for point in payload_test_points
    ]


def _normalized_custom_points(requirement: Requirement) -> list[str]:
    payload = _analysis_payload_dict(requirement)
    review = payload.get("review") if isinstance(payload.get("review"), dict) else {}
    return _normalized_string_list(review.get("custom_points"))


def _normalized_core_regression_points(requirement: Requirement) -> list[str]:
    stored = _normalized_string_list(requirement.core_regression_points)
    if stored:
        return stored
    payload = _analysis_payload_dict(requirement)
    review = payload.get("review") if isinstance(payload.get("review"), dict) else {}
    return _normalized_string_list(review.get("core_regression_points"))


def _append_tool_result(requirement: Requirement, tool_name: str, summary: str) -> None:
    history = list(requirement.tool_result or [])
    history.append(
        {
            "tool": tool_name,
            "summary": summary,
            "status": "completed",
            "created_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        }
    )
    requirement.tool_result = history[-8:]


def _parse_review_points_payload(raw_payload: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(raw_payload or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _parse_deleted_ids(raw_deleted_ids: str) -> set[int]:
    deleted_ids: set[int] = set()
    for raw_id in (raw_deleted_ids or "").split(","):
        candidate = raw_id.strip()
        if candidate.isdigit():
            deleted_ids.add(int(candidate))
    return deleted_ids


def _string_to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = _clean_text(value).lower()
    return text in {"1", "true", "yes", "on", "是"}


def _build_tool_plan(requirement: Requirement) -> list[dict[str, str]]:
    payload = _analysis_payload_dict(requirement)
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    risks = _normalized_string_list(summary.get("main_risks"))
    core_points = _normalized_core_regression_points(requirement)
    selected_points = _normalized_selected_points(payload)

    plan: list[dict[str, str]] = []
    if core_points:
        plan.append(
            {
                "tool": "UI 自动化",
                "scope": "核心回归链路",
                "target": "覆盖已选核心回归点",
                "reason": f"优先沉淀 {min(len(core_points), 5)} 条高价值回归点，降低重复回归成本。",
            }
        )

    if any(point["category"] == "functional" for point in selected_points):
        plan.append(
            {
                "tool": "接口测试",
                "scope": "主流程与关键数据校验",
                "target": "验证主流程状态流转和结果数据",
                "reason": "功能点覆盖较多，接口层更适合快速校验结果一致性和批量回归。",
            }
        )

    if any(point["category"] == "boundary" for point in selected_points):
        plan.append(
            {
                "tool": "参数化边界测试",
                "scope": "阈值、空值和上下限场景",
                "target": "覆盖边界条件前、中、后样本",
                "reason": "当前需求含边界点，建议通过参数化样本提高边界验证完整度。",
            }
        )

    if any(point["category"] == "exception" for point in selected_points) or risks:
        plan.append(
            {
                "tool": "异常注入与日志核对",
                "scope": "失败、超时、拦截和兜底场景",
                "target": "验证异常反馈、日志留痕和兜底逻辑",
                "reason": risks[0] if risks else "当前需求存在异常处理场景，需要单独验证失败链路是否闭环。",
            }
        )

    if not plan:
        plan.append(
            {
                "tool": "手工探索测试",
                "scope": "需求主流程",
                "target": "快速确认页面流程和结果反馈",
                "reason": "当前结构化测试点较少，先用手工探索补足业务理解。",
            }
        )

    return plan[:4]


@router.get("/requirements/new", name="requirement_new")
def new_requirement_page(
    request: Request,
    project_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    projects = db.query(Project).order_by(Project.created_at.desc()).all()
    return templates.TemplateResponse(
        request,
        "requirements/new.html",
        _new_requirement_context(
            request,
            projects,
            selected_project_id=project_id,
        ),
    )


@router.post("/requirements/", name="requirement_create")
async def create_requirement(
    request: Request,
    project_id: int = Form(...),
    markdown_file: UploadFile | None = File(default=None),
    markdown_filename_text: str = Form(default=""),
    markdown_content_text: str = Form(default=""),
    fallback_content: str = Form(default=""),
    db: Session = Depends(get_db),
):
    projects = db.query(Project).order_by(Project.created_at.desc()).all()
    project = db.query(Project).filter(Project.id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")

    uploaded_filename = ""
    uploaded_content = ""
    if markdown_file is not None and markdown_file.filename:
        uploaded_filename = markdown_file.filename.strip()
        raw_bytes = await markdown_file.read()
        uploaded_content = _decode_markdown_bytes(raw_bytes)

    persisted_filename = (markdown_filename_text or "").strip()
    persisted_content = (markdown_content_text or "").strip()
    pasted_content = (fallback_content or "").strip()

    final_filename = uploaded_filename or persisted_filename
    final_content = uploaded_content or persisted_content or pasted_content

    if not final_content:
        return templates.TemplateResponse(
            request,
            "requirements/new.html",
            _new_requirement_context(
                request,
                projects,
                selected_project_id=project_id,
                error_message="请上传 Markdown 文件，或直接粘贴需求正文。",
                form_data={
                    "project_id": str(project_id),
                    "markdown_filename_text": final_filename,
                    "markdown_content_text": persisted_content,
                    "fallback_content": pasted_content,
                },
            ),
            status_code=400,
        )

    title = _extract_title_from_markdown(final_filename, final_content)
    analysis_payload = build_requirement_analysis(final_content, title=title, use_llm=can_use_llm())
    parsed_points = [
        point["title"]
        for point in analysis_payload.get("selected_points", [])
        if isinstance(point, dict) and point.get("title")
    ]

    requirement = Requirement(
        project_id=project_id,
        title=title.strip(),
        content=final_content.strip(),
        parsed_points=parsed_points,
        analysis_payload=analysis_payload,
        analysis_status="draft",
        last_analyzed_at=datetime.utcnow(),
    )
    db.add(requirement)
    db.flush()

    wf = TestWorkflow(
        project_id=project_id,
        requirement_id=requirement.id,
        name=title.strip(),
        status="in_progress",
        current_stage="outline",
    )
    db.add(wf)
    db.flush()

    for stage_type in STAGE_TYPES:
        stage = WorkflowStage(
            workflow_id=wf.id,
            stage_type=stage_type,
            sort_order=STAGE_ORDER[stage_type],
        )
        if stage_type == "outline":
            stage.input_content = final_content.strip()
        db.add(stage)

    db.commit()
    return RedirectResponse(url=f"/requirements/{requirement.id}", status_code=303)


@router.post("/requirements/{requirement_id}/reanalyze", name="requirement_reanalyze")
def reanalyze_requirement(
    requirement_id: int,
    use_llm: bool = Form(default=False),
    db: Session = Depends(get_db),
):
    requirement = db.query(Requirement).filter(Requirement.id == requirement_id).first()
    if requirement is None:
        raise HTTPException(status_code=404, detail="Requirement not found.")

    llm_unavailable = use_llm and not can_use_llm()
    analysis_payload = build_requirement_analysis(
        requirement.content,
        title=requirement.title,
        use_llm=use_llm,
    )
    requirement.analysis_payload = analysis_payload
    requirement.parsed_points = [
        point["title"]
        for point in analysis_payload.get("selected_points", [])
        if isinstance(point, dict) and point.get("title")
    ]
    requirement.analysis_status = "draft"
    requirement.reviewed_at = None
    requirement.core_regression_points = []
    requirement.tool_plan = []
    for review_point in list(requirement.review_points):
        db.delete(review_point)
    requirement.last_analyzed_at = datetime.utcnow()
    db.commit()

    redirect_url = f"/requirements/{requirement_id}?reanalyzed=1"
    if llm_unavailable:
        redirect_url += "&llm_unavailable=1"
    return RedirectResponse(url=redirect_url, status_code=303)


@router.get("/requirements/{requirement_id}/xmind-markdown", name="requirement_xmind_markdown")
def export_requirement_xmind_markdown(requirement_id: int, db: Session = Depends(get_db)) -> PlainTextResponse:
    requirement = db.query(Requirement).filter(Requirement.id == requirement_id).first()
    if requirement is None:
        raise HTTPException(status_code=404, detail="Requirement not found.")

    markdown = generate_xmind_markdown(
        requirement.title,
        requirement.content,
        analysis_payload=requirement.analysis_payload,
    )
    safe_title = f"requirement_{requirement_id}_xmind"
    headers = {
        "Content-Disposition": f'attachment; filename="{safe_title}.md"',
    }
    return PlainTextResponse(content=markdown, media_type="text/markdown; charset=utf-8", headers=headers)


@router.get("/requirements/{requirement_id}", name="requirement_detail")
def requirement_detail(
    requirement_id: int,
    request: Request,
    generated: int | None = Query(default=None),
    imported: int | None = Query(default=None),
    reanalyzed: int | None = Query(default=None),
    reviewed: int | None = Query(default=None),
    tool_planned: int | None = Query(default=None),
    review_required: int | None = Query(default=None),
    edited: int | None = Query(default=None),
    llm_unavailable: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    requirement = (
        db.query(Requirement)
        .options(
            joinedload(Requirement.project),
            joinedload(Requirement.test_cases),
            joinedload(Requirement.review_points),
            subqueryload(Requirement.workflows).joinedload(TestWorkflow.stages),
        )
        .filter(Requirement.id == requirement_id)
        .first()
    )
    if requirement is None:
        raise HTTPException(status_code=404, detail="Requirement not found.")

    estimated_case_count = len(
        generate_structured_cases(
            requirement.title,
            requirement.content,
            analysis_payload=requirement.analysis_payload,
        )
    )

    wf = requirement.workflows[0] if requirement.workflows else None
    wf_stages: dict[str, WorkflowStage] = {}
    wf_stage_list: list[WorkflowStage] = []
    if wf:
        wf_stages = {s.stage_type: s for s in wf.stages}
        wf_stage_list = sorted(wf.stages, key=lambda s: STAGE_ORDER.get(s.stage_type, 99))

    return templates.TemplateResponse(
        request,
        "requirements/detail.html",
        {
            "request": request,
            "requirement": requirement,
            "generated": generated,
            "imported": imported,
            "reanalyzed": reanalyzed,
            "reviewed": reviewed,
            "tool_planned": tool_planned,
            "review_required": review_required,
            "edited": edited,
            "llm_unavailable": llm_unavailable,
            "estimated_case_count": estimated_case_count,
            "workflow": wf,
            "wf_stages": wf_stages,
            "wf_stage_list": wf_stage_list,
            "stage_labels": STAGE_LABELS,
            "stage_types": STAGE_TYPES,
            "can_use_llm_flag": _can_use_llm(),
            "analysis_sections": _build_analysis_sections(requirement),
            "summary_sections": _build_summary_sections(requirement),
            "scenario_sections": _build_scenario_sections(requirement),
            "scope_sections": _build_scope_sections(requirement),
            "test_point_rows": _normalized_test_point_rows(_analysis_payload_dict(requirement)),
            "gap_rows": _build_special_issue_sections(_analysis_payload_dict(requirement))["general_gaps"],
            "known_issue_rows": _build_special_issue_sections(_analysis_payload_dict(requirement))["known_issues"],
            "prelaunch_check_rows": _build_special_issue_sections(_analysis_payload_dict(requirement))["prelaunch_checks"],
            "generic_test_point_rows": _normalized_generic_test_point_rows(_analysis_payload_dict(requirement)),
            "term_rows": _normalized_terms_rows(_analysis_payload_dict(requirement)),
            "traceability_rows": _normalized_traceability_rows(_analysis_payload_dict(requirement)),
            "coverage_sections": _build_coverage_sections(requirement),
            "consistency_sections": _build_consistency_sections(requirement),
            "quality_summary": _build_quality_summary(requirement),
            "review_point_rows": _build_review_point_rows(requirement),
            "custom_points": _normalized_custom_points(requirement),
            "core_regression_points": _normalized_core_regression_points(requirement),
            "tool_plan": list(requirement.tool_plan or []),
            "tool_result": list(requirement.tool_result or []),
        },
    )


@router.post("/requirements/{requirement_id}/review", name="requirement_review")
def review_requirement(
    requirement_id: int,
    review_points_payload: str = Form(default="[]"),
    deleted_point_ids: str = Form(default=""),
    custom_points: str = Form(default=""),
    review_notes: str = Form(default=""),
    db: Session = Depends(get_db),
):
    requirement = (
        db.query(Requirement)
        .options(joinedload(Requirement.review_points))
        .filter(Requirement.id == requirement_id)
        .first()
    )
    if requirement is None:
        raise HTTPException(status_code=404, detail="Requirement not found.")

    payload_rows = _parse_review_points_payload(review_points_payload)
    deleted_ids = _parse_deleted_ids(deleted_point_ids)
    existing_points = {point.id: point for point in requirement.review_points if point.id is not None}
    kept_ids: set[int] = set()
    core_regression_points: list[str] = []
    selected_points: list[dict[str, str]] = []
    selected_test_points: list[dict[str, Any]] = []
    reviewed_test_points: list[dict[str, Any]] = []

    for index, row in enumerate(payload_rows):
        title = _clean_text(row.get("title"))
        if not title:
            continue

        point_id_raw = _clean_text(row.get("id"))
        point_id = int(point_id_raw) if point_id_raw.isdigit() else None
        point = existing_points.get(point_id) if point_id is not None else None
        if point is None:
            point = RequirementReviewPoint(requirement_id=requirement.id)
            db.add(point)
        else:
            kept_ids.add(point.id)

        category = _clean_text(row.get("category")).lower() or "functional"
        if category not in CATEGORY_LABELS:
            category = "functional"

        point.title = title
        point.category = category
        point.module = _clean_text(row.get("module")) or None
        point.context = _clean_text(row.get("context")) or "需求原文"
        point.requirement_source = _clean_text(row.get("requirement_source")) or title
        point.preconditions = _clean_text(row.get("preconditions")) or None
        point.steps = _clean_text(row.get("steps")) or None
        point.expected = _clean_text(row.get("expected")) or None
        priority = _clean_text(row.get("priority")) or "P2"
        source_refs_text = _clean_text(row.get("source_refs")) or point.requirement_source or title
        point.priority = priority
        point.is_selected = _string_to_bool(row.get("selected"))
        point.is_core = _string_to_bool(row.get("is_core"))
        point.source = _clean_text(row.get("source")) or point.source or "manual"
        point.sort_order = index
        point.updated_at = datetime.utcnow()

        reviewed_row = {
            "id": str(point.id or ""),
            "selected": point.is_selected,
            "is_core": point.is_core,
            "category": point.category,
            "module": point.module or requirement.title,
            "title": point.title,
            "context": point.context or "需求原文",
            "requirement_source": point.requirement_source or point.title,
            "source": point.source,
            "priority": priority,
            "source_refs": source_refs_text,
            "user_scenario": _string_to_bool(row.get("user_scenario")),
            "user_scenario_tag": _clean_text(row.get("user_scenario_tag")),
            "page_or_entry": _clean_text(row.get("page_or_entry")) or point.context or "需求原文",
            "preconditions": _clean_text(row.get("preconditions")),
            "action": _clean_text(row.get("action")) or point.title,
            "verification_focus": _clean_text(row.get("verification_focus")),
        }
        reviewed_test_points.append(reviewed_row)

        if point.is_selected:
            selected_points.append(
                {
                    "title": point.title,
                    "category": point.category,
                    "module": point.module or requirement.title,
                    "context": point.context or "需求原文",
                    "requirement_source": point.requirement_source or point.title,
                }
            )
            selected_test_points.append(
                {
                    "id": _clean_text(row.get("test_point_id")) or f"RTP-{index + 1:03d}",
                    "scope_item_id": _clean_text(row.get("scope_item_id")),
                    "title": point.title,
                    "type": _clean_text(row.get("point_type")) or "normal",
                    "category": point.category,
                    "module": point.module or requirement.title,
                    "role": _clean_text(row.get("role")) or "未说明",
                    "page_or_entry": _clean_text(row.get("page_or_entry")) or point.context or "需求原文",
                    "preconditions": _normalized_string_list((_clean_text(row.get("preconditions")) or "").split("；")),
                    "action": _clean_text(row.get("action")) or point.title,
                    "verification_focus": _normalized_string_list((_clean_text(row.get("verification_focus")) or "").split("；")),
                    "user_scenario": _string_to_bool(row.get("user_scenario")),
                    "user_scenario_tag": _clean_text(row.get("user_scenario_tag")),
                    "priority": priority,
                    "source_refs": _normalized_string_list(source_refs_text.split("；")),
                }
            )
        if point.is_selected and point.is_core and point.title not in core_regression_points:
            core_regression_points.append(point.title)

    for point_id, point in existing_points.items():
        if point_id in deleted_ids or point_id not in kept_ids:
            db.delete(point)

    custom_point_lines = _normalized_string_list(custom_points.splitlines())
    analysis_payload = dict(_analysis_payload_dict(requirement))
    review = analysis_payload.get("review") if isinstance(analysis_payload.get("review"), dict) else {}
    review["custom_points"] = custom_point_lines
    review["core_regression_points"] = core_regression_points
    review["reviewed_test_points"] = reviewed_test_points
    analysis_payload["review"] = review
    analysis_payload["selected_points"] = selected_points
    analysis_payload["test_points"] = selected_test_points

    requirement.analysis_payload = analysis_payload
    requirement.parsed_points = [point["title"] for point in selected_points]
    requirement.review_notes = review_notes.strip() or None
    requirement.core_regression_points = core_regression_points
    requirement.analysis_status = "reviewed"
    requirement.reviewed_at = datetime.utcnow()
    _append_tool_result(
        requirement,
        "人工确认",
        f"已确认 {len(selected_points)} 条测试点，选出 {len(core_regression_points)} 条核心回归点。",
    )
    db.commit()

    return RedirectResponse(url=f"/requirements/{requirement_id}?reviewed=1", status_code=303)


@router.post("/requirements/{requirement_id}/tool-plan", name="requirement_tool_plan")
def create_requirement_tool_plan(requirement_id: int, db: Session = Depends(get_db)):
    requirement = db.query(Requirement).filter(Requirement.id == requirement_id).first()
    if requirement is None:
        raise HTTPException(status_code=404, detail="Requirement not found.")

    requirement.tool_plan = _build_tool_plan(requirement)
    _append_tool_result(
        requirement,
        "工具规划",
        f"已生成 {len(requirement.tool_plan or [])} 条测试工具与执行策略建议。",
    )
    db.commit()

    return RedirectResponse(url=f"/requirements/{requirement_id}?tool_planned=1", status_code=303)