# 创建 diff_viewer.py 版本差异查看器组件

**日期**: 2026-05-09

## 概述

创建了 `libriscribe/src/libriscribe/web/components/diff_viewer.py`，实现章节版本对比功能的 Streamlit 组件。

## 新增文件

- `libriscribe/src/libriscribe/web/components/diff_viewer.py` — 版本差异查看器组件

## 功能清单

| 函数 | 说明 |
|------|------|
| `compute_diff_stats(old_text, new_text)` | 计算差异统计：新增行数、删除行数、修改行数、变化百分比 |
| `render_inline_diff(old_text, new_text)` | 词级差异高亮，返回 HTML 字符串 |
| `render_diff_viewer(old_text, new_text, old_label, new_label)` | 主渲染函数，支持统一视图/侧边对比切换，可折叠未变更区域 |
| `render_version_selector(project_data, chapter_number)` | 版本选择器，从 version_history 中选取两个版本进行对比 |

## 技术要点

- 使用 `difflib.SequenceMatcher` 进行行级和词级差异计算
- 所有用户输入通过 `html.escape()` 转义，防止 XSS
- CSS 样式内嵌，支持绿色(新增)、红色(删除)、黄色(修改)高亮
- 侧边对比使用 `st.columns` 双栏布局
- 折叠未变更区域时保留上下文行（默认 3 行）
