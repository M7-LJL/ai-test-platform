from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

CASE_TYPES = ("正常流程", "边界条件", "异常场景")
CASE_TYPE_PRIORITY = {
    "正常流程": "P2",
    "边界条件": "P2",
    "异常场景": "P1",
}
CASE_TYPE_TO_TEST_KIND = {
    "正常流程": "正向",
    "边界条件": "边界",
    "异常场景": "异常",
}
DESIGN_SECTION_TITLES = {"需求概览", "业务拆解", "推荐测试点"}
CATEGORY_CASE_TYPE_MAP = {
    "functional": "正常流程",
    "boundary": "边界条件",
    "exception": "异常场景",
}

DOMAIN_BUSINESS_LINE_HINTS = (
    "洗衣",
    "烘干",
    "淋浴",
    "饮水",
    "直饮水",
    "充电",
    "吹风",
    "支付",
    "广告",
    "营销",
    "订单",
    "会员",
    "活动",
    "优惠券",
    "积分",
    "审批",
)
DOMAIN_SCENARIO_HINTS = (
    "校园",
    "公寓",
    "酒店",
    "工厂",
    "社区",
    "后台",
    "前台",
    "商家端",
    "管理端",
)
DOMAIN_CHANNEL_HINTS = (
    "APP",
    "支付宝小程序",
    "微信小程序",
    "小程序",
    "PC",
    "H5",
)
DOMAIN_DEVICE_HINTS = (
    "洗衣机",
    "烘干机",
    "淋浴设备",
    "饮水机",
    "直饮水机",
    "充电设备",
    "吹风机",
    "设备",
)
DOMAIN_PAYMENT_HINTS = ("支付宝", "微信", "校园卡", "NFC")
ENTRY_HINTS = (
    "返回首页",
    "订单详情",
    "设备使用页",
    "首页",
    "详情页",
    "列表页",
    "弹窗",
    "页面",
    "入口",
    "按钮",
    "扫码",
    "提交",
    "保存",
    "审批",
    "审核",
)
USER_HINTS = (
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
BUSINESS_OBJECT_HINTS = (
    "订单",
    "用户",
    "商家",
    "门店",
    "标签",
    "白名单",
    "广告",
    "红包",
    "优惠券",
    "配置",
    "状态",
    "审批单",
    "设备",
    "活动",
    "积分",
)
BOUNDARY_HINTS = (
    "边界",
    "上限",
    "下限",
    "最大",
    "最小",
    "次数",
    "比例",
    "默认",
    "空值",
    "临界",
    "0",
    "1",
)
EXCEPTION_HINTS = (
    "失败",
    "异常",
    "超时",
    "拦截",
    "降级",
    "兜底",
    "不展示",
    "不发放",
    "禁止",
    "不可用",
    "错误",
)
CONFIG_HINTS = ("配置", "开关", "比例", "白名单", "标签", "后台", "规则", "参数")


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip(" \t\r\n-—:：。；;，,")


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        cleaned = _clean_text(value)
        if cleaned and cleaned not in result:
            result.append(cleaned)
    return result


def _normalize_point(sentence: str) -> str:
    sentence = _clean_text(sentence)
    sentence = re.sub(r"^(用户|系统|页面|应用|平台)", "", sentence).strip()
    sentence = re.sub(r"^(需要|应当|应该|可以|能够|支持|实现|提供|具备)", "", sentence).strip()
    if not sentence:
        return ""
    return sentence if sentence.startswith("验证") else f"验证{sentence}"


def _split_sentences(content: str) -> list[str]:
    raw_parts = re.split(r"[\r\n]+|(?<=[。！？!?；;])", content or "")
    sentences: list[str] = []
    for part in raw_parts:
        cleaned = re.sub(r"^\s*[-*0-9.)、#]+\s*", "", part).strip()
        cleaned = cleaned.strip("。！？!?；;")
        if len(cleaned) >= 4:
            sentences.append(cleaned)
    return sentences


def _infer_priority_from_title(point_title: str) -> str:
    critical_keywords = ("支付", "登录", "下单", "权限", "跳转", "广告", "白名单", "门店", "审批")
    return "P0" if any(keyword in point_title for keyword in critical_keywords) else "P1"


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
    lines = [line.rstrip() for line in (content or "").splitlines()]
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

    return [
        {
            "module": current_module,
            "context": "",
            "sentence": sentence,
            "case_type": _classify_case_type(sentence),
        }
        for sentence in _split_sentences(content)
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


def _analysis_to_requirement_items(
    requirement_title: str,
    analysis_payload: dict[str, Any] | None,
) -> list[dict[str, str]]:
    if not isinstance(analysis_payload, dict):
        return []

    items: list[dict[str, str]] = []

    test_points = analysis_payload.get("test_points", [])
    if isinstance(test_points, list):
        for point in test_points:
            if not isinstance(point, dict):
                continue
            title = point.get("title")
            category = point.get("category")
            if not isinstance(title, str) or not title.strip():
                continue
            case_type = CATEGORY_CASE_TYPE_MAP.get(str(category), "正常流程")
            source_refs = point.get("source_refs") if isinstance(point.get("source_refs"), list) else []
            items.append(
                {
                    "module": _clean_text(str(point.get("module") or requirement_title)) or "默认模块",
                    "context": _clean_text(str(point.get("page_or_entry") or point.get("context") or f"{case_type}关注项")),
                    "sentence": title.strip(),
                    "case_type": case_type,
                    "requirement_source": "；".join(_dedupe([str(item) for item in source_refs if _clean_text(str(item))])) or str(point.get("requirement_source") or "需求原文"),
                    "role": _clean_text(str(point.get("role") or "")),
                    "preconditions_text": "；".join(_dedupe([str(item) for item in point.get("preconditions", []) if _clean_text(str(item))])),
                    "action_text": _clean_text(str(point.get("action") or title)),
                    "verification_focus_text": "；".join(_dedupe([str(item) for item in point.get("verification_focus", []) if _clean_text(str(item))])),
                    "priority": _clean_text(str(point.get("priority") or "")),
                    "user_scenario_tag": _clean_text(str(point.get("user_scenario_tag") or "")),
                }
            )

    selected_points = analysis_payload.get("selected_points", [])
    if isinstance(selected_points, list):
        for point in selected_points:
            if not isinstance(point, dict):
                continue
            title = point.get("title")
            category = point.get("category")
            if not isinstance(title, str) or not title.strip():
                continue
            case_type = CATEGORY_CASE_TYPE_MAP.get(str(category), "正常流程")
            items.append(
                {
                    "module": _clean_text(str(point.get("module") or requirement_title)) or "默认模块",
                    "context": _clean_text(str(point.get("context") or f"{case_type}关注项")),
                    "sentence": title.strip(),
                    "case_type": case_type,
                    "requirement_source": str(point.get("requirement_source") or point.get("source_ref") or "需求原文"),
                }
            )

    review = analysis_payload.get("review", {})
    if isinstance(review, dict):
        custom_points = review.get("custom_points", [])
        if isinstance(custom_points, list):
            for point in custom_points:
                if isinstance(point, str) and point.strip():
                    items.append(
                        {
                            "module": _clean_text(requirement_title) or "默认模块",
                            "context": "人工确认测试点",
                            "sentence": point.strip(),
                            "case_type": _classify_case_type(point.strip()),
                            "requirement_source": "人工补充",
                        }
                    )

    return items


def _merge_requirement_items(
    requirement_title: str,
    content: str,
    analysis_payload: dict[str, Any] | None,
) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    for source_items in (
        _extract_requirement_items(requirement_title, content),
        _analysis_to_requirement_items(requirement_title, analysis_payload),
    ):
        for item in source_items:
            key = (
                _clean_text(item.get("module", "")),
                _clean_text(item.get("context", "")),
                _clean_text(item.get("sentence", "")),
            )
            if not key[2] or key in seen:
                continue
            seen.add(key)
            merged.append(item)
    return merged


def _first_keyword(text: str, keywords: tuple[str, ...]) -> str:
    for keyword in keywords:
        if keyword in text:
            return keyword
    return ""


def _matched_keywords(text: str, keywords: tuple[str, ...]) -> list[str]:
    return [keyword for keyword in keywords if keyword in text]


def _normalize_locked_case_data(raw: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(raw or {})
    return {
        "scene_name": _clean_text(str(data.get("scene_name", ""))),
        "user_type": _clean_text(str(data.get("user_type", ""))),
        "entry": _clean_text(str(data.get("entry", ""))),
        "business_line": _clean_text(str(data.get("business_line", ""))),
        "scenario_type": _clean_text(str(data.get("scenario_type", ""))),
        "channel": _clean_text(str(data.get("channel", ""))),
        "device_type": _clean_text(str(data.get("device_type", ""))),
        "payment_method": _clean_text(str(data.get("payment_method", ""))),
        "business_object": _clean_text(str(data.get("business_object", ""))),
        "preconditions": _dedupe([_clean_text(str(item)) for item in data.get("preconditions", []) if _clean_text(str(item))]),
        "config_conditions": _dedupe([_clean_text(str(item)) for item in data.get("config_conditions", []) if _clean_text(str(item))]),
        "action": _clean_text(str(data.get("action", ""))),
        "expected_results": _dedupe([_clean_text(str(item)) for item in data.get("expected_results", []) if _clean_text(str(item))]),
        "assertions": _dedupe([_clean_text(str(item)) for item in data.get("assertions", []) if _clean_text(str(item))]),
        "exception_handling": _dedupe([_clean_text(str(item)) for item in data.get("exception_handling", []) if _clean_text(str(item))]),
        "boundary_conditions": _dedupe([_clean_text(str(item)) for item in data.get("boundary_conditions", []) if _clean_text(str(item))]),
    }


def _infer_user_type(sentence: str) -> str:
    return _first_keyword(sentence, USER_HINTS)


def _infer_entry(sentence: str, context: str, module_name: str) -> str:
    hit = _first_keyword(sentence, ENTRY_HINTS)
    return hit or _clean_text(context or module_name)


def _infer_business_line(sentence: str) -> str:
    return _first_keyword(sentence, DOMAIN_BUSINESS_LINE_HINTS)


def _infer_scenario_type(sentence: str) -> str:
    return _first_keyword(sentence, DOMAIN_SCENARIO_HINTS)


def _infer_channel(sentence: str) -> str:
    return _first_keyword(sentence, DOMAIN_CHANNEL_HINTS)


def _infer_device_type(sentence: str) -> str:
    return _first_keyword(sentence, DOMAIN_DEVICE_HINTS)


def _infer_payment_method(sentence: str) -> str:
    return _first_keyword(sentence, DOMAIN_PAYMENT_HINTS)


def _infer_business_object(sentence: str) -> str:
    hits = _matched_keywords(sentence, BUSINESS_OBJECT_HINTS)
    return " / ".join(hits[:3])


def _scene_name_for_card(sentence: str, card_kind: str) -> str:
    base = _clean_text(re.sub(r"^验证", "", sentence)) or "未命名场景"
    suffix_map = {
        "main": "",
        "boundary": "边界校验",
        "exception": "异常处理",
        "config": "配置生效",
    }
    suffix = suffix_map.get(card_kind, "")
    return f"{base} - {suffix}" if suffix and suffix not in base else base


def _expand_design_cards(item: dict[str, str]) -> list[dict[str, Any]]:
    sentence = item["sentence"]
    case_type = item["case_type"]

    has_boundary = any(keyword in sentence for keyword in BOUNDARY_HINTS)
    has_exception = any(keyword in sentence for keyword in EXCEPTION_HINTS)
    has_config = any(keyword in sentence for keyword in CONFIG_HINTS)

    cards: list[dict[str, Any]] = [{**item, "card_kind": "main", "render_case_type": case_type}]

    if case_type != "边界条件" and has_boundary:
        cards.append({**item, "card_kind": "boundary", "render_case_type": "边界条件"})
    if case_type != "异常场景" and has_exception:
        cards.append({**item, "card_kind": "exception", "render_case_type": "异常场景"})
    if case_type == "正常流程" and has_config and not has_boundary:
        cards.append({**item, "card_kind": "config", "render_case_type": "边界条件"})

    deduped_cards: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for card in cards:
        key = (
            _clean_text(card["module"]),
            _clean_text(card["sentence"]),
            _clean_text(card["card_kind"]),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped_cards.append(card)
    return deduped_cards[:4]


def build_locked_case_data_from_item(item: dict[str, Any]) -> dict[str, Any]:
    sentence = item["sentence"]
    context = item.get("context", "")
    module_name = item["module"]
    card_kind = item.get("card_kind", "main")
    explicit_preconditions_text = _clean_text(str(item.get("preconditions_text", "")))
    explicit_action_text = _clean_text(str(item.get("action_text", "")))
    explicit_verification_focus_text = _clean_text(str(item.get("verification_focus_text", "")))
    explicit_role = _clean_text(str(item.get("role", "")))
    explicit_scene_tag = _clean_text(str(item.get("user_scenario_tag", "")))

    preconditions: list[str] = []
    config_conditions: list[str] = []
    expected_results: list[str] = []
    assertions: list[str] = []
    exception_handling: list[str] = []
    boundary_conditions: list[str] = []

    if "支付" in sentence:
        preconditions.append("已准备可复现的支付成功业务数据")
    if "登录" in sentence:
        preconditions.append("测试账号已登录并具备当前场景权限")
    if "扫码" in sentence:
        preconditions.append("扫码入口和对应设备状态可稳定复现")
    if "白名单" in sentence or "标签" in sentence:
        config_conditions.append("已准备命中与未命中标签/白名单的测试数据")
        assertions.append("标签命中结果正确")
    if "广告" in sentence:
        config_conditions.append("广告位开关、广告素材或广告请求结果可被明确校验")
        expected_results.append("广告结果符合当前策略")
    if "红包" in sentence or "优惠券" in sentence:
        config_conditions.append("奖励发放条件和金额可被明确校验")
        expected_results.append("奖励发放结果符合规则")
    if "比例" in sentence or "方式1" in sentence or "方式2" in sentence:
        config_conditions.append("相关比例或策略配置已生效")
        assertions.append("策略命中结果正确")
    if any(keyword in sentence for keyword in CONFIG_HINTS):
        config_conditions.append("相关配置、开关或规则已准备完成")
        assertions.append("配置生效结果正确")
    if any(keyword in sentence for keyword in BOUNDARY_HINTS):
        boundary_conditions.append("已准备边界前、边界值、边界后的测试状态")
    if any(keyword in sentence for keyword in EXCEPTION_HINTS):
        exception_handling.append("异常链路处理正确且反馈明确")
    if "跳转" in sentence:
        expected_results.append("页面跳转结果正确")
    if "展示" in sentence:
        expected_results.append("页面展示结果正确")
    if "状态" in sentence:
        expected_results.append("状态流转结果正确")
    if "列表" in sentence and "详情" in sentence:
        assertions.append("列表与详情数据保持一致")
    if "保存" in sentence or "提交" in sentence or "审批" in sentence or "审核" in sentence:
        assertions.append("提交结果与最终状态一致")

    if card_kind == "boundary":
        boundary_conditions.append(_clean_text(sentence))
    elif card_kind == "exception":
        exception_handling.append(_clean_text(sentence))
    elif card_kind == "config":
        config_conditions.append(_clean_text(sentence))
    else:
        assertions.append(_clean_text(sentence))

    if explicit_preconditions_text:
        preconditions.extend([segment for segment in explicit_preconditions_text.split("；") if _clean_text(segment)])
    if explicit_verification_focus_text:
        assertions.extend([segment for segment in explicit_verification_focus_text.split("；") if _clean_text(segment)])
    if explicit_scene_tag:
        config_conditions.append(f"真实用户场景：{explicit_scene_tag}")

    return _normalize_locked_case_data(
        {
            "scene_name": _scene_name_for_card(sentence, card_kind),
            "user_type": explicit_role or _infer_user_type(sentence),
            "entry": _infer_entry(sentence, context, module_name),
            "business_line": _infer_business_line(sentence),
            "scenario_type": _infer_scenario_type(sentence),
            "channel": _infer_channel(sentence),
            "device_type": _infer_device_type(sentence),
            "payment_method": _infer_payment_method(sentence),
            "business_object": _infer_business_object(sentence),
            "preconditions": preconditions,
            "config_conditions": config_conditions,
            "action": explicit_action_text or _clean_text(re.sub(r"^验证", "", sentence)),
            "expected_results": expected_results,
            "assertions": assertions,
            "exception_handling": exception_handling,
            "boundary_conditions": boundary_conditions,
        }
    )


def render_case_from_locked_data(
    locked_case_data: dict[str, Any] | None,
    *,
    module: str,
    section: str = "",
    case_type: str = "正常流程",
    priority: str = "P1",
    requirement_source: str = "需求原文",
) -> dict[str, str]:
    data = _normalize_locked_case_data(locked_case_data)

    title = data["scene_name"] or data["action"] or module or "未命名场景"

    preconditions_parts: list[str] = []
    if data["user_type"]:
        preconditions_parts.append(f"{data['user_type']}账号可用于当前场景")
    if data["business_line"]:
        preconditions_parts.append(f"业务线：{data['business_line']}")
    if data["scenario_type"]:
        preconditions_parts.append(f"场景：{data['scenario_type']}")
    if data["channel"]:
        preconditions_parts.append(f"渠道：{data['channel']}")
    if data["device_type"]:
        preconditions_parts.append(f"设备：{data['device_type']}")
    if data["payment_method"]:
        preconditions_parts.append(f"支付方式：{data['payment_method']}")
    if data["business_object"]:
        preconditions_parts.append(f"目标对象：{data['business_object']}")
    preconditions_parts.extend(data["preconditions"])
    preconditions_parts.extend(data["config_conditions"])
    preconditions = "；".join(_dedupe(preconditions_parts)) + "。" if preconditions_parts else "基础测试数据已准备完成。"

    steps: list[str] = []
    steps.append(f"进入{data['entry']}。" if data["entry"] else "进入当前业务场景对应入口。")
    steps.append(f"执行：{data['action']}。" if data["action"] else "执行当前场景对应的核心业务操作。")

    if case_type == "边界条件" and data["boundary_conditions"]:
        steps.append(f"重点覆盖边界：{'；'.join(data['boundary_conditions'])}。")
    elif case_type == "异常场景" and data["exception_handling"]:
        steps.append(f"重点覆盖异常：{'；'.join(data['exception_handling'])}。")
    elif data["assertions"]:
        steps.append(f"重点校验：{'；'.join(data['assertions'])}。")
    else:
        steps.append("观察页面反馈、状态流转和结果数据。")

    expected_items = _dedupe(
        [
            *data["expected_results"],
            *data["assertions"],
            *(data["boundary_conditions"] if case_type == "边界条件" else []),
            *(data["exception_handling"] if case_type == "异常场景" else []),
        ]
    )
    expected = "；".join(expected_items) if expected_items else "结果符合需求预期。"

    return {
        "module": module or section or "默认模块",
        "section": section,
        "case_type": case_type,
        "test_kind": CASE_TYPE_TO_TEST_KIND.get(case_type, "正向"),
        "title": title,
        "priority": priority,
        "preconditions": preconditions,
        "steps": "\n".join(f"{index}. {step}" for index, step in enumerate(steps, start=1)),
        "expected": expected,
        "test_data": f"锁定字段渲染：{data['scene_name'] or data['action'] or '当前场景'}",
        "requirement_source": requirement_source,
        "status": "draft",
        "locked_case_data": data,
    }


def _build_generic_cases_for_item(item: dict[str, str]) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []

    for card in _expand_design_cards(item):
        locked_case_data = build_locked_case_data_from_item(card)
        rendered_case_type = card.get("render_case_type", card["case_type"])

        rendered = render_case_from_locked_data(
            locked_case_data,
            module=card.get("module") or card.get("requirement_title") or "默认模块",
            section="",
            case_type=rendered_case_type,
            priority=(
                card.get("priority")
                or _infer_priority_from_title(card["sentence"])
                if rendered_case_type == "正常流程"
                else CASE_TYPE_PRIORITY.get(rendered_case_type, "P2")
            ),
            requirement_source=card.get("requirement_source") or card.get("source_ref") or "需求原文",
        )

        results.append(
            {
                **rendered,
                "case_id": f"TC-{uuid4().hex[:8].upper()}",
            }
        )

    return results


def _build_structured_cases(items: list[dict[str, str]]) -> list[dict[str, str]]:
    cases: list[dict[str, str]] = []
    seen_titles: set[tuple[str, str]] = set()

    for item in items:
        sentence = item["sentence"]
        point_title = _normalize_point(sentence)
        if not point_title:
            continue

        generated_cases = _build_generic_cases_for_item(item)

        for case in generated_cases:
            dedupe_key = (_clean_text(case["module"]), _clean_text(case["title"]))
            if dedupe_key in seen_titles:
                continue
            seen_titles.add(dedupe_key)
            cases.append(case)

    return cases


def _build_case_markdown(case: dict[str, str]) -> str:
    if case.get("section"):
        return "\n".join(
            [
                f"### {case['case_id']} {case['title']}",
                f"- **ID**: {case.get('case_id', f'TC-{uuid4().hex[:8].upper()}')}",
                f"- **模块**: {case['module']}",
                f"- **标题**: {case['title']}",
                f"- **优先级**: {case['priority']}",
                f"- **前置条件**: {case['preconditions']}",
                "- **测试步骤**:",
                *(f"  {step}" for step in case["steps"].splitlines()),
                f"- **预期结果**: {case['expected']}",
                f"- **类型**: {case.get('test_kind') or case.get('case_type', '正向')}",
                f"- **测试数据**: {case.get('test_data', '')}",
                f"- **需求来源**: {case.get('requirement_source', '需求原文')}",
                "",
            ]
        )
    return "\n".join(
        [
            f"#### {case['title']}",
            f"- 用例ID：{case.get('case_id', f'TC-{uuid4().hex[:8].upper()}')}",
            f"- 优先级：{case['priority']}",
            f"- 类型：{case.get('test_kind') or case.get('case_type', '正向')}",
            f"- 前置条件：{case['preconditions']}",
            "- 步骤：",
            *(f"  {step}" for step in case["steps"].splitlines()),
            f"- 预期结果：{case['expected']}",
            f"- 测试数据：{case.get('test_data', '')}",
            f"- 需求来源：{case.get('requirement_source', '需求原文')}",
            f"- 状态：{case['status']}",
            "",
        ]
    )


def generate_structured_cases(
    requirement_title: str,
    content: str,
    analysis_payload: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    if isinstance(analysis_payload, dict) and isinstance(analysis_payload.get("test_points"), list) and analysis_payload.get("test_points"):
        extracted_items = _analysis_to_requirement_items(requirement_title, analysis_payload)
    else:
        extracted_items = _merge_requirement_items(requirement_title, content, analysis_payload)
        if not extracted_items:
            extracted_items = _extract_requirement_items(requirement_title, content)
    for item in extracted_items:
        item["requirement_title"] = requirement_title
    return _build_structured_cases(extracted_items)


def generate_xmind_markdown(
    requirement_title: str,
    content: str,
    analysis_payload: dict[str, Any] | None = None,
) -> str:
    structured_cases = generate_structured_cases(requirement_title, content, analysis_payload=analysis_payload)

    if isinstance(analysis_payload, dict) and isinstance(analysis_payload.get("test_points"), list) and analysis_payload.get("test_points"):
        extracted_items = _analysis_to_requirement_items(requirement_title, analysis_payload)
    else:
        extracted_items = _merge_requirement_items(requirement_title, content, analysis_payload)
        if not extracted_items:
            extracted_items = _extract_requirement_items(requirement_title, content)

    module_map: dict[str, dict[str, list[dict[str, str]]]] = {}
    case_map: dict[str, dict[str, list[dict[str, str]]]] = {}
    summary = analysis_payload.get("summary", {}) if isinstance(analysis_payload, dict) else {}
    review = analysis_payload.get("review", {}) if isinstance(analysis_payload, dict) else {}

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
        overview_lines = _module_overview_lines(module_items)
        if isinstance(summary, dict):
            overview_lines = _dedupe(
                [*summary.get("system_flow", []), *summary.get("main_risks", []), *overview_lines]
            )
        for sentence in overview_lines[:10]:
            module_lines.append(f"- {sentence}")
        module_lines.append("")

        module_lines.append("## 业务拆解")
        module_lines.append("")
        if isinstance(summary, dict):
            summary_sections = {
                "系统流程": summary.get("system_flow", []),
                "核心规则": summary.get("core_rules", []),
                "主要风险": summary.get("main_risks", []),
                "测试重点": summary.get("test_focus", []),
            }
            for context_name, sentences in summary_sections.items():
                normalized_sentences = [sentence for sentence in sentences if isinstance(sentence, str) and sentence.strip()]
                if not normalized_sentences:
                    continue
                module_lines.append(f"### {context_name}")
                module_lines.append("")
                for sentence in normalized_sentences:
                    module_lines.append(f"- {sentence}")
                module_lines.append("")
        else:
            for context_name, sentences in _module_context_map(module_name, module_items).items():
                module_lines.append(f"### {context_name}")
                module_lines.append("")
                for sentence in sentences:
                    module_lines.append(f"- {sentence}")
                module_lines.append("")

        if isinstance(review, dict):
            custom_points = review.get("custom_points", [])
            if isinstance(custom_points, list) and custom_points:
                module_lines.append("### 人工补充")
                module_lines.append("")
                for point in custom_points:
                    module_lines.append(f"- {point}")
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
        inferred_case_type = current_case.get("case_type") or current_case_type
        test_kind = str(current_case.get("test_kind", ""))
        if "边界" in test_kind:
            inferred_case_type = "边界条件"
        elif "异常" in test_kind:
            inferred_case_type = "异常场景"
        current_case["case_type"] = inferred_case_type
        current_case["priority"] = current_case.get("priority") or CASE_TYPE_PRIORITY.get(inferred_case_type, "P2")
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

    def parse_field(line: str) -> tuple[str, str] | None:
        match = re.match(r"^-\s*(?:\*\*)?([^:*：]+?)(?:\*\*)?\s*[:：]\s*(.*)$", line.strip())
        if not match:
            return None
        return _clean_text(match.group(1)), match.group(2).strip()

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
            else:
                current_section = "README测试用例"
                current_module = heading
            continue

        if stripped.startswith("### "):
            heading = _clean_text(stripped[4:])
            if current_section == "README测试用例" or re.match(r"^TC[-_A-Z0-9]+", heading):
                flush_case()
                case_id_match = re.match(r"^(TC[-_A-Z0-9]+)\s+(.*)$", heading)
                current_case = {
                    "title": case_id_match.group(2) if case_id_match else heading,
                    "module": current_module,
                    "case_type": current_case_type,
                }
                if case_id_match:
                    current_case["case_id"] = case_id_match.group(1)
                continue

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

        field = parse_field(stripped)

        if stripped.startswith("- 步骤") or stripped.startswith("- **测试步骤**"):
            in_steps = True
            step_lines = []
            continue

        if in_steps and re.match(r"^\d+[.)]\s+", stripped):
            step_lines.append(stripped)
            continue

        if field and field[0] in {"用例ID", "ID"}:
            current_case["case_id"] = _clean_text(field[1])
            in_steps = False
            continue
        if field and field[0] == "模块":
            current_case["module"] = _clean_text(field[1]) or current_module
            in_steps = False
            continue
        if field and field[0] == "标题":
            current_case["title"] = _clean_text(field[1]) or current_case.get("title", "")
            in_steps = False
            continue
        if field and field[0] == "优先级":
            current_case["priority"] = _clean_text(field[1]) or "P2"
            in_steps = False
            continue
        if field and field[0] == "前置条件":
            current_case["preconditions"] = _clean_text(field[1])
            in_steps = False
            continue
        if field and field[0] == "预期结果":
            current_case["expected"] = _clean_text(field[1])
            in_steps = False
            continue
        if field and field[0] == "类型":
            current_case["test_kind"] = _clean_text(field[1]) or current_case_type
            in_steps = False
            continue
        if field and field[0] == "测试数据":
            current_case["test_data"] = _clean_text(field[1])
            in_steps = False
            continue
        if field and field[0] == "需求来源":
            current_case["requirement_source"] = _clean_text(field[1]) or "需求原文"
            in_steps = False
            continue
        if field and field[0] == "状态":
            current_case["status"] = _clean_text(field[1]) or "draft"
            in_steps = False
            continue

        if not stripped:
            in_steps = False

    flush_case()

    for case in cases:
        case.setdefault("case_id", f"TC-{uuid4().hex[:8].upper()}")
    return cases