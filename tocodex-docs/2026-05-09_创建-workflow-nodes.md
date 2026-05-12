# 任务备忘录：创建 workflow/nodes.py

**日期**: 2026-05-09

## 概述
创建 LangGraph 工作流节点实现文件，包含工作流中各个处理节点的函数定义。

## 变更文件
- `libriscribe/src/libriscribe/workflow/nodes.py` — 新建

## 节点列表
| 节点函数 | 功能 |
|----------|------|
| `planner_node` | 规划节点：初始化项目，准备章节计划 |
| `research_node` | 研究节点：从 RAG 中检索相关资料 |
| `writer_node` | 写作节点：生成章节内容 |
| `critic_node` | 评审节点：检查章节质量 |
| `editor_node` | 编辑节点：根据评审结果润色章节 |
| `human_review_node` | 人工审核节点 |
| `save_chapter_node` | 保存节点：将章节写入文件 |
| `next_chapter_node` | 下一章节点：推进章节计数 |
