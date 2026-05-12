"""Export service facade for manuscript export formats.

This module intentionally avoids importing UI frameworks or exporter dependencies at
module import time. Concrete exporters are imported lazily only when their matching
export method is called.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Union

PathLike = Union[str, Path]


class ExportService:
    """Application service for exporting chapters to supported file formats."""

    MIN_EXPORT_BYTES = {
        ".docx": 512,
        ".pdf": 512,
        ".pptx": 512,
        ".tex": 128,
    }

    def validate_export_file(self, output_path: PathLike, *, expected_suffix: str = "") -> dict[str, Any]:
        """导出后基础体检：确认文件真实存在、后缀正确且不是空壳文件。"""
        path = Path(output_path)
        suffix = (expected_suffix or path.suffix).lower()
        exists = path.exists()
        size = path.stat().st_size if exists else 0
        min_bytes = self.MIN_EXPORT_BYTES.get(suffix, 1)
        errors: list[str] = []
        if not exists:
            errors.append("输出文件不存在")
        if exists and size < min_bytes:
            errors.append(f"输出文件过小：{size} bytes，低于 {min_bytes} bytes")
        if expected_suffix and path.suffix.lower() != expected_suffix.lower():
            errors.append(f"输出文件后缀异常：{path.suffix or '无后缀'}，期望 {expected_suffix}")
        return {
            "path": str(path),
            "exists": exists,
            "size": size,
            "suffix": path.suffix.lower(),
            "min_bytes": min_bytes,
            "status": "通过" if not errors else "失败",
            "errors": errors,
        }

    def _ensure_valid_export(self, output_path: PathLike, *, expected_suffix: str) -> Path:
        report = self.validate_export_file(output_path, expected_suffix=expected_suffix)
        if report["status"] != "通过":
            raise RuntimeError(f"导出文件体检失败：{'; '.join(report['errors'])}")
        return Path(output_path)

    def export_docx(
        self,
        chapters: Iterable[dict[str, Any]],
        output_path: PathLike,
        title: str = "",
        author: str = "",
        genre: str = "",
        language: str = "English",
    ) -> Path:
        """Export chapters to DOCX and return the output path."""
        from libriscribe.export.docx_export import DocxExporter

        path = Path(output_path)
        DocxExporter().export(
            list(chapters),
            str(path),
            title=title,
            author=author,
            genre=genre,
            language=language,
        )
        return self._ensure_valid_export(path, expected_suffix=".docx")

    def export_pdf(
        self,
        chapters: Iterable[dict[str, Any]],
        output_path: PathLike,
        title: str = "",
        author: str = "",
        genre: str = "",
        language: str = "English",
    ) -> Path:
        """Export chapters to PDF and return the output path."""
        from libriscribe.export.pdf_export import PdfExporter

        path = Path(output_path)
        PdfExporter().export(
            list(chapters),
            str(path),
            title=title,
            author=author,
            genre=genre,
            language=language,
        )
        return self._ensure_valid_export(path, expected_suffix=".pdf")

    def export_pptx(
        self,
        chapters: Iterable[dict[str, Any]],
        output_path: PathLike,
        title: str = "",
        author: str = "",
        genre: str = "",
        language: str = "简体中文",
    ) -> Path:
        """Export chapters to PPTX and return the output path."""
        from libriscribe.export.pptx_export import PptxExporter

        path = Path(output_path)
        PptxExporter().export(
            list(chapters),
            str(path),
            title=title,
            author=author,
            genre=genre,
            language=language,
        )
        return self._ensure_valid_export(path, expected_suffix=".pptx")

    def export_latex(
        self,
        chapters: Iterable[dict[str, Any]],
        output_path: PathLike,
        title: str = "",
        author: str = "",
        genre: str = "",
        language: str = "English",
    ) -> Path:
        """Export chapters to LaTeX and return the generated .tex path."""
        from libriscribe.export.latex_export import LatexExporter

        path = Path(output_path)
        tex_path = path if path.suffix == ".tex" else Path(f"{path}.tex")
        LatexExporter().export(
            list(chapters),
            str(path),
            title=title,
            author=author,
            genre=genre,
            language=language,
        )
        return self._ensure_valid_export(tex_path, expected_suffix=".tex")
