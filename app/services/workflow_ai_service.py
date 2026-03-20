from __future__ import annotations

import logging
from typing import Any

from app.services.ai_service import openai_client, LLM_MODEL, can_use_llm

logger = logging.getLogger(__name__)

STAGE_TYPES = ("outline", "analysis", "cases", "defects", "report")

STAGE_LABELS: dict[str, str] = {
    "outline": "测试大纲",
    "analysis": "需求分析",
    "cases": "用例编写",
    "defects": "缺陷报告",
    "report": "测试报告",
}

STAGE_ORDER: dict[str, int] = {s: i for i, s in enumerate(STAGE_TYPES)}

_OUTLINE_SYSTEM_PROMPT = """\
你是一名资深的测试工程师。请根据用户提供的PRD或测试点，生成一份可直接导入XMind的Markdown大纲。大纲应遵循以下结构：

- 使用 `#` 表示根节点（项目名称）。
- 使用 `##` 表示主要模块。
- 使用 `###` 表示子功能或测试分类。
- 使用 `-` 表示具体的测试点，必要时可缩进表示子场景（正常/异常/边界）。

要求：
- 覆盖所有功能模块和关键测试点。
- 包含非功能测试（性能、兼容性、安全）和风险依赖（若有）。
- 语言简洁，层次清晰。
请输出纯Markdown内容，不要添加额外解释。"""

_ANALYSIS_SYSTEM_PROMPT = """\
你是一名资深测试工程师，请严格基于已提供的需求文档进行测试需求分析，不臆造业务逻辑。

分析必须走完以下三步：
1. 功能点穷尽清单：按以下维度逐项遍历——角色/用户、页面/入口、操作/动作、接口/数据、状态/流程、规则/约束、非功能、关联/依赖、隐性需求/界面状态。
2. 真实用户使用场景补充：误操作/反悔、重复/连续操作、中断与恢复、网络与环境、输入与粘贴、多端与多态、用户差异。
3. 理解一致性检查：原文锚定、术语统一、量化澄清、复述确认。

输出格式（Markdown）：
### 0. 术语与缩写
- 术语 | 含义

### 1. 测试范围
| 序号 | 功能点 | 需求来源 | 优先级 | 可测性 | 备注 |

### 2. 测试点
| 功能点 | 测试关注点 | 对应需求 | 是否真实用户场景 |

### 3. 需求疑义与遗漏
- [ ] 问题描述 / 建议补充

### 4. 需求追溯
| 功能点/测试点 | 需求来源 |

请输出纯Markdown内容。"""

_CASES_SYSTEM_PROMPT = """\
你是一名资深测试工程师。请将用户提供的需求分析/测试点列表转化为适合导入XMind的Markdown测试用例。

规则：
- 结构：`#` 根节点，`##` 模块，`###` 用例分组（功能/异常/边界），`-` 具体用例
- 每条用例必须包含：ID（TC-XXX）、标题、优先级（P0/P1/P2）、前置条件、测试步骤、预期结果、类型（功能/异常/边界）、测试数据、需求来源
- 步骤可执行，预期结果可验证（SMART原则）
- 每条用例标注需求来源

用例格式：
- **TC-001 标题**
  - 优先级: P0
  - 前置条件: ...
  - 测试步骤:
    - 1. ...
    - 2. ...
  - 预期结果: ...
  - 类型: 功能
  - 测试数据: ...
  - 需求来源: ...

请输出纯Markdown内容。"""

_DEFECTS_SYSTEM_PROMPT = """\
你是一名资深测试工程师。请根据用户提供的测试执行结果/问题现象，编写规范的缺陷报告。

每条缺陷必须包含：
- 标题（一句话概括：在什么情况下出现什么问题）
- 严重程度（致命/严重/一般/轻微）
- 模块
- 环境信息
- 前置条件
- 复现步骤（按操作顺序编号）
- 预期结果
- 实际结果
- 附件说明

严重程度参考：
- 致命：系统崩溃、数据丢失、核心功能不可用
- 严重：主要功能异常、无合理替代方案
- 一般：功能异常但有替代方案、影响次要功能
- 轻微：界面、文案、易用性问题

输出格式（Markdown），每条缺陷用 `## 缺陷：[标题]` 分隔。

请输出纯Markdown内容。"""

_REPORT_SYSTEM_PROMPT = """\
你是一名资深测试工程师。请根据用户提供的测试执行结果与缺陷统计，编写测试报告。

报告必须包含以下章节：
## 1. 报告摘要
版本、测试周期、测试结论（通过/有条件通过/不通过）、摘要说明

## 2. 测试执行概况
| 项目 | 数量 |
用例总数、已执行、通过、失败、通过率

## 3. 缺陷概况
| 严重程度 | 数量 | 已修复 | 遗留 |
致命/严重/一般/轻微的分布

## 4. 测试覆盖
覆盖模块/功能简述

## 5. 遗留风险与建议
遗留问题及影响、发布建议、后续改进建议

数据来源于实际测试结果，不捏造数据。结论明确、有据可依。
请输出纯Markdown内容。"""

_SYSTEM_PROMPTS: dict[str, str] = {
    "outline": _OUTLINE_SYSTEM_PROMPT,
    "analysis": _ANALYSIS_SYSTEM_PROMPT,
    "cases": _CASES_SYSTEM_PROMPT,
    "defects": _DEFECTS_SYSTEM_PROMPT,
    "report": _REPORT_SYSTEM_PROMPT,
}

_USER_PROMPT_TEMPLATES: dict[str, str] = {
    "outline": "请根据以下需求文档生成测试大纲：\n\n{content}",
    "analysis": "请对以下内容进行测试需求分析：\n\n{content}",
    "cases": "请基于以下需求分析/测试点生成测试用例：\n\n{content}",
    "defects": "请根据以下测试结果/问题现象生成缺陷报告：\n\n{content}",
    "report": "请根据以下测试数据生成测试报告：\n\n{content}",
}


def generate_stage_content(stage_type: str, content: str) -> dict[str, Any]:
    if stage_type not in _SYSTEM_PROMPTS:
        raise ValueError(f"Unknown stage type: {stage_type}")

    if not can_use_llm():
        raise RuntimeError("LLM 未配置，请在 .env 中设置 LLM_API_KEY 和 LLM_BASE_URL。")

    system_prompt = _SYSTEM_PROMPTS[stage_type]
    user_prompt = _USER_PROMPT_TEMPLATES[stage_type].format(content=content.strip())

    response = openai_client.chat.completions.create(
        model=LLM_MODEL,
        temperature=0.3,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    result = response.choices[0].message.content or ""

    return {
        "output": result,
        "prompt_used": f"[system]\n{system_prompt}\n\n[user]\n{user_prompt[:200]}...",
    }
