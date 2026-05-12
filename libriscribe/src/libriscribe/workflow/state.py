# src/libriscribe/workflow/state.py
"""LangGraph 状态定义

定义书写作工作流的全局状态。
"""

from typing import TypedDict, List, Dict, Any, Optional, Annotated
from operator import add


class BookWritingState(TypedDict):
    """书写作工作流状态"""
    # 项目信息
    project_name: str
    title: str
    genre: str
    category: str
    language: str
    description: str

    # 当前进度
    current_chapter: int
    total_chapters: int
    status: str  # "planning" | "writing" | "reviewing" | "editing" | "completed"

    # 内容
    chapter_content: str
    chapter_title: str
    chapter_summary: str

    # 评审
    review_result: Dict[str, Any]  # {score, issues, suggestions}
    iteration_count: int
    max_iterations: int

    # RAG 上下文
    rag_context: str  # 检索到的参考资料

    # 记忆
    terminology_context: str  # 术语表上下文
    previous_summaries: str  # 前文摘要
    style_guide: str  # 风格指南

    # 人机协作
    human_feedback: str
    needs_human_review: bool

    # 引用
    citations: List[Dict[str, Any]]

    # 错误处理
    error: str

    # 消息日志
    messages: Annotated[List[str], add]