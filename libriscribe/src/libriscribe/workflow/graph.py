# src/libriscribe/workflow/graph.py
"""LangGraph 主状态图定义"""

import logging
from libriscribe.workflow.state import BookWritingState
from libriscribe.workflow.nodes import (
    planner_node, research_node, writer_node, critic_node,
    editor_node, human_review_node, save_chapter_node, next_chapter_node,
)
from libriscribe.workflow.edges import should_iterate, needs_human_review, is_complete

logger = logging.getLogger(__name__)


def create_book_writing_graph(checkpointer=None):
    """创建书写作工作流图
    
    流程: START -> planner -> [每章循环]: research -> writer -> critic -> (条件) -> editor -> save -> human_review -> next_chapter -> END
    """
    try:
        from langgraph.graph import StateGraph, END
    except ImportError:
        raise ImportError("langgraph is required. Install with: pip install langgraph")

    workflow = StateGraph(BookWritingState)

    workflow.add_node("planner", planner_node)
    workflow.add_node("research", research_node)
    workflow.add_node("writer", writer_node)
    workflow.add_node("critic", critic_node)
    workflow.add_node("editor", editor_node)
    workflow.add_node("save", save_chapter_node)
    workflow.add_node("human_review", human_review_node)
    workflow.add_node("next_chapter", next_chapter_node)

    workflow.set_entry_point("planner")
    workflow.add_edge("planner", "research")
    workflow.add_edge("research", "writer")
    workflow.add_edge("writer", "critic")

    workflow.add_conditional_edges("critic", should_iterate, {
        "iterate": "writer",
        "edit": "editor",
        "save": "save",
    })

    workflow.add_edge("editor", "save")

    workflow.add_conditional_edges("save", needs_human_review, {
        "human": "human_review",
        "auto": "next_chapter",
    })

    workflow.add_edge("human_review", "next_chapter")

    workflow.add_conditional_edges("next_chapter", is_complete, {
        "next": "research",
        "complete": END,
    })

    graph = workflow.compile(
        checkpointer=checkpointer,
        interrupt_before=["human_review"] if checkpointer else None,
    )
    logger.info("Book writing graph compiled successfully")
    return graph


def run_book_writing(graph, initial_state: BookWritingState, config: dict = None):
    """运行书写作工作流"""
    final_state = None
    for event in graph.stream(initial_state, config=config):
        for node_name, node_output in event.items():
            logger.info(f"Node '{node_name}' completed")
            if isinstance(node_output, dict):
                for msg in node_output.get("messages", []):
                    logger.info(f"  {msg}")
            final_state = node_output
    return final_state