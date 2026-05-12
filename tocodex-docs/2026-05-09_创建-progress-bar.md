# 任务备忘录：创建 progress_bar.py 进度展示组件

**日期**: 2026-05-09
**任务**: 创建 Streamlit Web UI 的进度展示组件

## 变更文件

- `libriscribe/src/libriscribe/web/components/progress_bar.py` — **新建**

## 功能概要

实现了 6 个函数：

| 函数 | 用途 |
|------|------|
| `render_book_progress(project_data)` | 展示书籍整体完成进度（进度条 + 7 阶段状态） |
| `render_chapter_progress(project_data)` | 展示每章的 大纲/写作/审校/编辑 四项状态 |
| `render_writing_stats(project_data)` | 展示写作统计：总字数、章均字数、阅读时间、完成比例、评审分数分布 |
| `render_phase_indicator(phase, status)` | 单阶段状态指示器（带颜色和图标） |
| `calculate_overall_progress(project_data)` | 加权计算整体进度，返回 0.0~1.0 |
| `_render_status_badge(label, status)` | 内部辅助：带颜色的状态标签 |

## 设计要点

- 兼容 `ProjectKnowledgeBase`（Pydantic model）和 `dict` 两种数据格式
- 7 个阶段权重：概念 5%、大纲 10%、角色 10%、世界观 10%、写作 40%、审校 15%、导出 10%
- 状态推断逻辑基于知识库实际字段（logline、outline、characters、chapters、chapter_reviews 等）
- 使用 `st.progress`、`st.metric`、`st.columns` 等 Streamlit 原生组件
