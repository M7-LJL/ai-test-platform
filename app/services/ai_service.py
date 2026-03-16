from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4").strip() or "gpt-4"
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OpenAI is not None and OPENAI_API_KEY else None

CATEGORY_LABELS = {
    "functional": "功能点",
    "boundary": "边界点",
    "exception": "异常点",
}

ANALYSIS_TOOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
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
    "required": ["summary", "gaps", "test_standards", "selected_points", "review"],
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


def _split_sentences(content: str) -> list[str]:
    raw_parts = re.split(r"[\r\n]+|(?<=[。！？!?；;])", content or "")
    sentences: list[str] = []
    for part in raw_parts:
        cleaned = re.sub(r"^\s*[-*0-9.)、#]+\s*", "", part).strip()
        cleaned = cleaned.strip("。！？!?；;")
        if len(cleaned) >= 4:
            sentences.append(cleaned)
    return sentences


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
    boundary_keywords = (
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
    )
    exception_keywords = (
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

    if any(keyword in sentence for keyword in exception_keywords):
        return "exception"
    if any(keyword in sentence for keyword in boundary_keywords):
        return "boundary"
    return "functional"


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
        items.append(
            {
                "module": current_module,
                "context": current_context_text(),
                "sentence": cleaned,
                "category": _classify_point(cleaned),
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
        }
        for sentence in _split_sentences(content)
    ]


def _pick_core_rules(items: list[dict[str, str]]) -> list[str]:
    keywords = ("必须", "需要", "应", "开关", "配置", "白名单", "标签", "比例", "审批", "支付", "状态")
    matched = [item["sentence"] for item in items if any(keyword in item["sentence"] for keyword in keywords)]
    if matched:
        return _dedupe(matched)[:6]
    return _dedupe([item["sentence"] for item in items[:4]])


def _build_requirement_gaps(content: str, items: list[dict[str, str]]) -> list[str]:
    text = content or ""
    gaps: list[str] = []

    if not any(keyword in text for keyword in ("角色", "权限", "用户", "管理员", "运营")):
        gaps.append("需求中未明确不同角色的可见范围和操作权限，容易漏测权限差异。")
    if not any(keyword in text for keyword in ("成功", "失败", "状态", "结果", "提示")):
        gaps.append("需求未明确成功/失败后的页面反馈与状态流转，验收口径不够完整。")
    if not any(keyword in text for keyword in ("最大", "最小", "上限", "下限", "边界", "次数", "比例", "为空")):
        gaps.append("需求未明确关键边界条件，后续需要补充上限、下限、空值和临界值规则。")
    if not any(keyword in text for keyword in ("异常", "失败", "超时", "兜底", "拦截", "降级")):
        gaps.append("需求未说明异常链路处理方式，建议补充失败、超时和兜底策略。")
    if any(keyword in text for keyword in ("支付", "红包", "优惠券", "广告", "配置")) and not any(
        keyword in text for keyword in ("回流", "记录", "日志", "埋点", "同步")
    ):
        gaps.append("涉及业务结果回流或配置命中，但未明确记录口径与回流结果，容易出现数据校验遗漏。")

    if not gaps and items:
        gaps.append("当前需求主体较完整，但仍建议补充更细的边界、异常和数据一致性约束。")
    return gaps[:4]


def _build_test_standards(content: str, items: list[dict[str, str]]) -> list[str]:
    standards = [
        "每条核心规则至少覆盖页面表现、状态流转和结果数据三个层面的校验。",
        "所有关键链路需同时覆盖正常流程、边界条件和异常场景。",
    ]
    if any(keyword in content for keyword in ("配置", "开关", "白名单", "标签", "比例")):
        standards.append("配置类需求必须校验命中与未命中两类样本，并确认配置生效时机。")
    if any(keyword in content for keyword in ("支付", "红包", "优惠券", "广告")):
        standards.append("资金、激励和广告类需求必须校验业务结果、回流记录与最终状态一致性。")
    if any(item["category"] == "boundary" for item in items):
        standards.append("涉及阈值的场景需覆盖边界前、边界值、边界后的连续验证。")
    return _dedupe(standards)[:5]


def _build_summary(items: list[dict[str, str]], gaps: list[str]) -> dict[str, list[str]]:
    system_flow = _dedupe([item["sentence"] for item in items[:4]])
    core_rules = _pick_core_rules(items)

    main_risks = _dedupe(
        [
            *gaps,
            *[
                f"{CATEGORY_LABELS[item['category']]}覆盖不足：{item['sentence']}"
                for item in items
                if item["category"] in {"boundary", "exception"}
            ],
        ]
    )[:4]

    test_focus = _dedupe(
        [
            "优先确认主流程是否闭环，包括入口、关键动作和最终结果。",
            "优先确认配置、权限、状态流转和数据一致性是否满足验收标准。",
            *[
                f"重点关注{CATEGORY_LABELS[item['category']]}：{item['sentence']}"
                for item in items[:6]
            ],
        ]
    )[:5]

    return {
        "system_flow": system_flow or ["请根据需求补充完整系统流程。"],
        "core_rules": core_rules or ["请补充需求中的关键业务规则。"],
        "main_risks": main_risks or ["请补充当前需求的主要风险点。"],
        "test_focus": test_focus or ["请补充当前需求的测试重点。"],
    }


def _empty_analysis_payload() -> dict[str, Any]:
    return {
        "summary": {
            "system_flow": [],
            "core_rules": [],
            "main_risks": [],
            "test_focus": [],
        },
        "gaps": [],
        "test_standards": [],
        "selected_points": [],
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


def _normalize_analysis_payload(payload: Any, *, title: str = "") -> dict[str, Any]:
    empty = _empty_analysis_payload()
    if not isinstance(payload, dict):
        return empty

    raw_summary = payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
    raw_review = payload.get("review", {}) if isinstance(payload.get("review"), dict) else {}

    return {
        "summary": {
            "system_flow": _normalize_string_list(raw_summary.get("system_flow"), limit=6),
            "core_rules": _normalize_string_list(raw_summary.get("core_rules"), limit=6),
            "main_risks": _normalize_string_list(raw_summary.get("main_risks"), limit=6),
            "test_focus": _normalize_string_list(raw_summary.get("test_focus"), limit=6),
        },
        "gaps": _normalize_string_list(payload.get("gaps"), limit=4),
        "test_standards": _normalize_string_list(payload.get("test_standards"), limit=5),
        "selected_points": _normalize_selected_points(payload.get("selected_points"), title=title),
        "review": {
            "custom_points": _normalize_string_list(raw_review.get("custom_points"), limit=20),
            "core_regression_points": _normalize_string_list(raw_review.get("core_regression_points"), limit=20),
        },
    }


def _can_use_llm() -> bool:
    return openai_client is not None


def call_llm_for_analysis(content: str) -> dict[str, Any]:
    normalized = _clean_text(content)
    if not normalized:
        return _empty_analysis_payload()

    if not _can_use_llm():
        raise RuntimeError("OpenAI client is not configured.")

    system_prompt = (
        "你是一名资深测试工程师和测试分析专家。"
        "请对输入的需求进行结构化分析，识别需求漏洞、关键规则、测试标准，并生成按功能点、边界点、异常点分类的测试点。"
        "输出必须通过函数调用提交，字段必须严格匹配给定 schema。"
        "selected_points 中每个测试点都要具体、可测、可执行，标题要简洁。"
        "category 只能是 functional、boundary、exception。"
        "review 字段固定返回空数组，不要自行填充人工评审内容。"
    )
    user_prompt = (
        "请分析下面的需求文本，并输出结构化测试分析结果。\n\n"
        f"{content.strip()}"
    )

    response = openai_client.chat.completions.create(
        model=OPENAI_MODEL,
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

    items = _extract_requirement_items(content, title=title)
    gaps = _build_requirement_gaps(content, items)
    summary = _build_summary(items, gaps)
    test_standards = _build_test_standards(content, items)

    selected_points: list[dict[str, str]] = []
    seen_titles: set[str] = set()
    for item in items:
        title_text = _normalize_point(item["sentence"])
        if not title_text or title_text in seen_titles:
            continue
        seen_titles.add(title_text)
        selected_points.append(
            {
                "title": title_text,
                "category": item["category"],
                "module": item["module"] or _clean_text(title) or "默认模块",
                "context": item["context"] or "需求原文",
                "requirement_source": item["sentence"],
            }
        )

    return {
        "summary": summary,
        "gaps": gaps,
        "test_standards": test_standards,
        "selected_points": selected_points[:20],
        "review": {
            "custom_points": [],
            "core_regression_points": [],
        },
    }


def build_requirement_analysis(content: str, title: str = "", use_llm: bool = False) -> dict[str, Any]:
    if use_llm and _can_use_llm():
        try:
            llm_payload = call_llm_for_analysis(content)
            normalized_payload = _normalize_analysis_payload(llm_payload, title=title)
            if normalized_payload.get("selected_points"):
                return normalized_payload
            logger.warning("LLM analysis returned empty selected_points, fallback to rules.")
        except Exception as exc:  # pragma: no cover
            logger.exception("LLM analysis failed, fallback to rules: %s", exc)

    return _build_requirement_analysis_by_rules(content, title=title)


def analyze_requirement(content: str, title: str = "", use_llm: bool = False) -> list[str]:
    payload = build_requirement_analysis(content, title=title, use_llm=use_llm)
    return [point["title"] for point in payload.get("selected_points", []) if isinstance(point, dict)]