from __future__ import annotations

from pathlib import Path

import pytest

from libriscribe.knowledge_base import ProjectKnowledgeBase
from libriscribe.web.app import (
    _clean_path_text,
    _format_generation_error,
    _resolve_chapter_output_paths,
    _safe_chapter_number,
    _safe_section_filename_part,
)


def test_clean_path_text_removes_wrapping_quotes() -> None:
    assert _clean_path_text('"D:/work/project"') == "D:/work/project"
    assert _clean_path_text("'D:/work/project'") == "D:/work/project"


def test_safe_chapter_number_rejects_invalid_values() -> None:
    assert _safe_chapter_number("3") == 3
    with pytest.raises(ValueError, match="章节号无效"):
        _safe_chapter_number("abc")
    with pytest.raises(ValueError, match="必须大于 0"):
        _safe_chapter_number(0)


def test_safe_section_filename_part_sanitizes_windows_unsafe_text() -> None:
    assert _safe_section_filename_part("1.2:研究/路径?*") == "1.2_研究_路径"
    assert _safe_section_filename_part("CON") == "section_CON"
    with pytest.raises(ValueError, match="小节编号无效"):
        _safe_section_filename_part("////")


def test_resolve_chapter_output_paths_uses_project_file_parent_when_project_dir_missing(tmp_path: Path) -> None:
    project_file = tmp_path / "knowledge_base.json"
    project = ProjectKnowledgeBase(project_name="path-demo")

    chapter_path, output_path = _resolve_chapter_output_paths(project, str(project_file), "2", "2.1:非法/字符?")

    assert project.project_dir == str(tmp_path)
    assert chapter_path == tmp_path / "chapter_2.md"
    assert output_path == tmp_path / "chapter_2_section_2.1_非法_字符.md"


def test_format_generation_error_distinguishes_filesystem_error() -> None:
    message = _format_generation_error(OSError("[Errno 22] Invalid argument"))

    assert "文件系统错误" in message
    assert "不是普通模型/API错误" in message or "不是普通模型/API 错误" in message
