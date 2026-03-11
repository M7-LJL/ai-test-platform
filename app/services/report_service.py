from __future__ import annotations

import html

from app.database import SessionLocal
from app.models import Project, TestCase


def generate_report(project_id: int, export_url: str | None = None) -> str:
    db = SessionLocal()
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if project is None:
            raise ValueError("Project not found.")

        test_cases = (
            db.query(TestCase)
            .filter(TestCase.project_id == project_id)
            .order_by(TestCase.created_at.desc())
            .all()
        )

        priority_counts = {"P0": 0, "P1": 0, "P2": 0}
        for case in test_cases:
            if case.priority in priority_counts:
                priority_counts[case.priority] += 1

        rows = "\n".join(
            (
                "<tr>"
                f"<td>{html.escape(case.case_id)}</td>"
                f"<td>{html.escape(case.title)}</td>"
                f"<td>{html.escape(case.module or '-')}</td>"
                f"<td>{html.escape(case.priority or '-')}</td>"
                f"<td><pre>{html.escape(case.steps or '-')}</pre></td>"
                f"<td><pre>{html.escape(case.expected or '-')}</pre></td>"
                f"<td>{html.escape(case.status or '-')}</td>"
                "</tr>"
            )
            for case in test_cases
        )

        if not rows:
            rows = '<tr><td colspan="7">暂无用例</td></tr>'

        actions = ""
        if export_url:
            actions = (
                '<div class="card">'
                '<div class="actions">'
                f'<a class="btn" href="{html.escape(export_url)}">导出 HTML 报告</a>'
                f'<a class="btn btn-secondary" href="/projects/{project_id}">返回项目详情</a>'
                '<a class="btn btn-secondary" href="/projects">返回项目列表</a>'
                "</div>"
                "</div>"
            )

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>测试报告 - {html.escape(project.name)}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 32px; color: #1f2937; background: #f9fafb; }}
    h1, h2 {{ margin-bottom: 12px; }}
    .card {{ background: #ffffff; border: 1px solid #e5e7eb; border-radius: 10px; padding: 20px; margin-bottom: 20px; }}
    .stats {{ display: flex; gap: 16px; flex-wrap: wrap; }}
    .stat {{ min-width: 140px; background: #f3f4f6; border-radius: 8px; padding: 16px; }}
    .actions {{ display: flex; gap: 12px; flex-wrap: wrap; }}
    .btn {{ display: inline-block; background: #2563eb; color: #ffffff; text-decoration: none; padding: 10px 16px; border-radius: 8px; }}
    .btn-secondary {{ background: #4b5563; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border: 1px solid #d1d5db; padding: 12px; text-align: left; vertical-align: top; }}
    th {{ background: #f3f4f6; }}
    pre {{ white-space: pre-wrap; margin: 0; font-family: inherit; }}
  </style>
</head>
<body>
  {actions}
  <div class="card">
    <h1>项目测试报告</h1>
    <p><strong>项目名称：</strong>{html.escape(project.name)}</p>
    <p><strong>用例总数：</strong>{len(test_cases)}</p>
  </div>

  <div class="card">
    <h2>优先级分布</h2>
    <div class="stats">
      <div class="stat"><strong>P0</strong><br />{priority_counts["P0"]}</div>
      <div class="stat"><strong>P1</strong><br />{priority_counts["P1"]}</div>
      <div class="stat"><strong>P2</strong><br />{priority_counts["P2"]}</div>
    </div>
  </div>

  <div class="card">
    <h2>用例列表</h2>
    <table>
      <thead>
        <tr>
          <th>用例ID</th>
          <th>标题</th>
          <th>模块</th>
          <th>优先级</th>
          <th>步骤</th>
          <th>预期结果</th>
          <th>状态</th>
        </tr>
      </thead>
      <tbody>
        {rows}
      </tbody>
    </table>
  </div>
</body>
</html>
"""
    finally:
        db.close()
