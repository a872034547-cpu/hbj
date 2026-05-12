# 任务备忘录：创建 CitationAgent

**日期**: 2026-05-09
**任务**: 创建引用溯源代理 `CitationAgent`

## 变更文件

- `libriscribe/src/libriscribe/agents/citation_agent.py` — **新建**

## 概述

创建了 `CitationAgent` 类，继承自 `Agent` 基类，用于从章节内容中提取需要引用的句子并生成 GB/T 7714 格式的参考文献。

### 主要功能

1. **`execute()`** — 公开接口，接收项目知识库、章节号和章节内容，返回 `List[Citation]`
2. **`_extract_citation_candidates()`** — 使用 LLM 识别需要引用的事实性陈述、统计数据、直接引语和转述观点
3. **`_format_reference_gbt7714()`** — 使用 LLM 将候选引用格式化为 GB/T 7714-2015 标准
4. **`_fallback_format()`** — LLM 格式化失败时的回退格式化逻辑
5. **`_build_extraction_prompt()`** — 构建引用提取的 LLM 提示词

### 设计要点

- 使用 `generate_content_with_json_repair` 处理 LLM JSON 输出，提高解析可靠性
- 兼容两种 JSON 返回格式（直接列表或 `{"citations": [...]}` 包裹）
- 每条引用包含置信度评分（0-1）
- 异常处理覆盖每个环节，确保单条失败不影响整体流程
- `page` 字段设为 `None`，需手动补充
