#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
结构化 JSON 专著导出为专业排版 Word 文档。

设计目标：
1. 仅依赖 python-docx；
2. 所有版式由代码硬控制，不受输入内容中的 Markdown 或临时格式影响；
3. 支持封面、目录、前言、正文、结语、参考文献；
4. 支持章—节—三级—四级四层标题；
5. 提供 CLI 与可被 Web 端/测试导入的函数接口。

命令行用法：
    python scripts/export_structured_json_to_docx.py path/to/book.json

输出：
    与输入 JSON 同名的 .docx 文件。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

from docx import Document
from docx.document import Document as DocumentObject
from docx.enum.section import WD_SECTION
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

# -----------------------------------------------------------------------------
# 全局格式常量：所有硬性版式要求集中在此，便于维护。
# -----------------------------------------------------------------------------

PAGE_WIDTH_CM = 21.0
PAGE_HEIGHT_CM = 29.7
MARGIN_TOP_CM = 2.54
MARGIN_BOTTOM_CM = 2.54
MARGIN_LEFT_CM = 3.18
MARGIN_RIGHT_CM = 3.18

CHINESE_BODY_FONT = "宋体"
WESTERN_BODY_FONT = "Times New Roman"
CHINESE_HEADING_FONT = "黑体"
WESTERN_HEADING_FONT = "Times New Roman"

BODY_SIZE_PT = 12
BODY_LINE_SPACING_PT = 22
FIRST_LINE_INDENT_PT = 24
REFERENCE_SIZE_PT = 10.5
REFERENCE_HANGING_PT = 24

# 不使用 Word 内置 Heading 1/2/3/4 作为正文标题样式。
# 部分 Word/WPS 环境会把内置 Heading 样式自动套入模板多级列表，导致明明脚本写的是
# “第一章 / 第一节 / 一、/（一）”，打开后却显示成“第1章 / 第1节 / 1.1”。
# 因此这里改用自定义样式，并通过 outlineLvl 参与目录生成。
STYLE_CHAPTER_HEADING = "Book Chapter Heading"
STYLE_SECTION_HEADING = "Book Section Heading"
STYLE_LEVEL3_HEADING = "Book Level3 Heading"
STYLE_LEVEL4_HEADING = "Book Level4 Heading"
STYLE_UNNUMBERED_HEADING = "Book Unnumbered Heading"
HEADING_STYLE_NAMES = {
    STYLE_CHAPTER_HEADING,
    STYLE_SECTION_HEADING,
    STYLE_LEVEL3_HEADING,
    STYLE_LEVEL4_HEADING,
    STYLE_UNNUMBERED_HEADING,
}

TOC_FIELD_CODE = r'TOC \o "1-4" \h \z \u'

# Markdown/HTML 清理表达式。输入内容可能来自模型或 Markdown 编辑器，导出前统一净化。
MARKDOWN_PATTERNS = [
    (re.compile(r"```.*?```", re.DOTALL), ""),
    (re.compile(r"`([^`]*)`"), r"\1"),
    (re.compile(r"!\[[^\]]*\]\([^)]*\)"), ""),
    (re.compile(r"\[([^\]]+)\]\([^)]*\)"), r"\1"),
    (re.compile(r"(\*\*|__)(.*?)\1"), r"\2"),
    (re.compile(r"(?<!\*)\*(?!\*)(.*?)\*(?!\*)"), r"\1"),
    (re.compile(r"(?<!_)_(?!_)(.*?)_(?!_)"), r"\1"),
    (re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE), ""),
    (re.compile(r"^\s{0,3}>\s?", re.MULTILINE), ""),
    (re.compile(r"^\s*[-*+]\s+", re.MULTILINE), ""),
    (re.compile(r"^\s*\d+[.)]\s+", re.MULTILINE), ""),
    (re.compile(r"<[^>]+>"), ""),
]


# -----------------------------------------------------------------------------
# OXML 基础工具
# -----------------------------------------------------------------------------


def _get_or_add(parent, tag: str):
    """获取 parent 下的第一个 tag 子元素；不存在则创建。"""
    child = parent.find(qn(tag))
    if child is None:
        child = OxmlElement(tag)
        parent.append(child)
    return child


def _remove_all(parent, tag: str) -> None:
    """删除 parent 下所有 tag 子元素。"""
    for child in list(parent.findall(qn(tag))):
        parent.remove(child)


def set_run_font(run, chinese_font: str, western_font: str, size_pt: float, bold: bool | None = None) -> None:
    """同时设置中文字体、英文字体、字号和加粗。"""
    run.font.name = western_font
    run.font.size = Pt(size_pt)
    if bold is not None:
        run.bold = bold
    r_pr = run._element.get_or_add_rPr()
    r_fonts = _get_or_add(r_pr, "w:rFonts")
    r_fonts.set(qn("w:eastAsia"), chinese_font)
    r_fonts.set(qn("w:ascii"), western_font)
    r_fonts.set(qn("w:hAnsi"), western_font)
    r_fonts.set(qn("w:cs"), western_font)


def set_style_font(style, chinese_font: str, western_font: str, size_pt: float, bold: bool | None = None) -> None:
    """设置段落样式的中西文字体、字号和加粗。"""
    style.font.name = western_font
    style.font.size = Pt(size_pt)
    if bold is not None:
        style.font.bold = bold
    r_pr = style.element.get_or_add_rPr()
    r_fonts = _get_or_add(r_pr, "w:rFonts")
    r_fonts.set(qn("w:eastAsia"), chinese_font)
    r_fonts.set(qn("w:ascii"), western_font)
    r_fonts.set(qn("w:hAnsi"), western_font)
    r_fonts.set(qn("w:cs"), western_font)


def set_style_language(style, lang: str = "zh-CN") -> None:
    """设置样式语言，减少 Word 自动套用英文字体或拼写检查造成的版式漂移。"""
    r_pr = style.element.get_or_add_rPr()
    lang_el = _get_or_add(r_pr, "w:lang")
    lang_el.set(qn("w:val"), lang)
    lang_el.set(qn("w:eastAsia"), lang)


def set_document_language(document: DocumentObject, lang: str = "zh-CN") -> None:
    """设置文档默认语言。"""
    settings = document.settings.element
    theme_lang = settings.find(qn("w:themeFontLang"))
    if theme_lang is None:
        theme_lang = OxmlElement("w:themeFontLang")
        settings.append(theme_lang)
    theme_lang.set(qn("w:val"), lang)
    theme_lang.set(qn("w:eastAsia"), lang)


def set_keep_options(style, *, keep_next: bool = False, keep_lines: bool = False, widow_control: bool = True) -> None:
    """控制标题/正文分页行为。

    关键修复：同时移除 keepNext、keepLines 和 pageBreakBefore。三级/四级标题很短，
    若保留“与下段同页/段中不分页”，Word/WPS 会在当前页还剩较大空白时把
    “（二）”等子节整体推到下一页，造成用户看到的大块空白。
    """
    p_pr = style.element.get_or_add_pPr()
    _remove_all(p_pr, "w:keepNext")
    _remove_all(p_pr, "w:keepLines")
    _remove_all(p_pr, "w:pageBreakBefore")
    _remove_all(p_pr, "w:widowControl")
    if keep_next:
        p_pr.append(OxmlElement("w:keepNext"))
    if keep_lines:
        p_pr.append(OxmlElement("w:keepLines"))
    widow = OxmlElement("w:widowControl")
    widow.set(qn("w:val"), "1" if widow_control else "0")
    p_pr.append(widow)


def set_style_outline_level(style, level: int | None) -> None:
    """设置自定义标题样式的大纲级别，让目录识别但不触发内置标题自动编号。"""
    p_pr = style.element.get_or_add_pPr()
    _remove_all(p_pr, "w:outlineLvl")
    if level is not None:
        outline = OxmlElement("w:outlineLvl")
        outline.set(qn("w:val"), str(level))
        p_pr.append(outline)


def ensure_paragraph_style(document: DocumentObject, style_name: str, base_style: str = "Normal"):
    """获取或创建段落样式。"""
    try:
        return document.styles[style_name]
    except KeyError:
        style = document.styles.add_style(style_name, WD_STYLE_TYPE.PARAGRAPH)
        style.base_style = document.styles[base_style]
        return style


# -----------------------------------------------------------------------------
# 分节、页码、页眉页脚
# -----------------------------------------------------------------------------


def set_page_layout(section) -> None:
    """对单个 section 设置 A4 与页边距。"""
    section.page_width = Cm(PAGE_WIDTH_CM)
    section.page_height = Cm(PAGE_HEIGHT_CM)
    section.top_margin = Cm(MARGIN_TOP_CM)
    section.bottom_margin = Cm(MARGIN_BOTTOM_CM)
    section.left_margin = Cm(MARGIN_LEFT_CM)
    section.right_margin = Cm(MARGIN_RIGHT_CM)


def set_section_page_number(section, *, fmt: str = "decimal", start: int | None = None) -> None:
    """通过 XML 设置节页码格式与可选起始页码。"""
    sect_pr = section._sectPr
    pg_num_type = sect_pr.find(qn("w:pgNumType"))
    if pg_num_type is None:
        pg_num_type = OxmlElement("w:pgNumType")
        sect_pr.append(pg_num_type)
    pg_num_type.set(qn("w:fmt"), fmt)
    if start is None:
        if qn("w:start") in pg_num_type.attrib:
            del pg_num_type.attrib[qn("w:start")]
    else:
        pg_num_type.set(qn("w:start"), str(start))


def unlink_section_headers_footers(section) -> None:
    """取消当前节页眉页脚与上一节链接。"""
    for container in (
        section.header,
        section.footer,
        section.even_page_header,
        section.even_page_footer,
        section.first_page_header,
        section.first_page_footer,
    ):
        container.is_linked_to_previous = False


def clear_header_footer(container) -> None:
    """清空页眉或页脚容器内容。"""
    for paragraph in container.paragraphs:
        paragraph.clear()


def add_field(paragraph, field_code: str, placeholder: str = "") -> None:
    """在段落中插入 Word 域，例如 PAGE、TOC、STYLEREF。"""
    begin_run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    begin_run._r.append(begin)

    instr_run = paragraph.add_run()
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = f" {field_code} "
    instr_run._r.append(instr)

    separate_run = paragraph.add_run()
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    separate_run._r.append(separate)

    if placeholder:
        placeholder_run = paragraph.add_run(placeholder)
        set_run_font(placeholder_run, CHINESE_BODY_FONT, WESTERN_BODY_FONT, REFERENCE_SIZE_PT)

    end_run = paragraph.add_run()
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    end_run._r.append(end)


def add_page_number(footer, alignment) -> None:
    """向页脚插入 PAGE 域。"""
    clear_header_footer(footer)
    paragraph = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
    paragraph.alignment = alignment
    add_field(paragraph, "PAGE", "1")


def set_text_header(header, text: str, alignment=WD_ALIGN_PARAGRAPH.CENTER) -> None:
    """设置固定文本页眉。"""
    clear_header_footer(header)
    paragraph = header.paragraphs[0] if header.paragraphs else header.add_paragraph()
    paragraph.alignment = alignment
    run = paragraph.add_run(clean_text(text))
    set_run_font(run, CHINESE_BODY_FONT, WESTERN_BODY_FONT, REFERENCE_SIZE_PT)


def set_styleref_header(header) -> None:
    """设置当前章页眉：使用 STYLEREF 自动引用当前页最近的自定义章标题。"""
    clear_header_footer(header)
    paragraph = header.paragraphs[0] if header.paragraphs else header.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    add_field(paragraph, f'STYLEREF "{STYLE_CHAPTER_HEADING}"', "当前章")


def configure_front_footer(section) -> None:
    """目录/前言节：空页眉，页脚居中小写罗马页码。"""
    unlink_section_headers_footers(section)
    for header in (section.header, section.even_page_header, section.first_page_header):
        clear_header_footer(header)
    add_page_number(section.footer, WD_ALIGN_PARAGRAPH.CENTER)
    add_page_number(section.even_page_footer, WD_ALIGN_PARAGRAPH.CENTER)
    add_page_number(section.first_page_footer, WD_ALIGN_PARAGRAPH.CENTER)


def configure_body_headers_footers(section, book_title: str) -> None:
    """正文/结语/参考文献：奇数页当前章，偶数页书名；奇右偶左页码。"""
    unlink_section_headers_footers(section)
    set_styleref_header(section.header)
    set_text_header(section.even_page_header, book_title)
    clear_header_footer(section.first_page_header)
    add_page_number(section.footer, WD_ALIGN_PARAGRAPH.RIGHT)
    add_page_number(section.even_page_footer, WD_ALIGN_PARAGRAPH.LEFT)
    add_page_number(section.first_page_footer, WD_ALIGN_PARAGRAPH.RIGHT)


# -----------------------------------------------------------------------------
# 样式初始化
# -----------------------------------------------------------------------------


def _set_pf(style, *, alignment, first_indent=0, left_indent=0, before=0, after=0, spacing=BODY_LINE_SPACING_PT, exact=True) -> None:
    """统一设置段落格式。"""
    pf = style.paragraph_format
    pf.alignment = alignment
    pf.first_line_indent = Pt(first_indent)
    pf.left_indent = Pt(left_indent)
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    pf.line_spacing = Pt(spacing)
    pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY if exact else WD_LINE_SPACING.SINGLE


def initialize_styles(document: DocumentObject) -> None:
    """初始化所有固定样式。

    说明：标题编号改为写入纯文本前缀，不再依赖 Word 多级列表。
    这样可以避免不同 Word/WPS 版本把中文多级编号错误显示成“第 1 章 / 第 1 节 / 1.1”，
    也避免编号域刷新后出现不可控的缩进和分页漂移。
    """
    set_document_language(document)

    # 全局设置奇偶页不同。python-docx 1.2.0 支持该设置。
    document.settings.odd_and_even_pages_header_footer = True

    for section in document.sections:
        set_page_layout(section)

    styles = document.styles

    normal = styles["Normal"]
    set_style_font(normal, CHINESE_BODY_FONT, WESTERN_BODY_FONT, BODY_SIZE_PT, False)
    _set_pf(normal, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, first_indent=FIRST_LINE_INDENT_PT, before=0, after=0)
    set_keep_options(normal, keep_next=False, keep_lines=False, widow_control=True)
    set_style_language(normal)

    h1 = ensure_paragraph_style(document, STYLE_CHAPTER_HEADING, "Normal")
    set_style_font(h1, CHINESE_HEADING_FONT, WESTERN_HEADING_FONT, 16, True)
    _set_pf(h1, alignment=WD_ALIGN_PARAGRAPH.CENTER, before=24, after=12, spacing=14, exact=False)
    set_keep_options(h1, keep_next=False, keep_lines=False, widow_control=True)
    set_style_outline_level(h1, 0)
    set_style_language(h1)

    h2 = ensure_paragraph_style(document, STYLE_SECTION_HEADING, "Normal")
    set_style_font(h2, CHINESE_HEADING_FONT, WESTERN_HEADING_FONT, 14, True)
    _set_pf(h2, alignment=WD_ALIGN_PARAGRAPH.CENTER, before=18, after=6, spacing=14, exact=False)
    set_keep_options(h2, keep_next=False, keep_lines=False, widow_control=True)
    set_style_outline_level(h2, 1)
    set_style_language(h2)

    h3 = ensure_paragraph_style(document, STYLE_LEVEL3_HEADING, "Normal")
    set_style_font(h3, CHINESE_HEADING_FONT, WESTERN_HEADING_FONT, 12, False)
    _set_pf(h3, alignment=WD_ALIGN_PARAGRAPH.LEFT, first_indent=FIRST_LINE_INDENT_PT, before=12, after=6, spacing=12, exact=False)
    set_keep_options(h3, keep_next=False, keep_lines=False, widow_control=True)
    set_style_outline_level(h3, 2)
    set_style_language(h3)

    h4 = ensure_paragraph_style(document, STYLE_LEVEL4_HEADING, "Normal")
    set_style_font(h4, CHINESE_HEADING_FONT, WESTERN_HEADING_FONT, 12, False)
    _set_pf(h4, alignment=WD_ALIGN_PARAGRAPH.LEFT, first_indent=FIRST_LINE_INDENT_PT, before=6, after=3, spacing=12, exact=False)
    set_keep_options(h4, keep_next=False, keep_lines=False, widow_control=True)
    set_style_outline_level(h4, 3)
    set_style_language(h4)

    unnumbered = ensure_paragraph_style(document, STYLE_UNNUMBERED_HEADING, "Normal")
    set_style_font(unnumbered, CHINESE_HEADING_FONT, WESTERN_HEADING_FONT, 16, True)
    _set_pf(unnumbered, alignment=WD_ALIGN_PARAGRAPH.CENTER, before=24, after=12, spacing=14, exact=False)
    set_keep_options(unnumbered, keep_next=False, keep_lines=False, widow_control=True)
    set_style_outline_level(unnumbered, 0)
    # 明确去掉编号，避免继承模板 numPr。
    _remove_all(unnumbered.element.get_or_add_pPr(), "w:numPr")
    set_style_language(unnumbered)

    reference = ensure_paragraph_style(document, "Reference", "Normal")
    set_style_font(reference, CHINESE_BODY_FONT, WESTERN_BODY_FONT, REFERENCE_SIZE_PT, False)
    _set_pf(reference, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, first_indent=-REFERENCE_HANGING_PT, left_indent=REFERENCE_HANGING_PT, before=0, after=0)
    set_keep_options(reference, keep_next=False, keep_lines=False, widow_control=True)
    set_style_language(reference)

    cover_title = ensure_paragraph_style(document, "Cover Title", "Normal")
    set_style_font(cover_title, CHINESE_HEADING_FONT, WESTERN_HEADING_FONT, 26, True)
    _set_pf(cover_title, alignment=WD_ALIGN_PARAGRAPH.CENTER, before=180, after=36, spacing=26, exact=False)

    cover_author = ensure_paragraph_style(document, "Cover Author", "Normal")
    set_style_font(cover_author, CHINESE_BODY_FONT, WESTERN_BODY_FONT, 18, False)
    _set_pf(cover_author, alignment=WD_ALIGN_PARAGRAPH.CENTER, before=24, after=0, spacing=18, exact=False)

    # 不创建、不绑定 Word 自动多级列表；所有标题编号由 write_chapter() 写成普通文本。
    # 同时清理内置 Heading 样式，防止外部模板残留列表编号污染；实际正文不再使用它们。
    for style_name in ("Heading 1", "Heading 2", "Heading 3", "Heading 4"):
        _remove_all(styles[style_name].element.get_or_add_pPr(), "w:numPr")
        _remove_all(styles[style_name].element.get_or_add_pPr(), "w:pageBreakBefore")
    for style_name in HEADING_STYLE_NAMES:
        _remove_all(styles[style_name].element.get_or_add_pPr(), "w:numPr")
        _remove_all(styles[style_name].element.get_or_add_pPr(), "w:pageBreakBefore")
    return None


# -----------------------------------------------------------------------------
# 文本预处理与内容标准化
# -----------------------------------------------------------------------------


def add_cjk_spacing(text: str) -> str:
    """在中文与英文/数字之间插入 U+2009 thin space。"""
    text = re.sub(r"([\u4e00-\u9fff])([A-Za-z0-9])", lambda match: f"{match.group(1)}\u2009{match.group(2)}", text)
    text = re.sub(r"([A-Za-z0-9])([\u4e00-\u9fff])", lambda match: f"{match.group(1)}\u2009{match.group(2)}", text)
    return text


def clean_text(value: Any) -> str:
    """清理 Markdown/HTML/多余空白，并插入中英数字细空格。"""
    text = "" if value is None else str(value)
    text = text.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n")
    for pattern, replacement in MARKDOWN_PATTERNS:
        text = pattern.sub(replacement, text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return add_cjk_spacing(text.strip())


def iter_paragraph_texts(content: Any) -> Iterable[str]:
    """把字符串、列表、字典等输入统一展开为段落。"""
    if content is None:
        return
    if isinstance(content, str):
        for part in re.split(r"\n\s*\n", content):
            cleaned = clean_text(part)
            if cleaned:
                yield cleaned
        return
    if isinstance(content, (list, tuple)):
        for item in content:
            yield from iter_paragraph_texts(item)
        return
    if isinstance(content, dict):
        for key in ("content", "text", "paragraphs"):
            if key in content:
                yield from iter_paragraph_texts(content[key])
        return
    cleaned = clean_text(content)
    if cleaned:
        yield cleaned


def int_to_chinese(number: int) -> str:
    """把正整数转换为中文序号，覆盖常见章节数量。"""
    digits = "零一二三四五六七八九"
    if number <= 0:
        return str(number)
    if number < 10:
        return digits[number]
    if number == 10:
        return "十"
    if number < 20:
        return "十" + digits[number % 10]
    if number < 100:
        tens, ones = divmod(number, 10)
        return digits[tens] + "十" + (digits[ones] if ones else "")
    return str(number)


def strip_existing_heading_number(value: Any) -> str:
    """移除输入标题里已有的章/节/一、/（一）/1.1 等编号，避免重复编号。

    这里先不调用 clean_text()，避免“第1章”被中英数细空格规则改成“第 1 章”后
    影响编号识别；去掉既有编号后，再由 add_clean_paragraph() 统一清洗和补细空格。
    """
    text = "" if value is None else str(value)
    text = text.replace("\ufeff", "").replace("\u2009", " ").strip()
    for pattern, replacement in MARKDOWN_PATTERNS:
        text = pattern.sub(replacement, text)
    text = re.sub(r"[ \t]+", " ", text).strip()
    patterns = [
        r"^第\s*[一二三四五六七八九十百千万零〇两\d]+\s*[章节篇部]\s*[、.．:：\-—]*\s*",
        r"^[一二三四五六七八九十百千万零〇两]+\s*[、.．]\s*",
        r"^（\s*[一二三四五六七八九十百千万零〇两\d]+\s*）\s*",
        r"^\(\s*[一二三四五六七八九十百千万零〇两\d]+\s*\)\s*",
        r"^\d+(?:\.\d+)*\s*[、.．)]?\s*",
    ]
    for pattern in patterns:
        text = re.sub(pattern, "", text)
    return clean_text(text) or "未命名标题"


def clean_reference_text(value: Any) -> str:
    """按专著参考文献格式清理条目：去标题行、去 DOI/URL 链接、压缩多余空白。"""
    text = clean_text(value)
    if not text:
        return ""
    if re.fullmatch(r"#{0,6}\s*参考文献\s*", text):
        return ""
    text = re.sub(r"【\s*(?:DOI|doi|链接|URL|url|OpenAlex|检索链接)\s*[:：]?\s*[^】]*】", "", text)
    text = re.sub(r"\b(?:DOI|doi)\s*[:：]\s*10\.\S+", "", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"(?:Available at|Retrieved from)\s*[:：]?\s*\S+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+([,.;，。；])", r"\1", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip(" ；;，,")


def normalize_references(references: Any) -> list[str]:
    """把参考文献字段统一整理为字符串列表，并去掉不适合专著参考文献区的链接信息。"""
    refs: list[str] = []
    if references is None:
        return refs
    if isinstance(references, str):
        candidates = [line.strip() for line in references.splitlines() if line.strip()]
    elif isinstance(references, (list, tuple)):
        candidates = []
        for item in references:
            if isinstance(item, dict):
                candidates.append(item.get("formatted_ref") or item.get("text") or item.get("title") or "")
            else:
                candidates.extend(str(item).splitlines())
    else:
        candidates = [str(references)]
    for candidate in candidates:
        cleaned = clean_reference_text(candidate)
        if cleaned:
            refs.append(cleaned)
    return refs


# -----------------------------------------------------------------------------
# 内容写入
# -----------------------------------------------------------------------------


def add_clean_paragraph(document: DocumentObject, text: Any, style_name: str = "Normal"):
    """添加段落并强制套用样式和运行字体。"""
    paragraph = document.add_paragraph(style=style_name)
    run = paragraph.add_run(clean_text(text))
    if style_name in HEADING_STYLE_NAMES or style_name.startswith("Heading"):
        set_run_font(run, CHINESE_HEADING_FONT, WESTERN_HEADING_FONT, paragraph.style.font.size.pt if paragraph.style.font.size else BODY_SIZE_PT, paragraph.style.font.bold)
    elif style_name == "Reference":
        set_run_font(run, CHINESE_BODY_FONT, WESTERN_BODY_FONT, REFERENCE_SIZE_PT, False)
    else:
        set_run_font(run, CHINESE_BODY_FONT, WESTERN_BODY_FONT, BODY_SIZE_PT, False)
    # 清除可能由模板或内置 Heading 样式继承来的自动编号和分页控制，确保标题文本和分页完全由脚本控制。
    p_pr = paragraph._p.get_or_add_pPr()
    _remove_all(p_pr, "w:numPr")
    _remove_all(p_pr, "w:pageBreakBefore")
    _remove_all(p_pr, "w:keepNext")
    _remove_all(p_pr, "w:keepLines")
    return paragraph


def write_content_paragraphs(document: DocumentObject, content: Any) -> None:
    """写入正文段落。"""
    for paragraph_text in iter_paragraph_texts(content):
        add_clean_paragraph(document, paragraph_text, "Normal")


def write_cover(document: DocumentObject, data: dict[str, Any]) -> None:
    """写入封面。封面不插入页码。"""
    add_clean_paragraph(document, data.get("title", "未命名专著"), "Cover Title")
    if data.get("author"):
        add_clean_paragraph(document, data.get("author"), "Cover Author")


def write_toc(document: DocumentObject) -> None:
    """写入目录标题与目录域。"""
    add_clean_paragraph(document, "目录", STYLE_UNNUMBERED_HEADING)
    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    add_field(paragraph, TOC_FIELD_CODE, "请在 Word 中右键更新域以生成目录")


def write_preface(document: DocumentObject, preface: Any) -> bool:
    """写入前言；无内容返回 False。"""
    paragraphs = list(iter_paragraph_texts(preface))
    if not paragraphs:
        return False
    add_clean_paragraph(document, "前言", STYLE_UNNUMBERED_HEADING)
    for text in paragraphs:
        add_clean_paragraph(document, text, "Normal")
    return True


def _level3_items(section: dict[str, Any]) -> list[dict[str, Any]]:
    """读取 level3，兼容旧版 subsections 字段。"""
    items = section.get("level3")
    if items is None:
        items = section.get("subsections", [])
    return [item for item in (items or []) if isinstance(item, dict)]


def _level4_items(level3: dict[str, Any]) -> list[dict[str, Any]]:
    """读取 level4。"""
    return [item for item in (level3.get("level4") or []) if isinstance(item, dict)]


def write_reference_items(document: DocumentObject, references: Any) -> None:
    """写入参考文献条目。"""
    for reference in normalize_references(references):
        add_clean_paragraph(document, reference, "Reference")


def write_chapter(document: DocumentObject, chapter: dict[str, Any], chapter_index: int) -> None:
    """写入单章：chapter/section/level3/level4 分别对应 Heading 1-4。

    标题编号使用纯文本硬写入：第一章、第一节、一、（一）。
    输入 heading 只作为标题正文，不允许携带或触发 Word 自动编号。
    """
    add_clean_paragraph(document, f"第{int_to_chinese(chapter_index)}章　{strip_existing_heading_number(chapter.get('heading') or '')}", STYLE_CHAPTER_HEADING)
    write_content_paragraphs(document, chapter.get("content"))

    for section_index, section in enumerate(chapter.get("sections", []) or [], start=1):
        if not isinstance(section, dict):
            continue
        add_clean_paragraph(document, f"第{int_to_chinese(section_index)}节　{strip_existing_heading_number(section.get('heading') or '未命名小节')}", STYLE_SECTION_HEADING)
        write_content_paragraphs(document, section.get("content"))

        for level3_index, level3 in enumerate(_level3_items(section), start=1):
            add_clean_paragraph(document, f"{int_to_chinese(level3_index)}、{strip_existing_heading_number(level3.get('heading') or '未命名三级标题')}", STYLE_LEVEL3_HEADING)
            write_content_paragraphs(document, level3.get("content"))

            for level4_index, level4 in enumerate(_level4_items(level3), start=1):
                add_clean_paragraph(document, f"（{int_to_chinese(level4_index)}）{strip_existing_heading_number(level4.get('heading') or '未命名四级标题')}", STYLE_LEVEL4_HEADING)
                write_content_paragraphs(document, level4.get("content"))

    chapter_refs = normalize_references(chapter.get("references"))
    if chapter_refs:
        add_clean_paragraph(document, "本章参考文献", STYLE_SECTION_HEADING)
        write_reference_items(document, chapter_refs)


def write_unnumbered_section(document: DocumentObject, title: str, content: Any) -> bool:
    """写入结语等不编号一级标题章节。"""
    paragraphs = list(iter_paragraph_texts(content))
    if not paragraphs:
        return False
    add_clean_paragraph(document, title, STYLE_UNNUMBERED_HEADING)
    for text in paragraphs:
        add_clean_paragraph(document, text, "Normal")
    return True


def write_global_references(document: DocumentObject, references: Any) -> bool:
    """写入全书参考文献。"""
    refs = normalize_references(references)
    if not refs:
        return False
    add_clean_paragraph(document, "参考文献", STYLE_UNNUMBERED_HEADING)
    write_reference_items(document, refs)
    return True


def normalize_all_runs(document: DocumentObject) -> None:
    """保存前再次统一运行字体，降低 Word 自动替换字体概率。"""
    for paragraph in document.paragraphs:
        style_name = paragraph.style.name if paragraph.style is not None else "Normal"
        for run in paragraph.runs:
            if not run.text:
                continue
            if style_name in HEADING_STYLE_NAMES or style_name.startswith("Heading") or style_name.startswith("Cover Title"):
                size = paragraph.style.font.size.pt if paragraph.style.font.size else 12
                set_run_font(run, CHINESE_HEADING_FONT, WESTERN_HEADING_FONT, size, paragraph.style.font.bold)
            elif style_name == "Reference":
                set_run_font(run, CHINESE_BODY_FONT, WESTERN_BODY_FONT, REFERENCE_SIZE_PT, False)
            else:
                set_run_font(run, CHINESE_BODY_FONT, WESTERN_BODY_FONT, BODY_SIZE_PT, False)


# -----------------------------------------------------------------------------
# 导出主流程
# -----------------------------------------------------------------------------


def count_export_words(text: Any) -> int:
    """统计中英混排导出文本字数：中文按字计，英文/数字按词计。"""
    plain = clean_text(text)
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", plain)
    english_words = re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)?", plain)
    return len(chinese_chars) + len(english_words)


def collect_structured_body_text(data: dict[str, Any]) -> str:
    """收集结构化 JSON 中将被写入 Word 的正文文本，供导出前字数核验。"""
    parts: list[str] = []
    parts.extend(iter_paragraph_texts(data.get("preface")))
    for chapter in data.get("chapters") or []:
        if not isinstance(chapter, dict):
            continue
        parts.extend(iter_paragraph_texts(chapter.get("content")))
        for section in chapter.get("sections", []) or []:
            if not isinstance(section, dict):
                continue
            parts.extend(iter_paragraph_texts(section.get("content")))
            for level3 in _level3_items(section):
                parts.extend(iter_paragraph_texts(level3.get("content")))
                for level4 in _level4_items(level3):
                    parts.extend(iter_paragraph_texts(level4.get("content")))
        parts.extend(normalize_references(chapter.get("references")))
    parts.extend(iter_paragraph_texts(data.get("conclusion")))
    parts.extend(normalize_references(data.get("global_references")))
    return "\n\n".join(part for part in parts if str(part).strip())


def export_json_data_to_docx(data: dict[str, Any], output_path: str | Path) -> Path:
    """把已加载的结构化 JSON 数据导出为 .docx，并在函数属性中记录导出前字数。"""
    export_json_data_to_docx.last_body_word_count = count_export_words(collect_structured_body_text(data))
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    document = Document()
    initialize_styles(document)

    title = clean_text(data.get("title") or "未命名专著")
    chapters = [chapter for chapter in (data.get("chapters") or []) if isinstance(chapter, dict)]

    # 1. 封面：独立第一页，无页眉页脚和页码。
    cover_section = document.sections[0]
    set_page_layout(cover_section)
    cover_section.different_first_page_header_footer = True
    unlink_section_headers_footers(cover_section)
    for container in (
        cover_section.header,
        cover_section.footer,
        cover_section.even_page_header,
        cover_section.even_page_footer,
        cover_section.first_page_header,
        cover_section.first_page_footer,
    ):
        clear_header_footer(container)
    write_cover(document, data)

    # 2. 目录：新节，小写罗马页码从 i 开始。
    toc_section = document.add_section(WD_SECTION.NEW_PAGE)
    set_page_layout(toc_section)
    set_section_page_number(toc_section, fmt="lowerRoman", start=1)
    configure_front_footer(toc_section)
    write_toc(document)

    # 3. 前言：如果存在则新页，罗马页码连续。
    if list(iter_paragraph_texts(data.get("preface"))):
        preface_section = document.add_section(WD_SECTION.NEW_PAGE)
        set_page_layout(preface_section)
        set_section_page_number(preface_section, fmt="lowerRoman", start=None)
        configure_front_footer(preface_section)
        write_preface(document, data.get("preface"))

    # 4. 正文：每章从新页开始。为减少无意义空白，不再强制 ODD_PAGE 奇数页。
    first_body = True
    for chapter_index, chapter in enumerate(chapters, start=1):
        chapter_section = document.add_section(WD_SECTION.NEW_PAGE)
        set_page_layout(chapter_section)
        set_section_page_number(chapter_section, fmt="decimal", start=1 if first_body else None)
        configure_body_headers_footers(chapter_section, title)
        write_chapter(document, chapter, chapter_index)
        first_body = False

    # 5. 结语：不编号一级标题，阿拉伯页码继续。
    if list(iter_paragraph_texts(data.get("conclusion"))):
        conclusion_section = document.add_section(WD_SECTION.NEW_PAGE)
        set_page_layout(conclusion_section)
        set_section_page_number(conclusion_section, fmt="decimal", start=None)
        configure_body_headers_footers(conclusion_section, title)
        write_unnumbered_section(document, "结语", data.get("conclusion"))

    # 6. 参考文献：优先 global_references；没有时合并各章 references。
    refs = normalize_references(data.get("global_references"))
    if not refs:
        for chapter in chapters:
            refs.extend(normalize_references(chapter.get("references")))
    if refs:
        refs_section = document.add_section(WD_SECTION.NEW_PAGE)
        set_page_layout(refs_section)
        set_section_page_number(refs_section, fmt="decimal", start=None)
        configure_body_headers_footers(refs_section, title)
        write_global_references(document, refs)

    normalize_all_runs(document)
    document.save(str(output))
    return output


export_json_data_to_docx.last_body_word_count = 0


def export_json_to_docx(json_path: str | Path, output_path: str | Path | None = None) -> Path:
    """从 JSON 文件读取数据并导出 DOCX。"""
    source = Path(json_path)
    if output_path is None:
        output_path = source.with_suffix(".docx")
    with source.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError("输入 JSON 顶层必须是对象。")
    return export_json_data_to_docx(data, output_path)


# 兼容旧调用名称。
generate_monograph = export_json_to_docx


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="将结构化专著 JSON 导出为固定专业排版 Word 文档。")
    parser.add_argument("json_path", help="输入 JSON 文件路径")
    parser.add_argument("-o", "--output", help="输出 DOCX 路径；默认与 JSON 同名", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        output = export_json_to_docx(args.json_path, args.output)
    except Exception as exc:  # CLI 需要明确错误信息。
        print(f"导出失败：{exc}", file=sys.stderr)
        return 1
    print(f"文档已生成：{output}")
    print("提示：请用 Word 打开文档，右键目录区域选择【更新域】以刷新目录与页码。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
