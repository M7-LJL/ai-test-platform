from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from dotenv import load_dotenv

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None  # type: ignore[assignment]

load_dotenv()

logger = logging.getLogger(__name__)

LLM_API_KEY = os.getenv("LLM_API_KEY", os.getenv("OPENAI_API_KEY", "")).strip()
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "").strip()
LLM_MODEL = os.getenv("LLM_MODEL", os.getenv("OPENAI_MODEL", "")).strip()
if not LLM_MODEL:
    LLM_MODEL = "deepseek-chat" if "deepseek.com" in LLM_BASE_URL else "gpt-4"

client_kwargs: dict[str, str] = {"api_key": LLM_API_KEY}
if LLM_BASE_URL:
    client_kwargs["base_url"] = LLM_BASE_URL

openai_client = OpenAI(**client_kwargs) if OpenAI is not None and LLM_API_KEY else None

CATEGORY_LABELS = {
    "functional": "功能点",
    "boundary": "边界点",
    "exception": "异常点",
}

ANALYSIS_DIMENSIONS = (
    "角色/用户",
    "页面/入口",
    "操作/动作",
    "接口/数据",
    "状态/流程",
    "规则/约束",
    "非功能",
    "关联/依赖",
    "隐性需求/界面状态",
)
REAL_USER_SCENE_TAGS = (
    "误操作/反悔",
    "重复/连续操作",
    "中断与恢复",
    "网络与环境",
    "输入与粘贴",
    "多端与多态",
    "用户差异",
)
FUZZY_TERMS = ("尽快", "适量", "部分", "稍后", "及时", "若干", "尽量", "按需")
NOISE_LINE_KEYWORDS = ("会议纪要", "待补充", "后续补齐", "暂不处理", "先这样", "仅供参考")
REPEAT_SCENE_KEYWORDS = ("首次", "第一次", "再次", "第二次", "重复", "连续", "多次", "重试", "再点", "重复提交")
STATE_SCENE_KEYWORDS = ("草稿", "已提交", "审核中", "已通过", "已驳回", "已关闭", "已完成", "状态")
RESULT_SCENE_KEYWORDS = ("成功", "失败", "拦截", "不展示", "不可", "禁止", "幂等", "提示")
KNOWN_ISSUE_KEYWORDS = ("失败", "报错", "问题", "异常", "错误", "缺陷", "bug", "BUG")
PRELAUNCH_CHECK_KEYWORDS = ("上线", "发布前", "上线前", "检查", "核对", "确认")
HEADING_LINE_PATTERNS = (
    r"^\s*\d+[.、]\s*\S.+$",
    r"^\s*【[^】]+】\s*$",
    r"^\s*\[[^\]]+\]\s*$",
)

BUSINESS_ACTOR_HINTS = (
    "普通用户",
    "用户",
    "管理员",
    "运营",
    "审核员",
    "商家",
    "门店",
    "店长",
    "客服",
    "财务",
)
RULE_ACTOR_HINTS = BUSINESS_ACTOR_HINTS + ("系统",)
BOUNDARY_KEYWORDS = (
    "最大",
    "最小",
    "上限",
    "下限",
    "边界",
    "次数",
    "比例",
    "长度",
    "连续",
    "为空",
    "开关",
    "配置",
    "超出",
    "极端",
    "临界",
    "阈值",
)
EXCEPTION_KEYWORDS = (
    "错误",
    "失败",
    "异常",
    "无权限",
    "不存在",
    "超时",
    "中断",
    "不可用",
    "驳回",
    "降级",
    "拦截",
    "不展示",
    "不发放",
    "禁止",
    "兜底",
)
CONFIG_KEYWORDS = ("配置", "开关", "白名单", "标签", "比例", "规则", "参数")
STATE_KEYWORDS = ("状态", "流转", "审核", "审批", "提交", "驳回", "通过", "回退")
RESULT_KEYWORDS = ("提示", "展示", "跳转", "结果", "发放", "更新", "刷新", "显示")
DATA_KEYWORDS = ("记录", "日志", "埋点", "同步", "回流", "落库", "数据", "流水", "订单")
PERMISSION_KEYWORDS = ("权限", "角色", "可见", "可操作", "仅", "禁止", "无权限")
CRITICAL_RULE_KEYWORDS = (
    "支付",
    "审批",
    "发放",
    "配置",
    "白名单",
    "标签",
    "状态",
    "权限",
    "同步",
    "回流",
)
CONDITION_PATTERNS = (
    r"^(当.+?时)[，,:：]?(.*)$",
    r"^(如果.+?)[，,:：](.*)$",
    r"^(若.+?)[，,:：](.*)$",
    r"^(针对.+?)[，,:：](.*)$",
    r"^(对于.+?)[，,:：](.*)$",
    r"^(在.+?时)[，,:：]?(.*)$",
    r"^(.+?后)[，,:：](.*)$",
)

ANALYSIS_TOOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "meta": {
            "type": "object",
            "properties": {
                "analysis_version": {"type": "string"},
                "input_type": {"type": "string"},
                "used_llm": {"type": "boolean"},
                "source_title": {"type": "string"},
            },
            "required": ["analysis_version", "input_type", "used_llm", "source_title"],
            "additionalProperties": False,
        },
        "summary": {
            "type": "object",
            "properties": {
                "system_flow": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "系统流程摘要，3-6条",
                },
                "core_rules": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "核心业务规则，3-6条",
                },
                "main_risks": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "主要风险点，3-6条",
                },
                "test_focus": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "测试重点，3-6条",
                },
            },
            "required": ["system_flow", "core_rules", "main_risks", "test_focus"],
            "additionalProperties": False,
        },
        "gaps": {
            "type": "array",
            "items": {"type": "string"},
            "description": "需求漏洞或信息缺口，0-4条",
        },
        "test_standards": {
            "type": "array",
            "items": {"type": "string"},
            "description": "测试标准，2-5条",
        },
        "terms": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "term": {"type": "string"},
                    "meaning": {"type": "string"},
                    "source_refs": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["term", "meaning", "source_refs"],
                "additionalProperties": False,
            },
        },
        "scope_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "dimension": {"type": "string"},
                    "module": {"type": "string"},
                    "role": {"type": "string"},
                    "page_or_entry": {"type": "string"},
                    "object": {"type": "string"},
                    "rule_summary": {"type": "string"},
                    "priority": {"type": "string"},
                    "testable": {"type": "boolean"},
                    "source_refs": {"type": "array", "items": {"type": "string"}},
                    "notes": {"type": "string"},
                },
                "required": [
                    "id",
                    "name",
                    "dimension",
                    "module",
                    "role",
                    "page_or_entry",
                    "object",
                    "rule_summary",
                    "priority",
                    "testable",
                    "source_refs",
                    "notes",
                ],
                "additionalProperties": False,
            },
        },
        "test_points": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "scope_item_id": {"type": "string"},
                    "title": {"type": "string"},
                    "type": {"type": "string"},
                    "category": {"type": "string"},
                    "module": {"type": "string"},
                    "role": {"type": "string"},
                    "page_or_entry": {"type": "string"},
                    "preconditions": {"type": "array", "items": {"type": "string"}},
                    "action": {"type": "string"},
                    "verification_focus": {"type": "array", "items": {"type": "string"}},
                    "user_scenario": {"type": "boolean"},
                    "user_scenario_tag": {"type": "string"},
                    "priority": {"type": "string"},
                    "source_refs": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "id",
                    "scope_item_id",
                    "title",
                    "type",
                    "category",
                    "module",
                    "role",
                    "page_or_entry",
                    "preconditions",
                    "action",
                    "verification_focus",
                    "user_scenario",
                    "user_scenario_tag",
                    "priority",
                    "source_refs",
                ],
                "additionalProperties": False,
            },
        },
        "selected_points": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "简洁测试点标题"},
                    "category": {
                        "type": "string",
                        "enum": ["functional", "boundary", "exception"],
                    },
                    "module": {"type": "string", "description": "所属模块"},
                    "context": {"type": "string", "description": "场景上下文"},
                    "requirement_source": {"type": "string", "description": "原始需求依据"},
                },
                "required": ["title", "category", "module", "context", "requirement_source"],
                "additionalProperties": False,
            },
            "description": "测试点列表，建议 6-20 条，需覆盖功能点、边界点、异常点",
        },
        "traceability": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "scope_item_id": {"type": "string"},
                    "test_point_ids": {"type": "array", "items": {"type": "string"}},
                    "source_refs": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["scope_item_id", "test_point_ids", "source_refs"],
                "additionalProperties": False,
            },
        },
        "coverage_check": {
            "type": "object",
            "properties": {
                "roles": {"type": "string"},
                "pages_entries": {"type": "string"},
                "actions": {"type": "string"},
                "data_fields": {"type": "string"},
                "states_flows": {"type": "string"},
                "rules_constraints": {"type": "string"},
                "non_functional": {"type": "string"},
                "dependencies": {"type": "string"},
                "implicit_states": {"type": "string"},
            },
            "required": [
                "roles",
                "pages_entries",
                "actions",
                "data_fields",
                "states_flows",
                "rules_constraints",
                "non_functional",
                "dependencies",
                "implicit_states",
            ],
            "additionalProperties": False,
        },
        "consistency_check": {
            "type": "object",
            "properties": {
                "anchoring_status": {"type": "string"},
                "ambiguous_terms": {"type": "array", "items": {"type": "string"}},
                "fuzzy_phrases": {"type": "array", "items": {"type": "string"}},
                "my_understanding": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["anchoring_status", "ambiguous_terms", "fuzzy_phrases", "my_understanding"],
            "additionalProperties": False,
        },
        "quality_report": {
            "type": "object",
            "properties": {
                "score": {"type": "integer"},
                "missing_source_count": {"type": "integer"},
                "generic_statement_count": {"type": "integer"},
                "needs_review": {"type": "boolean"},
            },
            "required": ["score", "missing_source_count", "generic_statement_count", "needs_review"],
            "additionalProperties": False,
        },
        "review": {
            "type": "object",
            "properties": {
                "custom_points": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "core_regression_points": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["custom_points", "core_regression_points"],
            "additionalProperties": False,
        },
    },
    "required": [
        "meta",
        "summary",
        "gaps",
        "test_standards",
        "terms",
        "scope_items",
        "test_points",
        "selected_points",
        "traceability",
        "coverage_check",
        "consistency_check",
        "quality_report",
        "review",
    ],
    "additionalProperties": False,
}


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip(" .。;；,，:-")


def _normalize_point(sentence: str) -> str:
    sentence = _clean_text(sentence)
    sentence = re.sub(r"^(用户|系统|页面|应用|平台)", "", sentence).strip()

    replacements = (
        (r"^(需要|应当|应该|可以|能够)", ""),
        (r"^支持", ""),
        (r"^实现", ""),
        (r"^提供", ""),
        (r"^具备", ""),
    )
    for pattern, replacement in replacements:
        sentence = re.sub(pattern, replacement, sentence).strip()

    if not sentence:
        return ""
    if sentence.startswith("验证"):
        return sentence
    return f"验证{sentence}"


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        cleaned = _clean_text(value)
        if cleaned and cleaned not in result:
            result.append(cleaned)
    return result


def _normalize_source_refs(value: Any, *, fallback: str = "需求原文", limit: int = 6) -> list[str]:
    if isinstance(value, list):
        refs = _dedupe([str(item) for item in value if isinstance(item, str) and _clean_text(item)])
        return refs[:limit] if refs else [fallback]
    if isinstance(value, str) and _clean_text(value):
        return [_clean_text(value)]
    return [fallback]


def _looks_like_explicit_identifier(text: str) -> bool:
    cleaned = _clean_text(text)
    if not cleaned:
        return False
    patterns = (
        r"/api/[A-Za-z0-9/_\-]+",
        r"[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*",
        r"[A-Za-z_][A-Za-z0-9_]{2,}",
        r"[a-z]+(?:_[a-z0-9]+){1,}",
        r"[A-Z]{2,}-\d{2,}",
    )
    return any(re.search(pattern, cleaned) for pattern in patterns)


def _anchored_or_pending(value: str, *evidence_texts: str, fallback: str = "待确认") -> str:
    cleaned = _clean_text(value)
    if not cleaned:
        return fallback
    if not _looks_like_explicit_identifier(cleaned):
        return cleaned
    normalized_evidence = " ".join(_clean_text(text) for text in evidence_texts if _clean_text(text))
    if cleaned in normalized_evidence:
        return cleaned
    return fallback


def _contains_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _first_keyword(text: str, keywords: tuple[str, ...]) -> str:
    for keyword in keywords:
        if keyword in text:
            return keyword
    return ""


def _shorten_text(text: str, limit: int = 28) -> str:
    cleaned = _clean_text(text)
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def _split_sentences(content: str) -> list[str]:
    normalized_content = content or ""
    normalized_content = re.sub(r"(?<!http)(?<!https):(?=[^\d/])", "：", normalized_content)
    raw_parts = re.split(r"[\r\n]+|(?<=[。！？!?；;])|(?<=：)(?=.{4,})", normalized_content)
    sentences: list[str] = []
    for part in raw_parts:
        cleaned = re.sub(r"^\s*[-*0-9.)、#]+\s*", "", part).strip()
        cleaned = cleaned.strip("。！？!?；;")
        if len(cleaned) >= 4:
            sentences.append(cleaned)
    return sentences


def _looks_like_heading_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if any(re.match(pattern, stripped) for pattern in HEADING_LINE_PATTERNS):
        return True
    return bool(re.match(r"^[^\s:：]{2,20}(页|页面|列表|详情|配置|中心|管理|弹窗|消息|后台)$", stripped))


def _normalize_heading_line(line: str) -> str:
    stripped = _clean_text(line)
    stripped = re.sub(r"^【|】$", "", stripped)
    stripped = re.sub(r"^\[|\]$", "", stripped)
    stripped = re.sub(r"^-+", "", stripped).strip("-").strip()
    return stripped


def _classify_requirement_item_type(sentence: str, *, module: str = "", context: str = "") -> str:
    text = " ".join(part for part in (_clean_text(module), _clean_text(context), _clean_text(sentence)) if part)
    if _contains_keyword(text, PRELAUNCH_CHECK_KEYWORDS) and "检查" in text:
        return "prelaunch_check"
    if _contains_keyword(text, KNOWN_ISSUE_KEYWORDS) and any(keyword in text for keyword in ("导致", "失败", "报错", "异常", "问题")):
        return "known_issue"
    return "functional"


def _preprocess_requirement_content(content: str) -> str:
    if not content:
        return ""
    cleaned_lines: list[str] = []
    seen_lines: set[str] = set()
    for raw_line in content.splitlines():
        line = raw_line.rstrip()
        normalized = _clean_text(line)
        if not normalized:
            if cleaned_lines and cleaned_lines[-1] != "":
                cleaned_lines.append("")
            continue
        if _looks_like_heading_line(normalized):
            normalized_heading = _normalize_heading_line(normalized)
            cleaned_lines.append(f"## {normalized_heading}")
            continue
        if normalized in seen_lines:
            continue
        if len(normalized) <= 12 and any(keyword in normalized for keyword in NOISE_LINE_KEYWORDS):
            continue
        cleaned_lines.append(line)
        seen_lines.add(normalized)
    return "\n".join(cleaned_lines).strip()


def _heading_level(line: str) -> tuple[int, str] | None:
    match = re.match(r"^\s{0,3}(#{1,6})\s*(.+?)\s*$", line)
    if not match:
        return None
    return len(match.group(1)), _clean_text(match.group(2))


def _bullet_text(line: str) -> str | None:
    match = re.match(r"^\s*(?:[-*+]|\d+[.)])\s+(.+?)\s*$", line)
    if not match:
        return None
    return _clean_text(match.group(1))


def _classify_point(sentence: str) -> str:
    if _contains_keyword(sentence, EXCEPTION_KEYWORDS):
        return "exception"
    if _contains_keyword(sentence, BOUNDARY_KEYWORDS):
        return "boundary"
    return "functional"


def _extract_condition_clause(sentence: str) -> tuple[str, str]:
    text = _clean_text(sentence)
    for pattern in CONDITION_PATTERNS:
        match = re.match(pattern, text)
        if not match:
            continue
        condition = _clean_text(match.group(1))
        remainder = _clean_text(match.group(2))
        if condition:
            return condition, remainder or text
    return "", text


def _infer_semantic_category(sentence: str, fallback: str = "functional") -> str:
    text = _clean_text(sentence)
    if _contains_keyword(text, EXCEPTION_KEYWORDS) or _contains_keyword(text, PERMISSION_KEYWORDS):
        return "exception"
    if _contains_keyword(text, BOUNDARY_KEYWORDS) or _contains_keyword(text, CONFIG_KEYWORDS):
        return "boundary"
    return fallback if fallback in CATEGORY_LABELS else "functional"


def _extract_requirement_items(content: str, title: str = "") -> list[dict[str, str]]:
    lines = [line.rstrip() for line in (content or "").splitlines()]
    heading_info = [_heading_level(line) for line in lines]
    heading_levels = [level for info in heading_info if info for level, _ in [info]]
    module_heading_level = min(heading_levels) if heading_levels else None

    current_module = _clean_text(title) or "默认模块"
    context_stack: list[tuple[int, str]] = []
    items: list[dict[str, str]] = []
    paragraph_buffer: list[str] = []

    def current_context_text() -> str:
        return " / ".join(text for _, text in context_stack).strip()

    def add_sentence(sentence: str) -> None:
        cleaned = _clean_text(sentence)
        if len(cleaned) < 4:
            return
        current_context = current_context_text()
        items.append(
            {
                "module": current_module,
                "context": current_context,
                "sentence": cleaned,
                "category": _classify_point(cleaned),
                "item_type": _classify_requirement_item_type(cleaned, module=current_module, context=current_context),
            }
        )

    def flush_paragraph() -> None:
        nonlocal paragraph_buffer
        if paragraph_buffer:
            for sentence in _split_sentences(" ".join(paragraph_buffer)):
                add_sentence(sentence)
        paragraph_buffer = []

    for line in lines:
        heading = _heading_level(line)
        if heading:
            flush_paragraph()
            level, text = heading
            if module_heading_level is not None and level == module_heading_level:
                current_module = text or current_module
                context_stack = []
            else:
                while context_stack and context_stack[-1][0] >= level:
                    context_stack.pop()
                context_stack.append((level, text))
            continue

        bullet = _bullet_text(line)
        if bullet is not None:
            flush_paragraph()
            add_sentence(bullet)
            continue

        if line.strip():
            paragraph_buffer.append(line.strip())
        else:
            flush_paragraph()

    flush_paragraph()

    if items:
        return items

    return [
        {
            "module": current_module,
            "context": "",
            "sentence": sentence,
            "category": _classify_point(sentence),
            "item_type": _classify_requirement_item_type(sentence, module=current_module, context=""),
        }
        for sentence in _split_sentences(content)
    ]


def _normalize_table_key(value: str) -> str:
    return re.sub(r"[\s:：()（）/_\-]+", "", _clean_text(value)).lower()


def _table_cells(line: str) -> list[str] | None:
    stripped = line.strip()
    if not stripped.startswith("|") or stripped.count("|") < 2:
        return None
    return [cell.strip() for cell in stripped.strip("|").split("|")]


def _is_markdown_table_separator(cells: list[str] | None) -> bool:
    if not cells:
        return False
    cleaned = [re.sub(r"\s+", "", cell) for cell in cells]
    return all(bool(cell) and re.fullmatch(r":?-{3,}:?", cell) for cell in cleaned)


def _extract_markdown_tables(content: str, title: str = "") -> list[dict[str, Any]]:
    lines = [line.rstrip() for line in (content or "").splitlines()]
    current_module = _clean_text(title) or "默认模块"
    context_stack: list[tuple[int, str]] = []
    tables: list[dict[str, Any]] = []
    index = 0

    while index < len(lines):
        line = lines[index]
        heading = _heading_level(line)
        if heading:
            level, text = heading
            if level == 1:
                current_module = text or current_module
                context_stack = []
            else:
                while context_stack and context_stack[-1][0] >= level:
                    context_stack.pop()
                context_stack.append((level, text))
            index += 1
            continue

        header_cells = _table_cells(line)
        separator_cells = _table_cells(lines[index + 1]) if index + 1 < len(lines) else None
        if header_cells and separator_cells and _is_markdown_table_separator(separator_cells):
            rows: list[dict[str, str]] = []
            index += 2
            while index < len(lines):
                row_cells = _table_cells(lines[index])
                if not row_cells or _is_markdown_table_separator(row_cells):
                    break
                if len(row_cells) < len(header_cells):
                    row_cells.extend([""] * (len(header_cells) - len(row_cells)))
                row_cells = row_cells[:len(header_cells)]
                row = {
                    header_cells[col_index]: row_cells[col_index]
                    for col_index in range(len(header_cells))
                    if _clean_text(header_cells[col_index])
                }
                if any(_clean_text(value) for value in row.values()):
                    rows.append(row)
                index += 1
            if rows:
                tables.append(
                    {
                        "module": current_module,
                        "heading_path": [text for _, text in context_stack],
                        "nearest_heading": context_stack[-1][1] if context_stack else current_module,
                        "headers": header_cells,
                        "rows": rows,
                    }
                )
            continue

        index += 1

    return tables


def _table_row_get(row: dict[str, str], *candidate_headers: str) -> str:
    normalized_candidates = [_normalize_table_key(header) for header in candidate_headers if _normalize_table_key(header)]
    for key, value in row.items():
        normalized_key = _normalize_table_key(key)
        if any(candidate in normalized_key or normalized_key in candidate for candidate in normalized_candidates):
            cleaned_value = _clean_text(value)
            if cleaned_value:
                return cleaned_value
    return ""


def _extract_structured_terms(content: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for table in _extract_markdown_tables(content):
        headers_key = [_normalize_table_key(header) for header in table["headers"]]
        if not any("术语" in header for header in headers_key):
            continue
        if not any("含义" in header or "说明" in header for header in headers_key):
            continue
        for row in table["rows"]:
            term = _table_row_get(row, "术语", "名词")
            meaning = _table_row_get(row, "本需求中的含义", "含义", "说明")
            source = _table_row_get(row, "需求来源", "来源")
            if not term or not meaning or term in seen:
                continue
            rows.append(
                {
                    "term": term,
                    "meaning": meaning,
                    "source_refs": [source or "需求原文"],
                }
            )
            seen.add(term)
    return rows[:12]


def _extract_structured_scope_items(content: str, title: str = "") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    fallback_module = _clean_text(title) or "默认模块"

    for table in _extract_markdown_tables(content, title=title):
        nearest_heading = _clean_text(table.get("nearest_heading", "")) or fallback_module
        heading_path = [_clean_text(item) for item in table.get("heading_path", []) if _clean_text(item)]
        headers_key = [_normalize_table_key(header) for header in table["headers"]]
        has_scope_table = (
            any("功能点" in header for header in headers_key)
            and any("需求来源" in header or "对应需求" in header for header in headers_key)
        )
        if not has_scope_table:
            continue

        dimension = nearest_heading if nearest_heading in ANALYSIS_DIMENSIONS else ""
        if not dimension:
            for path_item in reversed(heading_path):
                if path_item in ANALYSIS_DIMENSIONS:
                    dimension = path_item
                    break
        if not dimension and any("测试范围" in item for item in heading_path):
            dimension = "操作/动作"
        if not dimension:
            dimension = "操作/动作"

        for row in table["rows"]:
            name = _table_row_get(row, "功能点", "功能", "对应功能")
            focus = _table_row_get(row, "测试关注点", "关注点", "备注")
            source = _table_row_get(row, "对应需求", "需求来源", "来源")
            priority = _table_row_get(row, "优先级")
            notes = _table_row_get(row, "备注")
            if not name:
                continue
            key = (dimension, name, source or notes)
            if key in seen:
                continue
            rows.append(
                {
                    "id": f"S{len(rows) + 1:03d}",
                    "name": name,
                    "dimension": dimension,
                    "module": fallback_module,
                    "role": _table_row_get(row, "角色", "用户") or "未说明",
                    "page_or_entry": _table_row_get(row, "入口/页面", "页面/入口", "入口", "页面") or nearest_heading or fallback_module,
                    "object": _table_row_get(row, "对象", "字段", "数据项") or name,
                    "rule_summary": focus or notes or name,
                    "priority": priority or "P1",
                    "testable": (_table_row_get(row, "可测性") or "是") != "否",
                    "source_refs": [source or "需求原文"],
                    "notes": notes,
                }
            )
            seen.add(key)
    return rows[:40]


def _extract_structured_test_points(content: str, title: str = "") -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    fallback_module = _clean_text(title) or "默认模块"

    for table in _extract_markdown_tables(content, title=title):
        headers_key = [_normalize_table_key(header) for header in table["headers"]]
        has_scene_table = (
            any("场景类型" in header for header in headers_key)
            and any("测试关注点" in header or "功能点" in header for header in headers_key)
        )
        if not has_scene_table:
            continue
        for index, row in enumerate(table["rows"], start=1):
            scene_type = _table_row_get(row, "场景类型")
            title_text = _table_row_get(row, "测试关注点", "功能点")
            module = _table_row_get(row, "对应功能", "模块") or fallback_module
            source = _table_row_get(row, "需求来源", "对应需求", "来源")
            if not title_text:
                continue
            category = _infer_semantic_category(title_text, _classify_point(title_text))
            key = (module, title_text)
            if key in seen:
                continue
            points.append(
                {
                    "id": f"TP-S{len(points) + 1:03d}",
                    "scope_item_id": "",
                    "title": title_text,
                    "type": "user_scene" if scene_type else "normal",
                    "category": category,
                    "module": module,
                    "role": _table_row_get(row, "角色", "用户") or "未说明",
                    "page_or_entry": _table_row_get(row, "入口/页面", "页面/入口", "页面") or module,
                    "preconditions": [],
                    "action": title_text,
                    "verification_focus": [title_text],
                    "user_scenario": bool(scene_type),
                    "user_scenario_tag": scene_type,
                    "priority": _table_row_get(row, "优先级") or "P1",
                    "source_refs": [source or "需求原文"],
                }
            )
            seen.add(key)
    return points[:40]


def _extract_structured_gaps(content: str) -> list[str]:
    lines = [line.rstrip() for line in (content or "").splitlines()]
    current_section = ""
    gaps: list[str] = []
    for line in lines:
        heading = _heading_level(line)
        if heading:
            _, text = heading
            current_section = text
            continue
        if not current_section or ("疑义" not in current_section and "待确认" not in current_section):
            continue
        bullet = _bullet_text(line)
        if bullet is None:
            continue
        cleaned = re.sub(r"^\[[ xX]\]\s*", "", bullet).strip()
        cleaned = re.sub(r"^\*\*(.+?)\*\*[:：]?", r"\1", cleaned).strip()
        cleaned = _clean_text(cleaned)
        if cleaned:
            gaps.append(cleaned)
    return _dedupe(gaps)[:8]


def _score_rule_unit(unit: dict[str, Any]) -> int:
    score = 1
    if unit["condition"]:
        score += 2
    if unit["actor"]:
        score += 1
    if unit["has_result"]:
        score += 2
    if unit["has_state"]:
        score += 1
    if unit["has_data"]:
        score += 2
    if unit["has_config"]:
        score += 1
    if unit["has_boundary"]:
        score += 1
    if unit["has_exception"]:
        score += 2
    if unit["has_permission"]:
        score += 2
    if _contains_keyword(unit["source"], CRITICAL_RULE_KEYWORDS):
        score += 2
    if len(unit["source"]) >= 18:
        score += 1
    return score


def _build_rule_unit(item: dict[str, str]) -> dict[str, Any]:
    sentence = _clean_text(item.get("sentence", ""))
    condition, remainder = _extract_condition_clause(sentence)
    action = _clean_text(remainder or sentence)
    actor = _first_keyword(sentence, RULE_ACTOR_HINTS)

    context_parts = [item.get("context", ""), condition]
    context = " / ".join(part for part in context_parts if _clean_text(part)).strip()

    unit = {
        "module": _clean_text(item.get("module", "")) or "默认模块",
        "context": context or "需求原文",
        "source": sentence,
        "actor": actor,
        "condition": condition,
        "action": action,
        "category": _infer_semantic_category(sentence, item.get("category", "functional")),
        "has_boundary": _contains_keyword(sentence, BOUNDARY_KEYWORDS),
        "has_exception": _contains_keyword(sentence, EXCEPTION_KEYWORDS),
        "has_config": _contains_keyword(sentence, CONFIG_KEYWORDS),
        "has_state": _contains_keyword(sentence, STATE_KEYWORDS),
        "has_result": _contains_keyword(sentence, RESULT_KEYWORDS),
        "has_data": _contains_keyword(sentence, DATA_KEYWORDS),
        "has_permission": _contains_keyword(sentence, PERMISSION_KEYWORDS),
    }
    unit["score"] = _score_rule_unit(unit)
    return unit


def _extract_rule_units(content: str, title: str = "") -> list[dict[str, Any]]:
    items = _extract_requirement_items(content, title=title)
    units: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for item in items:
        if item.get("item_type") != "functional":
            continue
        unit = _build_rule_unit(item)
        if not unit["source"]:
            continue
        key = (unit["module"], unit["source"])
        if key in seen:
            continue
        seen.add(key)
        units.append(unit)

    units.sort(key=lambda unit: (-int(unit["score"]), unit["module"], unit["source"]))
    return units


def _extract_special_requirement_items(content: str, title: str = "") -> dict[str, list[dict[str, str]]]:
    items = _extract_requirement_items(content, title=title)
    grouped = {"known_issue": [], "prelaunch_check": []}
    seen: set[tuple[str, str]] = set()
    for item in items:
        item_type = str(item.get("item_type") or "")
        if item_type not in grouped:
            continue
        key = (_clean_text(item.get("module", "")), _clean_text(item.get("sentence", "")))
        if not key[1] or key in seen:
            continue
        seen.add(key)
        grouped[item_type].append(
            {
                "module": _clean_text(item.get("module", "")) or _clean_text(title) or "默认模块",
                "context": _clean_text(item.get("context", "")) or "需求原文",
                "sentence": _clean_text(item.get("sentence", "")),
            }
        )
    return grouped


def _rule_label(unit: dict[str, Any]) -> str:
    action = unit.get("action") or unit.get("source") or ""
    action = re.sub(r"^(支持|实现|提供|具备|需要|应当|应该)", "", action).strip()
    return _shorten_text(action or "当前规则", limit=30)


def _rule_context(unit: dict[str, Any]) -> str:
    return _clean_text(unit.get("condition") or unit.get("context") or "需求原文") or "需求原文"


def _rule_expectations(unit: dict[str, Any]) -> list[str]:
    expectations: list[str] = []
    if unit["has_permission"]:
        expectations.append("角色/权限校验正确")
    if unit["has_config"]:
        expectations.append("配置命中结果正确")
    if unit["has_state"]:
        expectations.append("状态流转正确")
    if unit["has_result"]:
        expectations.append("页面反馈明确")
    if unit["has_data"]:
        expectations.append("结果记录或回流一致")
    if not expectations:
        expectations.append("结果符合需求预期")
    return expectations


def _infer_dimension(unit: dict[str, Any]) -> str:
    if unit["has_permission"] or unit["actor"]:
        return "角色/用户"
    if unit["has_state"]:
        return "状态/流程"
    if unit["has_data"]:
        return "接口/数据"
    if unit["has_config"]:
        return "规则/约束"
    if unit["has_result"]:
        return "页面/入口"
    if unit["has_boundary"] or unit["has_exception"]:
        return "隐性需求/界面状态"
    return "操作/动作"


def _infer_priority_from_unit(unit: dict[str, Any]) -> str:
    if unit["has_permission"] or unit["has_exception"] or unit["has_data"]:
        return "P0"
    if unit["has_state"] or unit["has_config"]:
        return "P1"
    return "P2"


def _extract_page_or_entry(unit: dict[str, Any]) -> str:
    context = _rule_context(unit)
    if context != "需求原文":
        return _anchored_or_pending(context, unit.get("source", ""), unit.get("context", ""))
    return "待确认"


def _extract_business_object(unit: dict[str, Any]) -> str:
    hits = [keyword for keyword in BUSINESS_ACTOR_HINTS + CONFIG_KEYWORDS if keyword in unit["source"]]
    if hits:
        return " / ".join(_dedupe(hits)[:3])
    return "待确认"


def _build_scope_items(rule_units: list[dict[str, Any]], title: str = "") -> list[dict[str, Any]]:
    scope_items: list[dict[str, Any]] = []
    fallback_module = _clean_text(title) or "默认模块"
    for index, unit in enumerate(rule_units[:24], start=1):
        scope_items.append(
            {
                "id": f"S{index:03d}",
                "name": _rule_label(unit),
                "dimension": _infer_dimension(unit),
                "module": _clean_text(unit.get("module")) or fallback_module,
                "role": unit.get("actor") or "未说明",
                "page_or_entry": _extract_page_or_entry(unit),
                "object": _extract_business_object(unit),
                "rule_summary": _core_rule_text(unit),
                "priority": _infer_priority_from_unit(unit),
                "testable": True,
                "source_refs": [unit["source"]],
                "notes": "",
            }
        )
    return scope_items


def _scenario_tag_for_type(point_type: str) -> str:
    mapping = {
        "exception": "网络与环境",
        "boundary": "输入与粘贴",
        "state": "中断与恢复",
        "permission": "用户差异",
    }
    return mapping.get(point_type, "重复/连续操作")


def _is_protected_semantic_point(text: str) -> bool:
    normalized = _clean_text(text)
    return _contains_keyword(normalized, REPEAT_SCENE_KEYWORDS + STATE_SCENE_KEYWORDS + RESULT_SCENE_KEYWORDS)


def _coarsen_text_for_merge(text: str) -> str:
    normalized = _clean_text(text)
    normalized = re.sub(r"(主流程正确.*|在边界值.*|在失败.*|需补充真实用户场景.*)$", "", normalized).strip()
    normalized = re.sub(r"(页面反馈|状态流转|结果数据|边界样本验证|异常链路)$", "", normalized).strip()
    return normalized or _clean_text(text)


def _priority_rank(priority: str) -> int:
    mapping = {"P0": 0, "P1": 1, "P2": 2}
    return mapping.get(_clean_text(priority), 99)


def _merge_similar_test_points(test_points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged_points: list[dict[str, Any]] = []
    point_map: dict[tuple[str, ...], dict[str, Any]] = {}

    for point in test_points:
        title = str(point.get("title", ""))
        action = str(point.get("action", ""))
        protected = _is_protected_semantic_point(title) or _is_protected_semantic_point(action)
        if protected:
            key = (
                _clean_text(str(point.get("module", ""))),
                _clean_text(str(point.get("category", ""))),
                _clean_text(title),
                _clean_text(action),
                _clean_text(str(point.get("page_or_entry", ""))),
            )
        else:
            key = (
                _clean_text(str(point.get("module", ""))),
                _clean_text(str(point.get("category", ""))),
                _coarsen_text_for_merge(title),
                _coarsen_text_for_merge(action),
                _clean_text(str(point.get("page_or_entry", ""))),
            )

        existing = point_map.get(key)
        if existing is None:
            point_map[key] = {
                **point,
                "preconditions": _normalize_string_list(point.get("preconditions"), limit=6),
                "verification_focus": _normalize_string_list(point.get("verification_focus"), limit=8),
                "source_refs": _normalize_source_refs(point.get("source_refs"), limit=8),
            }
            merged_points.append(point_map[key])
            continue

        existing["preconditions"] = _dedupe(
            [*existing.get("preconditions", []), *_normalize_string_list(point.get("preconditions"), limit=6)]
        )[:6]
        existing["verification_focus"] = _dedupe(
            [*existing.get("verification_focus", []), *_normalize_string_list(point.get("verification_focus"), limit=8)]
        )[:8]
        existing["source_refs"] = _dedupe(
            [*existing.get("source_refs", []), *_normalize_source_refs(point.get("source_refs"), limit=8)]
        )[:8]
        if _priority_rank(str(point.get("priority", "P2"))) < _priority_rank(str(existing.get("priority", "P2"))):
            existing["priority"] = point.get("priority", existing.get("priority", "P2"))

    return merged_points[:36]


def _build_test_points_from_scope_items(scope_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    test_points: list[dict[str, Any]] = []
    seen_titles: set[str] = set()

    def append_point(point: dict[str, Any]) -> None:
        title_text = _normalize_point(str(point.get("title", "")))
        if not title_text or title_text in seen_titles:
            return
        point["title"] = title_text
        seen_titles.add(title_text)
        test_points.append(point)

    for index, scope_item in enumerate(scope_items, start=1):
        base_title = scope_item["name"]
        base_source = scope_item["source_refs"]
        module = scope_item["module"]
        role = scope_item["role"]
        entry = scope_item["page_or_entry"]
        priority = scope_item["priority"]

        append_point(
            {
                "id": f"TP{index:03d}-A",
                "scope_item_id": scope_item["id"],
                "title": f"{base_title}主流程正确，校验页面反馈、状态流转和结果数据",
                "type": "normal",
                "category": "functional",
                "module": module,
                "role": role,
                "page_or_entry": entry,
                "preconditions": [f"{role if role != '未说明' else '用户'}满足基础触发条件"],
                "action": f"进入{entry}并执行{base_title}",
                "verification_focus": _rule_expectations(
                    {
                        "has_permission": "权限" in scope_item["rule_summary"],
                        "has_config": "配置" in scope_item["rule_summary"],
                        "has_state": "状态" in scope_item["rule_summary"],
                        "has_result": True,
                        "has_data": "数据" in scope_item["rule_summary"] or "记录" in scope_item["rule_summary"],
                    }
                ),
                "user_scenario": False,
                "user_scenario_tag": "",
                "priority": priority,
                "source_refs": base_source,
            }
        )

        if scope_item["dimension"] in {"接口/数据", "状态/流程", "规则/约束", "隐性需求/界面状态"}:
            append_point(
                {
                    "id": f"TP{index:03d}-B",
                    "scope_item_id": scope_item["id"],
                    "title": f"{base_title}在边界值、空值或临界状态下的处理",
                    "type": "boundary",
                    "category": "boundary",
                    "module": module,
                    "role": role,
                    "page_or_entry": entry,
                    "preconditions": ["准备边界前、边界值、边界后测试数据"],
                    "action": f"在{entry}执行{base_title}的边界样本验证",
                    "verification_focus": ["边界命中结果正确", "页面提示明确", "状态保持一致"],
                    "user_scenario": False,
                    "user_scenario_tag": "",
                    "priority": "P1",
                    "source_refs": base_source,
                }
            )

        if scope_item["dimension"] in {"角色/用户", "状态/流程", "规则/约束", "隐性需求/界面状态"}:
            append_point(
                {
                    "id": f"TP{index:03d}-C",
                    "scope_item_id": scope_item["id"],
                    "title": f"{base_title}在失败、无权限、超时或异常场景下的反馈与兜底",
                    "type": "exception",
                    "category": "exception",
                    "module": module,
                    "role": role,
                    "page_or_entry": entry,
                    "preconditions": ["准备失败或拦截触发条件"],
                    "action": f"模拟{base_title}异常链路",
                    "verification_focus": ["失败提示明确", "兜底逻辑正确", "日志或记录可追踪"],
                    "user_scenario": False,
                    "user_scenario_tag": "",
                    "priority": "P0",
                    "source_refs": base_source,
                }
            )

        append_point(
            {
                "id": f"TP{index:03d}-U",
                "scope_item_id": scope_item["id"],
                "title": f"{base_title}需补充真实用户场景下的连续操作与中断恢复验证",
                "type": "user_scene",
                "category": "functional",
                "module": module,
                "role": role,
                "page_or_entry": entry,
                "preconditions": ["模拟真实用户连续点击、返回或刷新行为"],
                "action": f"围绕{base_title}执行真实用户操作路径",
                "verification_focus": ["重复请求结果一致", "返回后状态可恢复", "页面提示与数据一致"],
                "user_scenario": True,
                "user_scenario_tag": _scenario_tag_for_type("state" if scope_item["dimension"] == "状态/流程" else "normal"),
                "priority": priority,
                "source_refs": ["真实用户场景", *base_source][:4],
            }
        )

    return _merge_similar_test_points(test_points)


def _build_terms(content: str) -> list[dict[str, Any]]:
    terms: list[dict[str, Any]] = []
    seen: set[str] = set()
    candidate_terms = ("审核", "审批", "提交", "保存", "回流", "白名单", "标签", "配置", "状态", "权限")
    for term in candidate_terms:
        if term in content and term not in seen:
            terms.append(
                {
                    "term": term,
                    "meaning": f"本需求中涉及“{term}”相关规则，建议在评审时统一定义口径。",
                    "source_refs": [f"需求原文：{term}"],
                }
            )
            seen.add(term)
    return terms[:8]


def _build_traceability(scope_items: list[dict[str, Any]], test_points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    trace_rows: list[dict[str, Any]] = []
    points_by_scope: dict[str, list[str]] = {}
    for point in test_points:
        points_by_scope.setdefault(point["scope_item_id"], [])
        points_by_scope[point["scope_item_id"]].append(point["id"])
    for scope_item in scope_items:
        trace_rows.append(
            {
                "scope_item_id": scope_item["id"],
                "test_point_ids": points_by_scope.get(scope_item["id"], []),
                "source_refs": scope_item["source_refs"],
            }
        )
    return trace_rows


def _coverage_status(condition: bool, *, partial_condition: bool = False) -> str:
    if condition:
        return "covered"
    if partial_condition:
        return "partial"
    return "missing"


def _build_coverage_check(content: str, rule_units: list[dict[str, Any]], scope_items: list[dict[str, Any]]) -> dict[str, str]:
    dimensions = {item["dimension"] for item in scope_items}
    text = content or ""
    return {
        "roles": _coverage_status("角色/用户" in dimensions or any(unit["actor"] for unit in rule_units)),
        "pages_entries": _coverage_status("页面/入口" in dimensions, partial_condition="页面" in text or "入口" in text),
        "actions": _coverage_status("操作/动作" in dimensions, partial_condition=bool(rule_units)),
        "data_fields": _coverage_status("接口/数据" in dimensions, partial_condition=_contains_keyword(text, DATA_KEYWORDS)),
        "states_flows": _coverage_status("状态/流程" in dimensions, partial_condition=_contains_keyword(text, STATE_KEYWORDS)),
        "rules_constraints": _coverage_status("规则/约束" in dimensions, partial_condition=_contains_keyword(text, CONFIG_KEYWORDS + PERMISSION_KEYWORDS)),
        "non_functional": _coverage_status(False, partial_condition=_contains_keyword(text, ("性能", "兼容", "安全", "易用"))),
        "dependencies": _coverage_status(False, partial_condition=_contains_keyword(text, ("依赖", "回流", "同步", "外部"))),
        "implicit_states": _coverage_status("隐性需求/界面状态" in dimensions, partial_condition=_contains_keyword(text, ("空态", "加载", "错误", "无权限", "默认"))),
    }


def _build_consistency_check(
    content: str,
    scope_items: list[dict[str, Any]],
    test_points: list[dict[str, Any]],
) -> dict[str, Any]:
    missing_source = any(not item.get("source_refs") for item in [*scope_items, *test_points])
    fuzzy_hits = [term for term in FUZZY_TERMS if term in content]
    ambiguous_terms = [item["term"] for item in _build_terms(content) if item["term"] in {"审核", "审批", "提交", "保存"}]
    my_understanding = [
        f"我的理解是：{scope_item['name']}需要在{scope_item['page_or_entry']}下由{scope_item['role']}完成，并校验{scope_item['rule_summary']}"
        for scope_item in scope_items[:3]
    ]
    return {
        "anchoring_status": "partial" if missing_source else "anchored",
        "ambiguous_terms": ambiguous_terms[:6],
        "fuzzy_phrases": fuzzy_hits[:6],
        "my_understanding": my_understanding[:4],
    }


def _count_generic_statements(test_points: list[dict[str, Any]]) -> int:
    generic_phrases = ("验证功能", "校验页面反馈", "结果符合需求预期", "观察页面反馈")
    count = 0
    for point in test_points:
        title = point.get("title", "")
        action = point.get("action", "")
        if any(phrase in title or phrase in action for phrase in generic_phrases):
            count += 1
    return count


def _build_quality_report(
    scope_items: list[dict[str, Any]],
    test_points: list[dict[str, Any]],
    gaps: list[str],
    consistency_check: dict[str, Any],
) -> dict[str, Any]:
    missing_source_count = sum(1 for item in [*scope_items, *test_points] if not item.get("source_refs"))
    generic_statement_count = _count_generic_statements(test_points)
    score = 100
    score -= min(len(gaps), 4) * 5
    score -= missing_source_count * 10
    score -= generic_statement_count * 8
    if consistency_check.get("anchoring_status") != "anchored":
        score -= 8
    return {
        "score": max(score, 0),
        "missing_source_count": missing_source_count,
        "generic_statement_count": generic_statement_count,
        "needs_review": bool(gaps or missing_source_count or generic_statement_count),
    }


def _selected_points_from_test_points(test_points: list[dict[str, Any]], *, title: str = "") -> list[dict[str, str]]:
    points: list[dict[str, str]] = []
    fallback_module = _clean_text(title) or "默认模块"
    for point in test_points:
        category = point.get("category")
        if category not in CATEGORY_LABELS:
            category = "functional"
        points.append(
            {
                "title": _normalize_point(str(point.get("title", ""))),
                "category": category,
                "module": _clean_text(str(point.get("module") or fallback_module)) or fallback_module,
                "context": _clean_text(str(point.get("page_or_entry") or "需求原文")) or "需求原文",
                "requirement_source": "；".join(_normalize_source_refs(point.get("source_refs"))[:2]),
            }
        )
    return _normalize_selected_points(points, title=title)


def _core_rule_text(unit: dict[str, Any]) -> str:
    actor_text = unit["actor"] if unit["actor"] and unit["actor"] != "系统" else "用户/系统"
    condition_text = f"在{unit['condition']}下" if unit["condition"] else ""
    expectation_items = _rule_expectations(unit)[:3]
    expectation_text = "、".join(expectation_items) if expectation_items else "待确认"
    return _clean_text(f"{actor_text}{condition_text}执行{_rule_label(unit)}时，需保证{expectation_text}")


def _append_selected_point(
    points: list[dict[str, str]],
    seen_titles: set[str],
    *,
    unit: dict[str, Any],
    category: str,
    title: str,
) -> None:
    title_text = _normalize_point(title)
    if not title_text or title_text in seen_titles:
        return

    points.append(
        {
            "title": title_text,
            "category": category if category in CATEGORY_LABELS else "functional",
            "module": unit["module"],
            "context": _rule_context(unit),
            "requirement_source": unit["source"],
        }
    )
    seen_titles.add(title_text)


def _candidate_points_for_rule(unit: dict[str, Any]) -> list[tuple[str, str]]:
    base = _rule_label(unit)
    candidates: list[tuple[str, str]] = [
        (
            "functional",
            f"{base}主流程是否正确，并校验页面反馈、状态流转和结果数据",
        )
    ]

    if unit["has_boundary"] or unit["has_config"] or unit["has_state"]:
        candidates.append(
            (
                "boundary",
                f"{base}在边界值、空值、上限下限或配置临界场景下的处理",
            )
        )

    if unit["has_exception"] or unit["has_permission"]:
        candidates.append(
            (
                "exception",
                f"{base}在失败、无权限、超时或异常场景下的反馈与兜底",
            )
        )

    return candidates


def _build_selected_points(rule_units: list[dict[str, Any]], title: str = "") -> list[dict[str, str]]:
    selected_points: list[dict[str, str]] = []
    seen_titles: set[str] = set()

    for unit in rule_units:
        for category, point_title in _candidate_points_for_rule(unit):
            _append_selected_point(
                selected_points,
                seen_titles,
                unit=unit,
                category=category,
                title=point_title,
            )

    if not any(point["category"] == "boundary" for point in selected_points):
        for unit in rule_units[:2]:
            _append_selected_point(
                selected_points,
                seen_titles,
                unit=unit,
                category="boundary",
                title=f"{_rule_label(unit)}在边界值、空值或临界状态下的处理",
            )

    if not any(point["category"] == "exception" for point in selected_points):
        for unit in rule_units[:2]:
            _append_selected_point(
                selected_points,
                seen_titles,
                unit=unit,
                category="exception",
                title=f"{_rule_label(unit)}在失败、拦截或异常场景下的反馈与兜底",
            )

    fallback_module = _clean_text(title) or "默认模块"
    for point in selected_points:
        point["module"] = _clean_text(point["module"]) or fallback_module
        point["context"] = _clean_text(point["context"]) or "需求原文"
        point["requirement_source"] = _clean_text(point["requirement_source"]) or point["title"]

    return selected_points[:20]


def _pick_core_rules(rule_units: list[dict[str, Any]]) -> list[str]:
    if not rule_units:
        return []
    return _dedupe([_core_rule_text(unit) for unit in rule_units[:6]])[:6]


def _build_requirement_gaps(content: str, rule_units: list[dict[str, Any]]) -> list[str]:
    text = content or ""
    gaps: list[str] = []

    has_actor = any(unit["actor"] in BUSINESS_ACTOR_HINTS for unit in rule_units) or _contains_keyword(text, BUSINESS_ACTOR_HINTS)
    has_condition = any(unit["condition"] for unit in rule_units)
    has_feedback = any(unit["has_result"] or unit["has_state"] for unit in rule_units)
    has_boundary = any(unit["has_boundary"] for unit in rule_units)
    has_exception = any(unit["has_exception"] or unit["has_permission"] for unit in rule_units)
    has_data = any(unit["has_data"] for unit in rule_units)

    if not has_actor:
        gaps.append("需求未明确适用角色或对象范围，建议补充不同角色的可见性、可操作性和权限差异。")
    if not has_condition:
        gaps.append("需求未明确前置条件或触发条件，建议补充入口、依赖数据、命中条件和生效时机。")
    if not has_feedback:
        gaps.append("需求未明确页面反馈、状态变化或结果口径，验收标准仍不完整。")
    if not has_boundary:
        gaps.append("需求未明确上限、下限、空值、临界值或配置切换等边界规则。")
    if not has_exception:
        gaps.append("需求未明确失败、拦截、无权限、超时或兜底场景的处理方式。")
    if _contains_keyword(text, CRITICAL_RULE_KEYWORDS) and not has_data:
        gaps.append("涉及配置、权限、支付或状态流转，但未明确记录留痕、结果回流或数据一致性校验口径。")

    if not gaps and rule_units:
        gaps.append("当前需求主体较完整，但仍建议补充更细的边界、异常、幂等和数据一致性约束。")

    return gaps[:4]


def _build_test_standards(content: str, rule_units: list[dict[str, Any]]) -> list[str]:
    standards = [
        "每条核心规则至少覆盖前置条件、触发动作、页面反馈、状态流转和结果数据五个层面的校验。",
        "所有关键链路需同时覆盖正常流程、边界条件和异常场景，避免只验证正向路径。",
    ]

    if any(unit["has_config"] for unit in rule_units):
        standards.append("配置类需求必须校验命中、未命中、切换前后和生效时机四类样本。")
    if any(unit["has_permission"] for unit in rule_units):
        standards.append("权限类需求必须验证不同角色的可见范围、可操作范围和拦截反馈。")
    if any(unit["has_state"] for unit in rule_units):
        standards.append("涉及状态流转的场景必须验证初始状态、目标状态、逆向流转限制和重复触发结果。")
    if any(unit["has_data"] for unit in rule_units) or _contains_keyword(content, CRITICAL_RULE_KEYWORDS):
        standards.append("涉及业务结果记录的场景必须校验页面结果、落库记录、日志埋点和回流结果一致性。")
    if any(unit["has_exception"] for unit in rule_units):
        standards.append("异常链路需验证失败提示、兜底策略、日志留痕和是否可恢复。")

    return _dedupe(standards)[:5]


def _build_summary(rule_units: list[dict[str, Any]], gaps: list[str]) -> dict[str, list[str]]:
    system_flow = _dedupe(
        [
            f"{_rule_context(unit)}：{_rule_label(unit)}" if _rule_context(unit) != "需求原文" else _rule_label(unit)
            for unit in rule_units[:4]
        ]
    )[:4]

    core_rules = _pick_core_rules(rule_units)

    main_risks = _dedupe(
        [
            *gaps,
            *[
                f"{CATEGORY_LABELS[unit['category']]}高风险：{_rule_label(unit)}"
                for unit in rule_units
                if unit["category"] in {"boundary", "exception"}
            ],
        ]
    )[:4]

    test_focus = _dedupe(
        [
            "优先从角色、前置条件、触发动作、页面反馈、状态流转、数据结果六个维度确认验收口径。",
            "优先验证配置命中、权限控制、状态变更、异常兜底和结果回流是否闭环。",
            *[f"重点验证：{_rule_label(unit)}" for unit in rule_units[:4]],
        ]
    )[:5]

    return {
        "system_flow": system_flow or ["请根据需求补充完整系统流程。"],
        "core_rules": core_rules or ["请补充当前需求的关键业务规则。"],
        "main_risks": main_risks or ["请补充当前需求的主要风险点。"],
        "test_focus": test_focus or ["请补充当前需求的测试重点。"],
    }


def _empty_analysis_payload() -> dict[str, Any]:
    return {
        "meta": {
            "analysis_version": "v2",
            "input_type": "markdown",
            "used_llm": False,
            "source_title": "",
        },
        "summary": {
            "system_flow": [],
            "core_rules": [],
            "main_risks": [],
            "test_focus": [],
        },
        "gaps": [],
        "test_standards": [],
        "terms": [],
        "scope_items": [],
        "test_points": [],
        "selected_points": [],
        "traceability": [],
        "coverage_check": {
            "roles": "missing",
            "pages_entries": "missing",
            "actions": "missing",
            "data_fields": "missing",
            "states_flows": "missing",
            "rules_constraints": "missing",
            "non_functional": "missing",
            "dependencies": "missing",
            "implicit_states": "missing",
        },
        "consistency_check": {
            "anchoring_status": "partial",
            "ambiguous_terms": [],
            "fuzzy_phrases": [],
            "my_understanding": [],
        },
        "quality_report": {
            "score": 0,
            "missing_source_count": 0,
            "generic_statement_count": 0,
            "needs_review": True,
        },
        "review": {
            "custom_points": [],
            "core_regression_points": [],
        },
    }


def _normalize_string_list(value: Any, *, limit: int | None = None) -> list[str]:
    if not isinstance(value, list):
        return []
    items = _dedupe([str(item) for item in value if isinstance(item, str) and _clean_text(item)])
    if limit is not None:
        return items[:limit]
    return items


def _normalize_selected_points(points: Any, *, title: str = "") -> list[dict[str, str]]:
    if not isinstance(points, list):
        return []

    normalized_points: list[dict[str, str]] = []
    seen_titles: set[str] = set()
    fallback_module = _clean_text(title) or "默认模块"

    for point in points:
        if not isinstance(point, dict):
            continue

        title_text = _normalize_point(str(point.get("title", "")))
        if not title_text or title_text in seen_titles:
            continue

        category = str(point.get("category") or "functional").strip().lower()
        if category not in CATEGORY_LABELS:
            category = "functional"

        module = _clean_text(str(point.get("module") or fallback_module)) or fallback_module
        context = _clean_text(str(point.get("context") or "需求原文")) or "需求原文"
        requirement_source = _clean_text(str(point.get("requirement_source") or title_text)) or title_text

        normalized_points.append(
            {
                "title": title_text,
                "category": category,
                "module": module,
                "context": context,
                "requirement_source": requirement_source,
            }
        )
        seen_titles.add(title_text)

    return normalized_points[:20]


def _normalize_terms(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in value:
        if not isinstance(row, dict):
            continue
        term = _clean_text(str(row.get("term", "")))
        meaning = _clean_text(str(row.get("meaning", "")))
        if not term or not meaning or term in seen:
            continue
        rows.append({"term": term, "meaning": meaning, "source_refs": _normalize_source_refs(row.get("source_refs"))})
        seen.add(term)
    return rows[:12]


def _normalize_scope_items(value: Any, *, title: str = "") -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    fallback_module = _clean_text(title) or "默认模块"
    for index, row in enumerate(value, start=1):
        if not isinstance(row, dict):
            continue
        item_id = _clean_text(str(row.get("id") or f"S{index:03d}"))
        name = _clean_text(str(row.get("name", "")))
        if not name or item_id in seen:
            continue
        dimension = _clean_text(str(row.get("dimension", ""))) or "操作/动作"
        if dimension not in ANALYSIS_DIMENSIONS:
            dimension = "操作/动作"
        rows.append(
            {
                "id": item_id,
                "name": name,
                "dimension": dimension,
                "module": _clean_text(str(row.get("module") or fallback_module)) or fallback_module,
                "role": _clean_text(str(row.get("role") or "未说明")) or "未说明",
                "page_or_entry": _clean_text(str(row.get("page_or_entry") or "需求原文")) or "需求原文",
                "object": _clean_text(str(row.get("object") or name)) or name,
                "rule_summary": _clean_text(str(row.get("rule_summary") or name)) or name,
                "priority": _clean_text(str(row.get("priority") or "P2")) or "P2",
                "testable": bool(row.get("testable", True)),
                "source_refs": _normalize_source_refs(row.get("source_refs")),
                "notes": _clean_text(str(row.get("notes") or "")),
            }
        )
        seen.add(item_id)
    return rows[:30]


def _normalize_test_points(value: Any, *, title: str = "") -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    fallback_module = _clean_text(title) or "默认模块"
    for index, row in enumerate(value, start=1):
        if not isinstance(row, dict):
            continue
        point_id = _clean_text(str(row.get("id") or f"TP{index:03d}"))
        title_text = _normalize_point(str(row.get("title", "")))
        if not point_id or not title_text or point_id in seen:
            continue
        category = _clean_text(str(row.get("category") or "functional")).lower() or "functional"
        if category not in CATEGORY_LABELS:
            category = "functional"
        rows.append(
            {
                "id": point_id,
                "scope_item_id": _clean_text(str(row.get("scope_item_id") or "")),
                "title": title_text,
                "type": _clean_text(str(row.get("type") or "normal")) or "normal",
                "category": category,
                "module": _clean_text(str(row.get("module") or fallback_module)) or fallback_module,
                "role": _clean_text(str(row.get("role") or "未说明")) or "未说明",
                "page_or_entry": _clean_text(str(row.get("page_or_entry") or "需求原文")) or "需求原文",
                "preconditions": _normalize_string_list(row.get("preconditions"), limit=5),
                "action": _clean_text(str(row.get("action") or title_text)) or title_text,
                "verification_focus": _normalize_string_list(row.get("verification_focus"), limit=6),
                "user_scenario": bool(row.get("user_scenario")),
                "user_scenario_tag": _clean_text(str(row.get("user_scenario_tag") or "")),
                "priority": _clean_text(str(row.get("priority") or "P2")) or "P2",
                "source_refs": _normalize_source_refs(row.get("source_refs")),
            }
        )
        seen.add(point_id)
    return _merge_similar_test_points(rows)[:40]


def _normalize_traceability(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for row in value:
        if not isinstance(row, dict):
            continue
        scope_item_id = _clean_text(str(row.get("scope_item_id", "")))
        if not scope_item_id:
            continue
        point_ids = _normalize_string_list(row.get("test_point_ids"), limit=12)
        rows.append(
            {
                "scope_item_id": scope_item_id,
                "test_point_ids": point_ids,
                "source_refs": _normalize_source_refs(row.get("source_refs")),
            }
        )
    return rows[:30]


def _normalize_coverage_check(value: Any) -> dict[str, str]:
    default = _empty_analysis_payload()["coverage_check"]
    if not isinstance(value, dict):
        return default
    normalized = {}
    for key, default_value in default.items():
        status = _clean_text(str(value.get(key) or default_value)).lower()
        normalized[key] = status if status in {"covered", "partial", "missing"} else default_value
    return normalized


def _normalize_consistency_check(value: Any) -> dict[str, Any]:
    default = _empty_analysis_payload()["consistency_check"]
    if not isinstance(value, dict):
        return default
    anchoring_status = _clean_text(str(value.get("anchoring_status") or default["anchoring_status"])).lower()
    if anchoring_status not in {"anchored", "partial"}:
        anchoring_status = "partial"
    return {
        "anchoring_status": anchoring_status,
        "ambiguous_terms": _normalize_string_list(value.get("ambiguous_terms"), limit=8),
        "fuzzy_phrases": _normalize_string_list(value.get("fuzzy_phrases"), limit=8),
        "my_understanding": _normalize_string_list(value.get("my_understanding"), limit=5),
    }


def _normalize_quality_report(value: Any) -> dict[str, Any]:
    default = _empty_analysis_payload()["quality_report"]
    if not isinstance(value, dict):
        return default
    score = value.get("score", default["score"])
    try:
        score_value = max(0, min(int(score), 100))
    except (TypeError, ValueError):
        score_value = default["score"]
    return {
        "score": score_value,
        "missing_source_count": max(0, int(value.get("missing_source_count", 0) or 0)),
        "generic_statement_count": max(0, int(value.get("generic_statement_count", 0) or 0)),
        "needs_review": bool(value.get("needs_review", default["needs_review"])),
    }


def _normalize_analysis_payload(payload: Any, *, title: str = "") -> dict[str, Any]:
    empty = _empty_analysis_payload()
    if not isinstance(payload, dict):
        return empty

    raw_summary = payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
    raw_review = payload.get("review", {}) if isinstance(payload.get("review"), dict) else {}
    terms = _normalize_terms(payload.get("terms"))
    scope_items = _normalize_scope_items(payload.get("scope_items"), title=title)
    test_points = _normalize_test_points(payload.get("test_points"), title=title)
    selected_points = _normalize_selected_points(payload.get("selected_points"), title=title)
    if not selected_points and test_points:
        selected_points = _selected_points_from_test_points(test_points, title=title)

    return {
        "meta": {
            "analysis_version": _clean_text(str((payload.get("meta") or {}).get("analysis_version") if isinstance(payload.get("meta"), dict) else "")) or "v2",
            "input_type": _clean_text(str((payload.get("meta") or {}).get("input_type") if isinstance(payload.get("meta"), dict) else "")) or "markdown",
            "used_llm": bool((payload.get("meta") or {}).get("used_llm")) if isinstance(payload.get("meta"), dict) else False,
            "source_title": _clean_text(str((payload.get("meta") or {}).get("source_title") if isinstance(payload.get("meta"), dict) else title)) or title,
        },
        "summary": {
            "system_flow": _normalize_string_list(raw_summary.get("system_flow"), limit=6),
            "core_rules": _normalize_string_list(raw_summary.get("core_rules"), limit=6),
            "main_risks": _normalize_string_list(raw_summary.get("main_risks"), limit=6),
            "test_focus": _normalize_string_list(raw_summary.get("test_focus"), limit=6),
        },
        "gaps": _normalize_string_list(payload.get("gaps"), limit=4),
        "test_standards": _normalize_string_list(payload.get("test_standards"), limit=5),
        "terms": terms,
        "scope_items": scope_items,
        "test_points": test_points,
        "selected_points": selected_points,
        "traceability": _normalize_traceability(payload.get("traceability")),
        "coverage_check": _normalize_coverage_check(payload.get("coverage_check")),
        "consistency_check": _normalize_consistency_check(payload.get("consistency_check")),
        "quality_report": _normalize_quality_report(payload.get("quality_report")),
        "review": {
            "custom_points": _normalize_string_list(raw_review.get("custom_points"), limit=20),
            "core_regression_points": _normalize_string_list(raw_review.get("core_regression_points"), limit=20),
        },
    }


def can_use_llm() -> bool:
    return openai_client is not None


def call_llm_for_analysis(content: str) -> dict[str, Any]:
    normalized = _clean_text(content)
    if not normalized:
        return _empty_analysis_payload()

    if not can_use_llm():
        raise RuntimeError("LLM client is not configured.")

    system_prompt = (
        "你是一名资深测试工程师和测试需求分析专家。"
        "请严格基于已提供的需求文档分析，不臆造业务逻辑。"
        "禁止发明输入中未出现的接口名、字段名、数据库表名、事件名、任务名、URL、Webhook、状态码或技术实现细节。"
        "如果输入没有明确给出这些信息，统一写“待确认”，不要凭经验补全。"
        "你必须按以下顺序完成分析："
        "1）按功能点穷尽清单逐项遍历角色/用户、页面/入口、操作/动作、接口/数据、状态/流程、规则/约束、非功能、关联/依赖、隐性需求/界面状态；"
        "2）补充真实用户使用场景，包括误操作、重复提交、中断恢复、弱网、输入粘贴、多端多态、用户差异；"
        "3）执行理解一致性检查，确保每个功能点和测试点都能回指原文来源，并列出术语、模糊表述和“我的理解是”。"
        "不要只做摘要提取，不要输出空洞表述。"
        "scope_items 和 test_points 必须具体、可测、可执行，并尽量带动作、对象、验证目标和 source_refs。"
        "category 只能是 functional、boundary、exception。"
        "review 字段固定返回空数组。"
        "输出必须通过函数调用提交，字段必须严格匹配给定 schema。"
    )
    user_prompt = (
        "请分析下面的需求文本，并输出结构化测试分析结果。\n\n"
        f"{content.strip()}"
    )

    response = openai_client.chat.completions.create(
        model=LLM_MODEL,
        temperature=0.2,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "submit_requirement_analysis",
                    "description": "提交与当前需求分析结构完全一致的 JSON 结果。",
                    "parameters": ANALYSIS_TOOL_SCHEMA,
                },
            }
        ],
        tool_choice={
            "type": "function",
            "function": {"name": "submit_requirement_analysis"},
        },
    )

    choice = response.choices[0]
    message = choice.message
    tool_calls = getattr(message, "tool_calls", None) or []
    if not tool_calls:
        raise RuntimeError("LLM did not return a function call.")

    arguments = tool_calls[0].function.arguments or "{}"
    try:
        return json.loads(arguments)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Failed to decode LLM function arguments as JSON.") from exc


def _build_requirement_analysis_by_rules(content: str, title: str = "") -> dict[str, Any]:
    normalized = _clean_text(content)
    if not normalized:
        return _empty_analysis_payload()

    rule_units = _extract_rule_units(content, title=title)
    special_items = _extract_special_requirement_items(content, title=title)
    structured_terms = _extract_structured_terms(content)
    structured_scope_items = _extract_structured_scope_items(content, title=title)
    structured_test_points = _extract_structured_test_points(content, title=title)
    structured_gaps = _extract_structured_gaps(content)

    scope_items = structured_scope_items or _build_scope_items(rule_units, title=title)
    test_points = structured_test_points or _build_test_points_from_scope_items(scope_items)
    gaps = structured_gaps or _build_requirement_gaps(content, rule_units)
    for item in special_items.get("known_issue", [])[:3]:
        gaps.append(f"已知问题：{item['sentence']}（{item['module']}）")
    for item in special_items.get("prelaunch_check", [])[:2]:
        gaps.append(f"上线检查项：{item['sentence']}（{item['module']}）")
    gaps = _dedupe(gaps)[:6]
    summary = _build_summary(rule_units, gaps)
    test_standards = _build_test_standards(content, rule_units)
    selected_points = _selected_points_from_test_points(test_points, title=title)
    consistency_check = _build_consistency_check(content, scope_items, test_points)
    quality_report = _build_quality_report(scope_items, test_points, gaps, consistency_check)

    return {
        "meta": {
            "analysis_version": "v2",
            "input_type": "markdown",
            "used_llm": False,
            "source_title": title,
        },
        "summary": summary,
        "gaps": gaps,
        "test_standards": test_standards,
        "terms": structured_terms or _build_terms(content),
        "scope_items": scope_items,
        "test_points": test_points,
        "selected_points": selected_points,
        "traceability": _build_traceability(scope_items, test_points),
        "coverage_check": _build_coverage_check(content, rule_units, scope_items),
        "consistency_check": consistency_check,
        "quality_report": quality_report,
        "review": {
            "custom_points": [],
            "core_regression_points": [],
        },
    }


def build_requirement_analysis(content: str, title: str = "", use_llm: bool = False) -> dict[str, Any]:
    content = _preprocess_requirement_content(content)
    if use_llm and can_use_llm():
        try:
            llm_payload = call_llm_for_analysis(content)
            if isinstance(llm_payload, dict):
                llm_payload.setdefault(
                    "meta",
                    {
                        "analysis_version": "v2",
                        "input_type": "markdown",
                        "used_llm": True,
                        "source_title": title,
                    },
                )
            normalized_payload = _normalize_analysis_payload(llm_payload, title=title)
            if normalized_payload.get("selected_points"):
                normalized_payload["meta"]["used_llm"] = True
                return normalized_payload
            logger.warning("LLM analysis returned empty selected_points, fallback to rules.")
        except Exception as exc:  # pragma: no cover
            logger.exception("LLM analysis failed, fallback to rules: %s", exc)

    return _build_requirement_analysis_by_rules(content, title=title)


def _markdown_cell(value: Any) -> str:
    text = _clean_text(str(value or ""))
    if not text:
        return "-"
    return text.replace("|", "\\|")


def _markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        normalized = [_markdown_cell(cell) for cell in row]
        lines.append("| " + " | ".join(normalized) + " |")
    return "\n".join(lines)


def _join_refs(value: Any, *, fallback: str = "需求原文") -> str:
    refs = _normalize_source_refs(value, limit=8)
    return "；".join(refs) or fallback


def _group_points_by_scope(test_points: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for point in test_points:
        grouped.setdefault(str(point.get("scope_item_id", "")), [])
        grouped[str(point.get("scope_item_id", ""))].append(point)
    return grouped


def render_requirement_analysis_markdown(payload: dict[str, Any], title: str = "") -> str:
    normalized_payload = _normalize_analysis_payload(payload, title=title)
    source_title = _clean_text(title) or _clean_text(normalized_payload.get("meta", {}).get("source_title")) or "未命名需求"
    terms = normalized_payload.get("terms", [])
    scope_items = normalized_payload.get("scope_items", [])
    test_points = normalized_payload.get("test_points", [])
    traceability = normalized_payload.get("traceability", [])
    coverage_check = normalized_payload.get("coverage_check", {})
    consistency_check = normalized_payload.get("consistency_check", {})
    gaps = _normalize_string_list(normalized_payload.get("gaps"), limit=10)

    points_by_scope = _group_points_by_scope(test_points)
    traceability_map = {
        str(row.get("scope_item_id", "")): _normalize_source_refs(row.get("source_refs"), limit=8)
        for row in traceability
        if isinstance(row, dict)
    }

    lines = [f"# 测试需求分析 - {source_title}", ""]

    lines.extend(["## 0. 术语与缩写", ""])
    if terms:
        term_rows = [
            [
                row.get("term", ""),
                row.get("meaning", ""),
                _join_refs(row.get("source_refs"), fallback="需求原文"),
            ]
            for row in terms
            if isinstance(row, dict)
        ]
        lines.append(_markdown_table(["术语", "本需求中的含义", "需求来源"], term_rows))
    else:
        lines.append("- 暂未识别需要统一口径的术语，建议评审时补充。")
    lines.append("")

    lines.extend(["## 1. 测试范围", ""])
    if scope_items:
        scope_rows = []
        for index, scope_item in enumerate(scope_items, start=1):
            if not isinstance(scope_item, dict):
                continue
            scope_rows.append(
                [
                    f"F-{index:02d}",
                    scope_item.get("name", ""),
                    _join_refs(scope_item.get("source_refs"), fallback="需求原文"),
                    scope_item.get("priority", "P2"),
                    "是" if bool(scope_item.get("testable", True)) else "否",
                    scope_item.get("notes", "") or scope_item.get("rule_summary", ""),
                ]
            )
        lines.append(_markdown_table(["序号", "功能点", "需求来源", "优先级", "可测性", "备注"], scope_rows))
    else:
        lines.append("- 暂无可落地的测试范围，请先补充原始需求。")
    lines.append("")

    lines.extend(["## 2. 测试点", "", "### 一、功能点穷尽清单（按维度遍历）", ""])
    for dimension in ANALYSIS_DIMENSIONS:
        dimension_rows = [
            scope_item
            for scope_item in scope_items
            if isinstance(scope_item, dict) and _clean_text(scope_item.get("dimension")) == dimension
        ]
        if not dimension_rows:
            continue
        lines.extend([f"#### {dimension}"])
        table_rows = []
        for scope_item in dimension_rows:
            scope_id = str(scope_item.get("id", ""))
            related_points = points_by_scope.get(scope_id, [])
            verification_parts = [
                scope_item.get("rule_summary", ""),
                f"入口：{scope_item.get('page_or_entry', '需求原文')}",
            ]
            if _clean_text(scope_item.get("role")):
                verification_parts.append(f"角色：{scope_item.get('role')}")
            user_scene_flag = "是" if any(bool(point.get("user_scenario")) for point in related_points) else "否"
            table_rows.append(
                [
                    scope_item.get("name", ""),
                    "；".join(_dedupe([_clean_text(part) for part in verification_parts if _clean_text(part)])),
                    _join_refs(traceability_map.get(scope_id) or scope_item.get("source_refs"), fallback="需求原文"),
                    user_scene_flag,
                ]
            )
        lines.append(_markdown_table(["功能点", "测试关注点", "对应需求", "真实用户场景"], table_rows))
        lines.append("")

    lines.extend(["### 一（补）、真实用户使用场景补充", ""])
    scene_rows: list[list[Any]] = []
    scene_order = {tag: index for index, tag in enumerate(REAL_USER_SCENE_TAGS)}
    user_scene_points = [
        point
        for point in test_points
        if isinstance(point, dict) and (bool(point.get("user_scenario")) or _clean_text(point.get("user_scenario_tag")))
    ]
    user_scene_points.sort(
        key=lambda point: (
            scene_order.get(_clean_text(point.get("user_scenario_tag")), 99),
            _clean_text(point.get("module")),
            _clean_text(point.get("title")),
        )
    )
    for point in user_scene_points:
        scene_rows.append(
            [
                _clean_text(point.get("user_scenario_tag")) or "真实用户场景",
                point.get("title", ""),
                point.get("module", "") or point.get("page_or_entry", "") or "需求原文",
                "是",
            ]
        )
    if scene_rows:
        lines.append(_markdown_table(["场景类型", "测试关注点", "对应功能", "真实用户场景"], scene_rows))
    else:
        lines.append("- 暂未识别真实用户场景，建议补充误操作、重复操作、中断恢复、弱网、输入粘贴、多端等场景。")
    lines.append("")

    lines.extend(["## 3. 需求疑义与遗漏", ""])
    pending_items: list[str] = []
    pending_items.extend(gaps)
    for term in _normalize_string_list(consistency_check.get("ambiguous_terms"), limit=6):
        pending_items.append(f"术语“{term}”当前口径不够明确，建议产品/研发统一定义。")
    for phrase in _normalize_string_list(consistency_check.get("fuzzy_phrases"), limit=6):
        pending_items.append(f"原文存在模糊表述“{phrase}”，建议补充明确规则、范围或阈值。")
    pending_items = _dedupe([item for item in pending_items if _clean_text(item)])
    if pending_items:
        for item in pending_items:
            lines.append(f"- [ ] {item}")
    else:
        lines.append("- [x] 暂未识别影响后续计划和用例设计的关键疑义。")
    lines.append("")

    lines.extend(["## 4. 需求追溯", ""])
    trace_rows: list[list[Any]] = []
    for scope_item in scope_items:
        if not isinstance(scope_item, dict):
            continue
        trace_rows.append(
            [
                scope_item.get("name", ""),
                _join_refs(traceability_map.get(str(scope_item.get("id", ""))) or scope_item.get("source_refs"), fallback="需求原文"),
            ]
        )
    if trace_rows:
        lines.append(_markdown_table(["功能点/测试点", "需求来源"], trace_rows))
    else:
        lines.append("- 暂无可追溯项。")
    lines.append("")

    lines.extend(["## 5. 自检", ""])
    coverage_items = [
        ("角色/用户", coverage_check.get("roles")),
        ("页面/入口", coverage_check.get("pages_entries")),
        ("操作/动作", coverage_check.get("actions")),
        ("接口/数据", coverage_check.get("data_fields")),
        ("状态/流程", coverage_check.get("states_flows")),
        ("规则/约束", coverage_check.get("rules_constraints")),
        ("非功能", coverage_check.get("non_functional")),
        ("关联/依赖", coverage_check.get("dependencies")),
        ("隐性需求/界面状态", coverage_check.get("implicit_states")),
    ]
    coverage_status_label = {
        "covered": "已覆盖",
        "partial": "部分覆盖",
        "missing": "未覆盖/未说明",
    }
    for label, status in coverage_items:
        checked = "x" if status == "covered" else " "
        status_text = coverage_status_label.get(_clean_text(status), "未覆盖/未说明")
        lines.append(f"- [{checked}] {label}：{status_text}")
    understanding_items = _normalize_string_list(consistency_check.get("my_understanding"), limit=4)
    for item in understanding_items:
        lines.append(f"- [x] 理解一致性检查：{item}")

    return "\n".join(lines).strip()


def analyze_requirement(content: str, title: str = "", use_llm: bool = False) -> list[str]:
    payload = build_requirement_analysis(content, title=title, use_llm=use_llm)
    return [point["title"] for point in payload.get("selected_points", []) if isinstance(point, dict)]