from __future__ import annotations

import re
from uuid import uuid4


CASE_TYPES = ("正常流程", "边界条件", "异常场景")
CASE_TYPE_PRIORITY = {
    "正常流程": "P2",
    "边界条件": "P2",
    "异常场景": "P1",
}
DESIGN_SECTION_TITLES = {"需求概览", "业务拆解", "推荐测试点"}
CASE_VARIANTS = {
    "正常流程": (
        "核心主流程成功",
        "从不同入口触发",
        "连续执行稳定性",
        "返回后再次进入",
        "不同账号或门店条件",
        "结果页回查校验",
        "配置生效验证",
        "跨页面跳转一致性",
    ),
    "边界条件": (
        "最小值边界",
        "最大值边界",
        "临界值前一位",
        "临界值后一位",
        "默认值场景",
        "空值场景",
        "极端组合场景",
        "单项开关边界",
    ),
    "异常场景": (
        "配置缺失场景",
        "配置非法场景",
        "上游依赖失败",
        "接口超时重试",
        "权限或白名单拦截",
        "数据不存在场景",
        "重复操作冲突",
        "降级兜底路径",
    ),
}


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip(" \t\r\n-—:：。；;，,")


def _normalize_point(sentence: str) -> str:
    sentence = _clean_text(sentence)
    sentence = re.sub(r"^(用户|系统|页面|应用|平台)", "", sentence).strip()
    sentence = re.sub(r"^(需要|应当|应该|可以|能够|支持|实现|提供|具备)", "", sentence).strip()
    if not sentence:
        return ""
    if sentence.startswith("验证"):
        return sentence
    return f"验证{sentence}"


def _split_sentences(content: str) -> list[str]:
    raw_parts = re.split(r"[\r\n]+|(?<=[。！？!?；;])", content)
    sentences: list[str] = []
    for part in raw_parts:
        cleaned = re.sub(r"^\s*[-*0-9.)、#]+\s*", "", part).strip()
        cleaned = cleaned.strip("。！？!?；;")
        if len(cleaned) >= 4:
            sentences.append(cleaned)
    return sentences


def _infer_priority_from_title(point_title: str) -> str:
    high_priority_keywords = ("支付", "登录", "下单", "权限", "跳转", "红包", "广告")
    if any(keyword in point_title for keyword in high_priority_keywords):
        return "P1"
    return "P2"


def _classify_case_type(sentence: str) -> str:
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
        "100/0",
        "0/100",
    )
    exception_keywords = (
        "错误",
        "失败",
        "异常",
        "白名单",
        "屏蔽",
        "禁止",
        "无权限",
        "不存在",
        "超时",
        "中断",
        "不可用",
        "驳回",
        "降级",
        "拦截",
        "不应",
    )

    if any(keyword in sentence for keyword in exception_keywords):
        return "异常场景"
    if any(keyword in sentence for keyword in boundary_keywords):
        return "边界条件"
    return "正常流程"


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


def _extract_requirement_items(requirement_title: str, content: str) -> list[dict[str, str]]:
    lines = [line.rstrip() for line in content.splitlines()]
    heading_info = [_heading_level(line) for line in lines]
    heading_levels = [level for info in heading_info if info for level, _ in [info]]
    module_heading_level = min(heading_levels) if heading_levels else None

    current_module = _clean_text(requirement_title) or "默认模块"
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
                "case_type": _classify_case_type(cleaned),
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

    fallback_sentences = _split_sentences(content)
    return [
        {
            "module": current_module,
            "context": "",
            "sentence": sentence,
            "case_type": _classify_case_type(sentence),
        }
        for sentence in fallback_sentences
    ]


def _module_overview_lines(items: list[dict[str, str]]) -> list[str]:
    seen: set[str] = set()
    overview: list[str] = []
    for item in items:
        sentence = item["sentence"]
        if sentence not in seen:
            overview.append(sentence)
            seen.add(sentence)
    return overview[:8]


def _module_context_map(module_name: str, items: list[dict[str, str]]) -> dict[str, list[str]]:
    context_map: dict[str, list[str]] = {}
    for item in items:
        context_name = item["context"] or f"{module_name}核心能力"
        context_map.setdefault(context_name, [])
        if item["sentence"] not in context_map[context_name]:
            context_map[context_name].append(item["sentence"])
    return context_map


def _build_structured_cases(items: list[dict[str, str]]) -> list[dict[str, str]]:
    cases: list[dict[str, str]] = []
    for item in items:
        module_name = item["module"]
        context = item["context"]
        sentence = item["sentence"]
        case_type = item["case_type"]
        point_title = _normalize_point(sentence)
        step_action = _clean_text(sentence)
        if not point_title:
            continue

        title_prefix = f"{point_title}（{context}）" if context else point_title
        base_precondition = f"{module_name}相关配置已准备完成，当前业务场景可被稳定触发。"
        if context:
            base_precondition = f"{base_precondition} 当前关注子场景：{context}。"

        if case_type == "异常场景":
            base_expected = f"系统应正确处理“{step_action}”对应的异常或限制情况，并提供明确反馈。"
        elif case_type == "边界条件":
            base_expected = f"系统应正确处理“{step_action}”对应的边界输入或边界配置，结果符合预期规则。"
        else:
            base_expected = f"系统应正确支持“{step_action}”对应的主流程，并展示预期结果。"

        for index, variant in enumerate(CASE_VARIANTS[case_type], start=1):
            priority = CASE_TYPE_PRIORITY.get(case_type) or _infer_priority_from_title(title_prefix)
            if case_type != "异常场景" and index <= 2 and _infer_priority_from_title(title_prefix) == "P1":
                priority = "P1"

            steps = [
                f"进入{module_name}相关页面或业务入口。",
                f"定位到{context or module_name}对应的业务路径。",
                f"以“{variant}”为目标，执行“{step_action}”对应操作。",
                "观察系统响应、页面跳转、提示信息、状态变化及数据落库结果。",
            ]

            cases.append(
                {
                    "module": module_name,
                    "case_type": case_type,
                    "title": f"{title_prefix} - {variant}",
                    "priority": priority,
                    "preconditions": f"{base_precondition} 当前验证维度：{variant}。",
                    "steps": "\n".join(f"{step_no}. {step}" for step_no, step in enumerate(steps, start=1)),
                    "expected": f"{base_expected} 并覆盖“{variant}”对应的验证目标。",
                    "status": "draft",
                }
            )

    return cases


def _build_case_markdown(case: dict[str, str]) -> str:
    return "\n".join(
        [
            f"#### {case['title']}",
            f"- 优先级：{case['priority']}",
            f"- 前置条件：{case['preconditions']}",
            "- 步骤：",
            *(f"  {step}" for step in case["steps"].splitlines()),
            f"- 预期结果：{case['expected']}",
            f"- 状态：{case['status']}",
            "",
        ]
    )


def generate_structured_cases(requirement_title: str, content: str) -> list[dict[str, str]]:
    extracted_items = _extract_requirement_items(requirement_title, content)
    return _build_structured_cases(extracted_items)


def generate_xmind_markdown(requirement_title: str, content: str) -> str:
    extracted_items = _extract_requirement_items(requirement_title, content)
    structured_cases = generate_structured_cases(requirement_title, content)
    module_map: dict[str, dict[str, list[dict[str, str]]]] = {}
    case_map: dict[str, dict[str, list[dict[str, str]]]] = {}

    for item in extracted_items:
        module_map.setdefault(item["module"], {case_type: [] for case_type in CASE_TYPES})
        module_map[item["module"]][item["case_type"]].append(item)
    for case in structured_cases:
        case_map.setdefault(case["module"], {case_type: [] for case_type in CASE_TYPES})
        case_map[case["module"]][case["case_type"]].append(case)

    sections: list[str] = []
    for module_name, grouped in module_map.items():
        module_lines = [f"# {module_name}", ""]
        module_items = [item for case_type in CASE_TYPES for item in grouped.get(case_type, [])]

        module_lines.append("## 需求概览")
        module_lines.append("")
        for sentence in _module_overview_lines(module_items):
            module_lines.append(f"- {sentence}")
        module_lines.append("")

        module_lines.append("## 业务拆解")
        module_lines.append("")
        for context_name, sentences in _module_context_map(module_name, module_items).items():
            module_lines.append(f"### {context_name}")
            module_lines.append("")
            for sentence in sentences:
                module_lines.append(f"- {sentence}")
            module_lines.append("")

        module_lines.append("## 推荐测试点")
        module_lines.append("")
        for case_type in CASE_TYPES:
            cases = case_map.get(module_name, {}).get(case_type, [])
            if not cases:
                continue
            module_lines.append(f"### {case_type}")
            module_lines.append("")
            for case in cases:
                case_markdown = _build_case_markdown(case)
                if case_markdown:
                    module_lines.append(case_markdown.rstrip())
                    module_lines.append("")

        sections.append("\n".join(module_lines).rstrip())

    return "\n\n".join(section for section in sections if section).strip() + "\n"


def parse_xmind_markdown(markdown: str) -> list[dict[str, str]]:
    current_module = ""
    current_case_type = "正常流程"
    current_section = ""
    current_case: dict[str, str] | None = None
    cases: list[dict[str, str]] = []
    in_steps = False
    step_lines: list[str] = []

    def flush_case() -> None:
        nonlocal current_case, in_steps, step_lines
        if current_case is None:
            return
        if step_lines:
            current_case["steps"] = "\n".join(step_lines).strip()
        current_case["module"] = current_module or current_case.get("module", "") or "默认模块"
        current_case["case_type"] = current_case.get("case_type") or current_case_type
        current_case["priority"] = current_case.get("priority") or CASE_TYPE_PRIORITY.get(current_case_type, "P2")
        current_case["status"] = current_case.get("status") or "draft"
        current_case["preconditions"] = current_case.get("preconditions", "").strip()
        current_case["steps"] = current_case.get("steps", "").strip()
        current_case["expected"] = current_case.get("expected", "").strip()
        current_case["title"] = current_case.get("title", "").strip()
        if current_case["title"]:
            cases.append(current_case)
        current_case = None
        in_steps = False
        step_lines = []

    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()

        if stripped.startswith("# "):
            flush_case()
            current_module = _clean_text(stripped[2:])
            current_section = ""
            continue
        if stripped.startswith("## "):
            flush_case()
            heading = _clean_text(stripped[3:])
            if heading in DESIGN_SECTION_TITLES:
                current_section = heading
            elif heading in CASE_TYPES:
                current_section = "推荐测试点"
                current_case_type = heading or "正常流程"
            continue
        if stripped.startswith("### "):
            heading = _clean_text(stripped[4:])
            if current_section == "推荐测试点" and heading in CASE_TYPES:
                flush_case()
                current_case_type = heading
                continue
            if current_section == "推荐测试点":
                flush_case()
                current_case = {
                    "title": heading,
                    "module": current_module,
                    "case_type": current_case_type,
                }
            continue
        if stripped.startswith("#### "):
            if current_section == "推荐测试点":
                flush_case()
                current_case = {
                    "title": _clean_text(stripped[5:]),
                    "module": current_module,
                    "case_type": current_case_type,
                }
            continue

        if current_case is None:
            continue

        if stripped.startswith("- 步骤"):
            in_steps = True
            step_lines = []
            continue
        if in_steps and re.match(r"^\d+[.)]\s+", stripped):
            step_lines.append(stripped)
            continue

        if stripped.startswith("- 用例ID："):
            current_case["case_id"] = _clean_text(stripped.split("：", 1)[1])
            in_steps = False
            continue
        if stripped.startswith("- 优先级："):
            current_case["priority"] = _clean_text(stripped.split("：", 1)[1]) or "P2"
            in_steps = False
            continue
        if stripped.startswith("- 前置条件："):
            current_case["preconditions"] = _clean_text(stripped.split("：", 1)[1])
            in_steps = False
            continue
        if stripped.startswith("- 预期结果："):
            current_case["expected"] = _clean_text(stripped.split("：", 1)[1])
            in_steps = False
            continue
        if stripped.startswith("- 状态："):
            current_case["status"] = _clean_text(stripped.split("：", 1)[1]) or "draft"
            in_steps = False
            continue

        if not stripped:
            in_steps = False

    flush_case()

    for case in cases:
        case.setdefault("case_id", f"TC-{uuid4().hex[:8].upper()}")
    return cases
