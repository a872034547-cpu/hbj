"""Outline service utilities.

This module contains read-only helpers for summarising the outline structure of a
project. It intentionally avoids persistence or UI dependencies so it can be used
from Streamlit pages, background jobs, and future API layers.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

from libriscribe.knowledge_base import Chapter, ChapterSection, ProjectKnowledgeBase


class OutlineService:
    """Service for outline-level statistics and chapter progress summaries."""

    def outline_summary(self, project: ProjectKnowledgeBase) -> dict:
        """Return aggregate outline statistics for a project.

        The summary includes:
        - ``chapters``: total chapter count.
        - ``sections``: total writing-unit count across all chapters.
        - ``leaf_sections``: count of sections without child sections.
        - ``target_words``: total planned words. Chapter target words are used
          first; when a chapter has no target word count, section targets are
          summed as a fallback.
        - ``chapter_status``: per-chapter status rows for dashboards and APIs.
        """
        chapters = self._ordered_chapters(project)
        chapter_status: List[Dict[str, Any]] = []

        total_sections = 0
        total_leaf_sections = 0
        total_target_words = 0

        for chapter_number, chapter in chapters:
            sections = list(getattr(chapter, "sections", []) or [])
            leaf_sections = self._leaf_sections(sections)
            chapter_target_words = self._chapter_target_words(chapter, sections)
            actual_words = int(getattr(chapter, "actual_word_count", 0) or 0)

            total_sections += len(sections)
            total_leaf_sections += len(leaf_sections)
            total_target_words += chapter_target_words

            completed_sections = sum(
                1
                for section in leaf_sections
                if (getattr(section, "status", "") or "").lower() in {"completed", "reviewed", "word_count_soft_fail"}
            )

            chapter_status.append(
                {
                    "chapter_number": chapter_number,
                    "title": getattr(chapter, "title", "") or "",
                    "status": getattr(chapter, "status", "pending") or "pending",
                    "sections": len(sections),
                    "leaf_sections": len(leaf_sections),
                    "completed_leaf_sections": completed_sections,
                    "target_words": chapter_target_words,
                    "actual_words": actual_words,
                    "completion_rate": self._completion_rate(actual_words, chapter_target_words),
                }
            )

        return {
            "chapters": len(chapters),
            "sections": total_sections,
            "leaf_sections": total_leaf_sections,
            "target_words": total_target_words,
            "chapter_status": chapter_status,
        }

    def _ordered_chapters(self, project: ProjectKnowledgeBase) -> List[Tuple[int, Chapter]]:
        """Return chapters sorted by numeric chapter number."""
        raw_chapters = getattr(project, "chapters", {}) or {}
        ordered: List[Tuple[int, Chapter]] = []

        items: Iterable[Tuple[Any, Chapter]]
        if isinstance(raw_chapters, dict):
            items = raw_chapters.items()
        else:
            items = enumerate(raw_chapters, start=1)

        for key, chapter in items:
            chapter_number = getattr(chapter, "chapter_number", None)
            if chapter_number is None:
                chapter_number = key
            ordered.append((self._safe_int(chapter_number), chapter))

        return sorted(ordered, key=lambda item: item[0])

    def _leaf_sections(self, sections: List[ChapterSection]) -> List[ChapterSection]:
        """Return sections that do not have child sections."""
        section_numbers = {
            str(getattr(section, "section_number", "") or "").strip()
            for section in sections
            if str(getattr(section, "section_number", "") or "").strip()
        }

        leaves: List[ChapterSection] = []
        for section in sections:
            section_number = str(getattr(section, "section_number", "") or "").strip()
            if not section_number:
                leaves.append(section)
                continue

            prefix = f"{section_number}."
            has_child = any(
                candidate != section_number and candidate.startswith(prefix)
                for candidate in section_numbers
            )
            if not has_child:
                leaves.append(section)

        return leaves

    def _chapter_target_words(self, chapter: Chapter, sections: List[ChapterSection]) -> int:
        """Return chapter target words with section-level fallback."""
        chapter_words = int(getattr(chapter, "word_count", 0) or 0)
        if chapter_words > 0:
            return chapter_words
        return sum(int(getattr(section, "word_count", 0) or 0) for section in sections)

    def _completion_rate(self, actual_words: int, target_words: int) -> float:
        """Return word-count completion rate as a percentage."""
        if target_words <= 0:
            return 0.0
        return round(min(max(actual_words / target_words * 100, 0.0), 100.0), 1)

    def _safe_int(self, value: Any) -> int:
        """Convert a chapter number-like value to int without raising."""
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
