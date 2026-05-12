# 创建 Dashboard 页面

**日期：** 2026-05-09

## 概述

创建了 Streamlit Web UI 的项目仪表盘页面，展示项目概览、统计数据、章节进度、快速操作和项目健康指标。

## 变更文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `libriscribe/src/libriscribe/web/pages/dashboard.py` | 新建 | 仪表盘页面主文件 |
| `libriscribe/src/libriscribe/web/__init__.py` | 修改 | 导出 `render_dashboard` |

## 功能清单

- `render_dashboard()` — 主渲染函数，根据是否有项目数据展示欢迎页或仪表盘
- `render_project_stats()` — 统计数据展示（章节数、字数、术语数、引用数、评审分数等）
- `render_chapter_progress()` — 章节完成度柱状图 + 详细进度列表
- `render_quick_actions()` — 快速操作按钮（生成大纲、写章节、审校、导出）
- `_render_overview_card()` — 项目概览卡片
- `_render_recent_activity()` — 最近活动列表
- `_render_health_indicators()` — 项目健康指标（术语一致性、引用覆盖率、评审分数）
- `_render_welcome()` — 无项目时的欢迎/设置页面
