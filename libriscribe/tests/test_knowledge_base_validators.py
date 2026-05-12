from __future__ import annotations

from libriscribe.knowledge_base import ProjectKnowledgeBase, Worldbuilding


def test_project_knowledge_base_parses_range_and_plus_values() -> None:
    project = ProjectKnowledgeBase(
        project_name="validator-demo",
        num_characters="3-5",
        num_chapters="12+",
    )

    assert project.num_characters == (3, 5)
    assert project.num_chapters == 12


def test_project_knowledge_base_worldbuilding_validator_initializes_when_needed() -> None:
    project = ProjectKnowledgeBase(project_name="world-demo", worldbuilding_needed=True)

    assert isinstance(project.worldbuilding, Worldbuilding)


def test_project_knowledge_base_worldbuilding_validator_clears_when_not_needed() -> None:
    project = ProjectKnowledgeBase(
        project_name="world-demo",
        worldbuilding_needed=False,
        worldbuilding=Worldbuilding(geography="临时世界观"),
    )

    assert project.worldbuilding is None
