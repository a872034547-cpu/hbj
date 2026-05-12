# src/libriscribe/workflow/edges.py
"""LangGraph 条件边逻辑"""

import logging
from libriscribe.workflow.state import BookWritingState
from libriscribe.settings import Settings

logger = logging.getLogger(__name__)


def should_iterate(state: BookWritingState) -> str:
    settings = Settings()
    threshold = settings.critic_score_threshold
    max_iter = state.get('max_iterations', settings.max_review_iterations)
    score = state.get('review_result', {}).get('score', 0)
    iteration = state.get('iteration_count', 0)

    if score < threshold and iteration < max_iter:
        return "iterate"
    elif score >= threshold:
        return "edit"
    else:
        return "save"


def needs_human_review(state: BookWritingState) -> str:
    if state.get('needs_human_review', False):
        return "human"
    if state.get('review_preference', 'AI') == 'Human':
        return "human"
    return "auto"


def is_complete(state: BookWritingState) -> str:
    if state.get('current_chapter', 1) >= state.get('total_chapters', 1):
        return "complete"
    return "next"