# 任务备忘录：创建 SummaryManager

**日期**: 2026-05-09

## 概要

创建了分层摘要管理器模块，用于每章生成后自动摘要，跨章时只传"前 N 章关键摘要 + 术语表"，解决长上下文问题。

## 变更文件

- `libriscribe/src/libriscribe/memory/summary_manager.py` — 新建，包含 `SummaryManager` 类，支持：
  - 章节摘要生成（LLM 或截断回退）
  - 全书摘要更新
  - 前 N 章摘要获取（用于注入 prompt）
  - JSON 文件持久化（`summaries.json`）
  - 与知识库的双向同步
