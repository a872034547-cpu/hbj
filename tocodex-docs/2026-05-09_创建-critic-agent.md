# 任务备忘录：创建 CriticAgent

**日期**: 2026-05-09

## 概述

创建了质量评审代理 `CriticAgent`，用于对章节内容进行多维度评分和详细反馈，支持迭代改进循环。

## 新增文件

- `libriscribe/src/libriscribe/agents/critic_agent.py`

## 功能说明

`CriticAgent` 继承自 `Agent` 基类，包含以下核心方法：

| 方法 | 说明 |
|------|------|
| `execute(project_knowledge_base, chapter_number, chapter_content)` | 评审章节，返回 `ChapterReview` 对象 |
| `_build_review_prompt(...)` | 构建包含风格指南、角色档案、世界观、前序摘要、术语表的评审提示词 |
| `_parse_review_response(response)` | 从 LLM 响应中提取 JSON（支持代码块、裸 JSON、花括号提取三种容错策略） |
| `get_score(project_knowledge_base, chapter_number)` | 便捷方法，仅返回最新评审评分 |

### 评审维度（7 项）

1. 情节一致性 (Plot Consistency)
2. 角色一致性 (Character Consistency)
3. 写作质量 (Writing Quality)
4. 节奏把控 (Pacing)
5. 术语使用 (Terminology Usage)
6. 事实准确性 (Factual Accuracy)
7. 风格遵循度 (Style Adherence)

### 依赖关系

- `libriscribe.agents.agent_base.Agent`
- `libriscribe.knowledge_base.ProjectKnowledgeBase`, `ChapterReview`
- `libriscribe.utils.llm_client.LLMClient`
