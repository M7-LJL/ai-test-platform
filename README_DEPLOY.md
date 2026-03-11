# Render 部署手册

本手册用于把当前 `ai-test-platform` 项目部署到 [Render](https://render.com/)。

适用范围：
- 你已经在本地把项目跑起来了
- 你希望拿到一个公网可访问地址
- 你可以把代码推到 GitHub

部署完成后，你会得到：
- 一个公网 Web 地址
- 一个 Render 托管的 PostgreSQL 数据库
- 一个持久化磁盘目录，用于保存生成的 HTML 报告

---

## 一、部署前准备

在开始前，请确认本地项目已经具备这些文件：

- `requirements.txt`
- `render.yaml`
- `runtime.txt`
- `app/main.py`
- `app/database.py`

当前项目已经支持：

- `DATABASE_URL` 环境变量
- Render PostgreSQL 连接串
- `REPORTS_DIR` 持久化目录
- FastAPI 启动命令

---

## 二、把项目推到 GitHub

如果你还没有 Git 仓库，可以在项目根目录执行：

```bash
git init
git add .
git commit -m "initial deploy setup"
```

然后在 GitHub 新建一个仓库，比如：

- `ai-test-platform`

再执行：

```bash
git remote add origin https://github.com/<你的用户名>/ai-test-platform.git
git branch -M main
git push -u origin main
```

如果你已经有仓库，只需要把当前代码推上去即可。

---

## 三、在 Render 创建服务

### 方式 A：推荐，直接使用 `render.yaml`

1. 打开 [Render Dashboard](https://dashboard.render.com/)
2. 点击 `New +`
3. 选择 `Blueprint`
4. 连接你的 GitHub
5. 选择这个项目对应的仓库
6. Render 会自动识别仓库根目录下的 `render.yaml`
7. 点击 `Apply`

这样会自动创建：

- 一个 Web 服务：`ai-test-platform`
- 一个 PostgreSQL 数据库：`ai-test-platform-db`
- 一个持久化磁盘：`/var/data`

### 方式 B：手动创建

如果你不想用 Blueprint，也可以手动创建：

1. `New +` -> `Web Service`
2. 选择 GitHub 仓库
3. 配置如下：

- `Environment`: `Python`
- `Build Command`:

```bash
pip install -r requirements.txt
```

- `Start Command`:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

然后再手动创建：

- PostgreSQL 数据库
- Persistent Disk

并补环境变量：

- `DATABASE_URL`
- `REPORTS_DIR=/var/data/reports`

---

## 四、Render 自动使用的配置说明

项目中已经提供了 `render.yaml`：

```yaml
services:
  - type: web
    name: ai-test-platform
    env: python
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn app.main:app --host 0.0.0.0 --port $PORT
    envVars:
      - key: DATABASE_URL
        fromDatabase:
          name: ai-test-platform-db
          property: connectionString
      - key: REPORTS_DIR
        value: /var/data/reports
    disk:
      name: ai-test-platform-data
      mountPath: /var/data
      sizeGB: 1
```

它的作用是：

- 自动安装依赖
- 自动启动 FastAPI
- 自动把 PostgreSQL 连接串注入到 `DATABASE_URL`
- 自动给报告目录分配持久化空间

---

## 五、数据库说明

本地开发默认使用 SQLite：

```env
DATABASE_URL=sqlite:///./test_management.db
```

部署到 Render 后，会自动切换成 PostgreSQL。

当前 `app/database.py` 已经做了兼容处理：

- 本地没配 `DATABASE_URL` 时，用 SQLite
- 线上有 `DATABASE_URL` 时，用 PostgreSQL
- 自动兼容 `postgres://` 到 SQLAlchemy 可识别格式

你不需要手动改代码。

---

## 六、首次部署后的检查步骤

部署完成后，按下面顺序检查：

1. 打开 Render 提供的公网地址
2. 访问首页 `/`
3. 打开 `/projects`
4. 新建一个项目
5. 新建一个需求
6. 点击 `AI 生成用例`
7. 打开项目测试报告页
8. 测试 `导出 Xmind Markdown`
9. 测试 `导入 Markdown 用例`

如果这些都能正常打开，说明部署成功。

---

## 七、常见问题排查

### 1. 部署后打不开页面

检查 Render 日志里是否有：

- `ModuleNotFoundError`
- `ImportError`
- `SyntaxError`
- `Application startup failed`

优先确认：

- `requirements.txt` 是否完整
- `Start Command` 是否正确

当前正确启动命令是：

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

### 2. 数据库连接失败

检查环境变量里是否存在：

- `DATABASE_URL`

如果使用 `render.yaml` 创建 Blueprint，通常会自动注入。

### 3. 报告导出后文件丢失

确认 Render 服务挂载了持久化磁盘，并且：

- `REPORTS_DIR=/var/data/reports`

### 4. 页面样式或图标异常

当前静态资源使用：

- `/static/favicon.svg`

如果你后续增加 CSS/JS 文件，也放在：

- `app/static/`

---

## 八、推荐发布流程

以后更新代码时，推荐这样做：

1. 本地修改并测试
2. 提交代码到 Git
3. 推送到 GitHub
4. Render 自动重新部署
5. 部署完成后打开公网地址验证

常用命令：

```bash
git add .
git commit -m "update feature"
git push
```

---

## 九、建议补充项

当前项目已经可以部署，但如果你准备长期使用，建议后续继续补：

- `.gitignore`
- `README.md`
- 统一日志输出
- 管理员登录鉴权
- 更稳定的文件存储方案
- 数据迁移工具，比如 Alembic

---

## 十、最短操作版

如果你只想快速照着做，直接按这几步：

1. 把项目推到 GitHub
2. 打开 Render
3. `New +` -> `Blueprint`
4. 选择你的仓库
5. 点击 `Apply`
6. 等待部署完成
7. 打开 Render 分配的网址

---

## 十一、当前项目关键配置

依赖安装：

```bash
pip install -r requirements.txt
```

本地运行：

```bash
uvicorn app.main:app --reload
```

线上运行：

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

本地环境变量示例：

```env
DATABASE_URL=sqlite:///./test_management.db
REPORTS_DIR=./reports
```

如果你后面需要，我还可以继续帮你补：

- `.gitignore`
- `README.md`
- `Railway` 部署版说明
- `Dockerfile` 和 `docker-compose.yml`
