"""项目持久化服务。

该模块封装项目列表扫描、加载与保存逻辑，不依赖 Streamlit，便于 Web UI、
CLI 或未来 API 层复用。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from libriscribe.knowledge_base import ProjectKnowledgeBase

logger = logging.getLogger(__name__)


class ProjectService:
    """提供项目文件的轻量持久化能力。"""

    @staticmethod
    def list_projects(projects_root: Path) -> list[dict]:
        """扫描项目根目录并返回已有项目摘要。

        Args:
            projects_root: 项目根目录。每个子目录下应包含 ``knowledge_base.json``。

        Returns:
            项目摘要列表。每个元素包含 ``name``、``path``、``title``、``category``、
            ``updated_at`` 字段；单个项目加载失败不会影响其他项目扫描。
        """
        root = Path(projects_root)
        if not root.exists() or not root.is_dir():
            logger.info("Projects root does not exist or is not a directory: %s", root)
            return []

        projects: list[dict] = []
        for item in sorted(root.iterdir(), key=lambda path: path.name.lower()):
            if not item.is_dir():
                continue

            project_file = item / "knowledge_base.json"
            if not project_file.exists() or not project_file.is_file():
                continue

            project = ProjectService.load_project(project_file)
            if project is None:
                projects.append(
                    {
                        "name": item.name,
                        "path": str(project_file),
                        "title": item.name,
                        "category": "",
                        "updated_at": "",
                    }
                )
                continue

            projects.append(
                {
                    "name": project.project_name or item.name,
                    "path": str(project_file),
                    "title": project.title or item.name,
                    "category": project.category or "",
                    "updated_at": project.updated_at or "",
                }
            )

        return projects

    @staticmethod
    def load_project(project_file: Path) -> Optional[ProjectKnowledgeBase]:
        """从项目文件加载 ``ProjectKnowledgeBase``。

        Args:
            project_file: ``knowledge_base.json`` 文件路径。

        Returns:
            加载成功时返回项目知识库对象；文件不存在、解析失败或底层加载返回
            ``None`` 时返回 ``None``。
        """
        path = Path(project_file)
        if not path.exists() or not path.is_file():
            logger.warning("Project file does not exist or is not a file: %s", path)
            return None

        try:
            project = ProjectKnowledgeBase.load_from_file(str(path))
            if project is None:
                logger.warning("ProjectKnowledgeBase.load_from_file returned None: %s", path)
                return None

            project.project_dir = path.parent
            return project
        except Exception:
            logger.exception("Failed to load project from file: %s", path)
            return None

    @staticmethod
    def save_project(project: ProjectKnowledgeBase, project_file: Path) -> bool:
        """保存 ``ProjectKnowledgeBase`` 到项目文件。

        Args:
            project: 待保存的项目知识库对象。
            project_file: 目标 ``knowledge_base.json`` 文件路径。

        Returns:
            保存成功返回 ``True``，失败返回 ``False``。
        """
        path = Path(project_file)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            project.project_dir = path.parent
            project.save_to_file(str(path))
            return True
        except Exception:
            logger.exception("Failed to save project to file: %s", path)
            return False
