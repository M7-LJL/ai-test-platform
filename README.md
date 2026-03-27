# AI Test Platform

一个基于 `FastAPI + Jinja2 + SQLAlchemy` 的测试管理平台 `MVP`，用于把需求分析、测试工作流、测试用例、执行计划、缺陷和报告串起来，形成可落地的测试管理闭环。

当前项目的目标不是单纯“生成测试文档”，而是逐步演进为一个面向 QA 的测试工作流平台。

## 项目定位

这个项目当前聚焦 3 类核心能力：

- 测试对象管理：项目、需求、用例、计划、缺陷
- AI 辅助工作流：从需求进入测试工作流，生成阶段性产出
- 测试执行闭环：基于计划执行用例、记录结果、沉淀缺陷与报告

适合的使用场景：

- 从需求文档生成测试分析和测试用例
- 管理项目下的需求、用例、测试计划和缺陷
- 通过页面化工作流推进测试活动
- 逐步把 AI 生成能力融入测试流程，而不是只做聊天式工具

## 当前已实现能力

### 1. 项目管理
- 创建、查看、删除项目
- 项目详情页聚合需求、工作流、用例和测试报告入口

### 2. 需求管理
- 新建需求
- 基于需求做结构化分析
- 保存分析结果和评审点
- 支持从需求进入测试工作流

### 3. 测试工作流
- 为需求创建测试工作流
- 支持阶段输入、阶段生成、阶段保存
- 支持导出工作流阶段产出
- 当前已实现阶段：
  - `测试大纲`
  - `需求分析`
  - `用例编写`
  - `缺陷报告`
  - `测试报告`

### 4. 测试用例管理
- 基于需求分析生成结构化测试用例
- 编辑测试用例
- 支持用例锁定，保护人工修改内容
- 支持 Markdown/XMind 风格导入导出

### 5. 测试计划与执行
- 创建测试计划
- 选择测试用例加入计划
- 记录执行结果：`untested / passed / failed / blocked`
- 自动汇总计划执行统计

### 6. 缺陷与报告
- 管理缺陷对象
- 生成项目级测试报告页面
- 支持导出 HTML 报告

## 当前系统边界

这是一个 `MVP`，已经具备测试平台基础骨架，但还在持续演进。

当前更偏向：

- 测试管理平台雏形
- AI 驱动的测试工作流原型
- 面向文档和结构化数据的测试资产平台

尚未完全补齐但已明确规划的方向：

- 更完整的 9 阶段测试工作流
- 阶段确认、回退、跳步、待更新状态
- 测试计划、测试准备、测试执行的更强联动
- 风险项、待确认项、追溯关系的系统化管理

## 技术栈

后端：

- `FastAPI`
- `SQLAlchemy`
- `Jinja2`
- `Uvicorn`

数据层：

- 本地默认使用 `SQLite`
- 部署时支持 `PostgreSQL`

AI 能力：

- 使用 OpenAI 兼容接口
- 当前支持通过环境变量接入大模型

部署：

- 本地运行
- Render 部署

## 本地启动

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

可以复制 `.env.example` 为 `.env`，然后按需填写：

```env
DATABASE_URL=sqlite:///./test_management.db
REPORTS_DIR=./reports
LLM_API_KEY=
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
```

说明：

- 不配置 `DATABASE_URL` 时，默认使用项目目录下的 `SQLite`
- 不配置 `LLM_API_KEY` 时，工作流可运行，但 AI 生成功能会退化为占位内容

### 3. 启动服务

Windows 推荐：

```bash
py -3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

通用方式：

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

启动后访问：

- 首页：[http://127.0.0.1:8000/](http://127.0.0.1:8000/)
- 项目列表：[http://127.0.0.1:8000/projects](http://127.0.0.1:8000/projects)
- API 文档：[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

## 基本使用流程

建议按下面顺序体验当前系统：

1. 创建项目
2. 新建需求
3. 进入需求详情页
4. 启动或进入测试工作流
5. 生成测试大纲、需求分析、测试用例
6. 进入用例中心编辑和确认测试用例
7. 创建测试计划并加入测试用例
8. 记录执行结果
9. 查看缺陷和测试报告

## 目录结构

```text
ai-test-platform/
├── app/
│   ├── routers/          # 页面与业务路由
│   ├── services/         # AI、报告、XMind 等服务
│   ├── templates/        # Jinja2 页面模板
│   ├── static/           # 静态资源
│   ├── database.py       # 数据库初始化与兼容处理
│   ├── models.py         # 核心数据模型
│   └── main.py           # FastAPI 应用入口
├── reports/              # 报告输出目录
├── README.md
├── README_DEPLOY.md
├── requirements.txt
├── render.yaml
└── runtime.txt
```

## 核心数据模型

当前主要模型包括：

- `Project`
- `Requirement`
- `RequirementReviewPoint`
- `TestCase`
- `TestSuite`
- `TestPlan`
- `TestPlanCase`
- `Defect`
- `TestWorkflow`
- `WorkflowStage`

这些模型已经构成测试平台的基础领域对象，也是后续把测试工作流系统化的基础。

## 部署说明

如果你希望部署到 Render，请查看：

- `README_DEPLOY.md`

部署文档已包含：

- Render Blueprint 方式
- 手动创建 Web Service 方式
- PostgreSQL 配置
- 持久化磁盘配置
- 常见问题排查

## 当前问题与下一步规划

目前项目最值得继续补强的方向：

- 把 5 阶段 workflow 扩展到完整测试工作流
- 为 workflow 增加确认、回退、阻塞、待更新状态
- 把测试计划、测试准备、测试执行更紧密地接到 workflow
- 优化 AI 用例生成质量，减少重复和泛化
- 加强结构化追溯：需求 -> 测试点 -> 用例 -> 执行 -> 缺陷 -> 报告

## License

本项目使用仓库内提供的 `LICENSE`。
