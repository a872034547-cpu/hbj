from __future__ import annotations

from libriscribe.knowledge_base import Chapter, ChapterSection, ProjectKnowledgeBase
from libriscribe.services.quality_service import QualityService


def test_quality_service_summarizes_project_metrics() -> None:
    project = ProjectKnowledgeBase(project_name="demo", title="Demo", category="专著", genre="测试")
    project.chapters[1] = Chapter(
        chapter_number=1,
        title="第一章",
        sections=[
            ChapterSection(section_number="1.1", title="背景", level=2, status="completed"),
            ChapterSection(section_number="1.2", title="问题", level=2, status="pending"),
        ],
    )

    summary = QualityService().summarize_project_quality(project)

    assert summary["chapters"] == 1
    assert summary["writing_units"] == 2
    assert summary["completed_units"] == 1
    assert 0 <= summary["completion_score"] <= 100
