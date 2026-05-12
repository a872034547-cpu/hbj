# src/libriscribe/export/pdf_export.py
"""直接 PDF 导出，不依赖 Pandoc/XeLaTeX。"""

import logging
import re
from pathlib import Path
from typing import List

from libriscribe.utils.chinese_labels import format_chapter_label, strip_leading_chapter_heading

logger = logging.getLogger(__name__)


class PdfExporter:
    """使用 reportlab 直接生成 PDF。优先加载系统中文 TTF 字体，避免 fpdf 字符映射 -1 问题。"""

    def export(self, chapters: List[dict], output_path: str, title: str = "", author: str = "", genre: str = "", language: str = "English"):
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        try:
            self._export_with_reportlab(chapters, output, title, author, genre)
        except ImportError as exc:
            logger.warning("reportlab unavailable, falling back to fpdf: %s", exc)
            self._export_with_fpdf(chapters, output, title, author, genre)

        if not output.exists():
            raise RuntimeError("PDF 生成失败，输出文件不存在。")
        size = output.stat().st_size
        if size == 0:
            raise RuntimeError("PDF 生成失败，输出文件为空。")
        logger.info("PDF exported to: %s (%d bytes)", output, size)

    def _export_with_reportlab(self, chapters: List[dict], output: Path, title: str, author: str, genre: str) -> None:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfgen import canvas

        font_name = self._register_reportlab_font(pdfmetrics, TTFont)
        c = canvas.Canvas(str(output), pagesize=A4)
        width, height = A4
        # 参考用户提供的 Word：A4，上下约 2.54cm，左右约 3.17cm。
        margin_left = 90
        margin_right = 90
        margin_top = 72
        margin_bottom = 72
        usable_width = width - margin_left - margin_right
        y = height - margin_top

        def new_page():
            nonlocal y
            c.showPage()
            y = height - margin_top

        def write_lines(text: str, font_size: float = 10.5, leading: float = 17, bold_gap: float = 0, align: str = "left", first_indent: bool = False):
            nonlocal y
            c.setFont(font_name, font_size)
            wrap_width = usable_width - (font_size * 2 if first_indent else 0)
            for idx, line in enumerate(self._wrap_text(text, font_size, wrap_width)):
                if y < margin_bottom + leading:
                    new_page()
                    c.setFont(font_name, font_size)
                x = margin_left
                if align == "center":
                    c.drawCentredString(width / 2, y, line)
                else:
                    if first_indent and idx == 0:
                        x += font_size * 2
                    c.drawString(x, y, line)
                y -= leading
            if bold_gap:
                y -= bold_gap

        write_lines(title or "未命名书稿", font_size=36, leading=44, align="center")
        if author:
            write_lines(f"作者：{author}", font_size=12, leading=20, align="center")
        if genre:
            write_lines(genre, font_size=15, leading=22, align="center")
        new_page()

        for idx, chapter in enumerate(chapters):
            number = chapter.get("number") or chapter.get("chapter_number")
            if number:
                if int(number) < 1:
                    raise ValueError(f"Invalid chapter number for PDF export: {number}")
                ch_title_raw = chapter.get("title", "") or f"Chapter {number}"
                ch_title = chapter.get("display_title") or format_chapter_label(number, ch_title_raw)
                content = self._strip_leading_chapter_heading(chapter.get("content", "") or "", number, ch_title_raw)
            else:
                ch_title = chapter.get("display_title") or chapter.get("title", "未命名部分")
                content = self._strip_leading_part_heading(chapter.get("content", "") or "", ch_title)

            write_lines(ch_title, font_size=20, leading=28, bold_gap=8, align="center")
            for raw_line in content.splitlines():
                line = raw_line.strip()
                if not line:
                    y -= 8
                    if y < margin_bottom:
                        new_page()
                    continue
                if line.startswith("# "):
                    write_lines(line[2:].strip(), font_size=20, leading=28, bold_gap=6, align="center")
                elif line.startswith("## "):
                    write_lines(line[3:].strip(), font_size=15, leading=22, bold_gap=4, align="center")
                elif line.startswith("### "):
                    write_lines(line[4:].strip(), font_size=10.5, leading=17, bold_gap=2, first_indent=True)
                elif line.startswith("#### "):
                    write_lines(line[5:].strip(), font_size=10.5, leading=17, bold_gap=1, first_indent=True)
                else:
                    clean = re.sub(r"\*\*(.*?)\*\*", r"\1", line)
                    clean = re.sub(r"\*(.*?)\*", r"\1", clean)
                    write_lines(clean, font_size=10.5, leading=17, first_indent=True)
            if idx != len(chapters) - 1:
                new_page()

        c.save()

    def _register_reportlab_font(self, pdfmetrics, TTFont) -> str:
        font_path = self._find_chinese_ttf()
        pdfmetrics.registerFont(TTFont("CN", str(font_path)))
        logger.info("PDF reportlab font registered: %s", font_path)
        return "CN"

    def _wrap_text(self, text: str, font_size: int, usable_width: float) -> List[str]:
        """按近似字符宽度换行；中文按字符切分，英文保留空格。"""
        text = str(text).replace("\t", "    ")
        if not text:
            return [""]
        # 中文 TTF 下 reportlab 可逐字绘制；这里用保守宽度估算，避免超出页面。
        max_units = max(12, int(usable_width / (font_size * 0.58)))
        lines: List[str] = []
        current = ""
        units = 0.0
        for ch in text:
            ch_units = 0.55 if ord(ch) < 128 else 1.0
            if units + ch_units > max_units and current:
                lines.append(current.rstrip())
                current = ch
                units = ch_units
            else:
                current += ch
                units += ch_units
        if current:
            lines.append(current.rstrip())
        return lines or [""]

    def _find_chinese_ttf(self) -> Path:
        candidates = [
            Path("C:/Windows/Fonts/simhei.ttf"),
            Path("C:/Windows/Fonts/simfang.ttf"),
            Path("C:/Windows/Fonts/simkai.ttf"),
            Path("C:/Windows/Fonts/simsunb.ttf"),
            Path("C:/Windows/Fonts/SimsunExtG.ttf"),
            Path("C:/Windows/Fonts/arialuni.ttf"),
        ]
        for font_path in candidates:
            if font_path.exists():
                return font_path
        raise RuntimeError("未找到可用于 PDF 导出的中文 TTF 字体。请安装 simhei.ttf、simfang.ttf 或 arialuni.ttf 后重试。")

    def _export_with_fpdf(self, chapters: List[dict], output: Path, title: str, author: str, genre: str) -> None:
        try:
            from fpdf import FPDF
        except ImportError as exc:
            raise RuntimeError("缺少 PDF 依赖。请执行：pip install reportlab fpdf") from exc

        pdf = FPDF(format="A4")
        pdf.set_margins(31.7, 25.4, 31.7)
        pdf.set_auto_page_break(auto=True, margin=25.4)
        font_family = self._register_fpdf_font(pdf)
        pdf.add_page()

        pdf.set_font(font_family, "", 28)
        self._write_fpdf_multiline(pdf, title or "未命名书稿", h=16, align="C")
        if author:
            pdf.ln(4)
            pdf.set_font(font_family, "", 12)
            self._write_fpdf_multiline(pdf, author, h=8, align="C")
        if genre:
            pdf.ln(2)
            pdf.set_font(font_family, "", 11)
            self._write_fpdf_multiline(pdf, genre, h=8, align="C")
        pdf.add_page()

        for chapter in chapters:
            number = chapter.get("number") or chapter.get("chapter_number")
            if number:
                if int(number) < 1:
                    raise ValueError(f"Invalid chapter number for PDF export: {number}")
                chapter_title = chapter.get("title", "") or f"Chapter {number}"
                ch_title = chapter.get("display_title") or format_chapter_label(number, chapter_title)
                content = self._strip_leading_chapter_heading(chapter.get("content", "") or "", number, chapter_title)
            else:
                ch_title = chapter.get("display_title") or chapter.get("title", "未命名部分")
                content = self._strip_leading_part_heading(chapter.get("content", "") or "", ch_title)
            pdf.set_font(font_family, "", 20)
            self._write_fpdf_multiline(pdf, ch_title, h=12, align="C")
            pdf.ln(2)
            self._write_fpdf_markdown(pdf, content, font_family)
            pdf.add_page()

        try:
            pdf.output(str(output))
        except KeyError as exc:
            logger.exception("FPDF output failed with font/internal key error")
            raise RuntimeError("PDF 直接生成失败：fpdf 字体或字符映射不兼容。请安装 reportlab 后重试：pip install reportlab") from exc
        except Exception as exc:
            logger.exception("FPDF output failed")
            raise RuntimeError(f"PDF 直接生成失败：{exc}") from exc

    def _register_fpdf_font(self, pdf) -> str:
        font_path = self._find_chinese_ttf()
        try:
            pdf.add_font("CN", "", str(font_path), uni=True)
            logger.info("PDF fpdf font registered: %s", font_path)
            return "CN"
        except Exception as exc:
            raise RuntimeError(f"当前 fpdf 无法加载中文字体 {font_path}: {exc}。请安装 reportlab 后重试：pip install reportlab") from exc

    def _strip_leading_chapter_heading(self, content: str, number, title: str) -> str:
        return strip_leading_chapter_heading(content, number, title)

    def _strip_leading_part_heading(self, content: str, title: str) -> str:
        pattern = rf"^\s*#{{1,6}}\s*{re.escape(str(title).strip())}\s*\n+"
        return re.sub(pattern, "", str(content or ""), count=1)

    def _write_fpdf_markdown(self, pdf, content: str, font_family: str):
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line:
                pdf.ln(3)
                continue
            if line.startswith("# "):
                pdf.set_font(font_family, "", 20)
                self._write_fpdf_multiline(pdf, line[2:].strip(), h=11, align="C")
                pdf.ln(1)
            elif line.startswith("## "):
                pdf.set_font(font_family, "", 15)
                self._write_fpdf_multiline(pdf, line[3:].strip(), h=9, align="C")
                pdf.ln(1)
            elif line.startswith("### "):
                pdf.set_font(font_family, "", 10.5)
                self._write_fpdf_multiline(pdf, "　　" + line[4:].strip(), h=7)
                pdf.ln(1)
            elif line.startswith("#### "):
                pdf.set_font(font_family, "", 10.5)
                self._write_fpdf_multiline(pdf, "　　" + line[5:].strip(), h=7)
            else:
                pdf.set_font(font_family, "", 10.5)
                text = re.sub(r"\*\*(.*?)\*\*", r"\1", line)
                text = re.sub(r"\*(.*?)\*", r"\1", text)
                self._write_fpdf_multiline(pdf, "　　" + text, h=7)

    def _write_fpdf_multiline(self, pdf, text: str, h: float = 7, align: str = "L"):
        safe_text = str(text).replace("\t", "    ")
        pdf.multi_cell(0, h, safe_text, align=align)
