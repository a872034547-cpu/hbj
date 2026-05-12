# 任务备忘录：创建章节编辑器页面

**日期:** 2026-05-09

## 概述

创建了 Streamlit Web UI 的章节编辑器页面 `editor.py`，提供完整的章节编辑、评审、引用和术语管理功能。

## 创建的文件

- `libriscribe/src/libriscribe/web/pages/editor.py`

## 功能清单

| 函数 | 功能 |
|------|------|
| `render_editor()` | 主页面入口，左右分栏布局 |
| `render_chapter_selector(project_data)` | 章节下拉选择器 |
| `render_chapter_content(chapter, chapter_number)` | Markdown 编辑区 + 元数据（字数/场景数/修改时间） |
| `render_chapter_actions(chapter_number, project_data)` | 5 个操作按钮：保存/重新生成/评审/添加引用/检查术语 |
| `render_review_panel(chapter_number, project_data)` | 评审反馈面板（评分/建议/历史记录） |
| `render_citation_panel(chapter_number, project_data)` | 引用溯源面板（来源/页码/GB/T 7714 格式） |
| `render_terminology_panel(chapter_number, project_data)` | 术语高亮面板（匹配统计/术语表展示） |
| `render_scene_panel(chapter)` | 场景大纲面板（摘要/角色/目标/情感基调） |

## 依赖的模块

- `libriscribe.knowledge_base` — ProjectKnowledgeBase, Chapter, Scene, Citation, ChapterReview
- `libriscribe.agents.chapter_writer` — ChapterWriterAgent（重新生成）
- `libriscribe.agents.content_reviewer` — ContentReviewerAgent（评审）
- `libriscribe.agents.citation_agent` — CitationAgent（引用提取）
- `libriscribe.memory.terminology` — TerminologyManager（术语检查）
- `libriscribe.utils.llm_client` — LLMClient
- `libriscribe.utils.file_utils` — read_markdown_file, write_markdown_file
