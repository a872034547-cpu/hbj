"""中文章节与大纲标签格式化工具。"""

from __future__ import annotations

import re
from typing import Any


_CN_DIGITS = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九"]


def chinese_number(value: Any) -> str:
    """把正整数转换为常用中文数字，用于章节/小节展示。"""
    try:
        n = int(value)
    except Exception:
        n = 1
    if n <= 0:
        n = 1
    if n < 10:
        return _CN_DIGITS[n]
    if n == 10:
        return "十"
    if n < 20:
        return "十" + _CN_DIGITS[n - 10]
    if n < 100:
        tens, ones = divmod(n, 10)
        return _CN_DIGITS[tens] + "十" + (_CN_DIGITS[ones] if ones else "")
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        prefix = _CN_DIGITS[hundreds] + "百"
        if rest == 0:
            return prefix
        if rest < 10:
            return prefix + "零" + _CN_DIGITS[rest]
        return prefix + chinese_number(rest)
    return str(n)


def format_chapter_label(chapter_num: Any, title: str = "") -> str:
    """返回用户可见章标题：第一章 / 第一章 标题。"""
    label = f"第{chinese_number(chapter_num)}章"
    return f"{label} {str(title or '').strip()}".strip()


def format_outline_section_label(section_number: Any, title: str = "") -> str:
    """把内部 1.1/1.1.1/1.1.1.1 编号统一转换为中文大纲标题。"""
    parts = [p for p in str(section_number or "").split(".") if p]
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return f"{section_number} {title}".strip()
    if len(nums) >= 4:
        label = f"（{chinese_number(nums[3])}）"
    elif len(nums) == 3:
        label = f"{chinese_number(nums[2])}、"
    elif len(nums) == 2:
        label = f"第{chinese_number(nums[1])}节"
    else:
        label = str(section_number or "").strip()
    return f"{label} {str(title or '').strip()}".strip()


def chapter_heading_pattern(number: Any) -> re.Pattern[str]:
    """匹配旧/新章标题，用于导出前去重清理。"""
    cn = re.escape(chinese_number(number))
    arabic = re.escape(str(number))
    return re.compile(rf"^(?:第\s*(?:{arabic}|{cn})\s*章|第\s*0\s*章|Chapter\s*\d+)\b", re.IGNORECASE)


def strip_leading_chapter_heading(content: Any, number: Any, title: str = "") -> str:
    """移除 Markdown 正文开头重复的章标题，供页面预处理与各导出器复用。"""
    if not content:
        return ""
    lines = str(content).splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and re.match(r"^#\s+", lines[0].strip()):
        heading = re.sub(r"^#+\s*", "", lines[0].strip()).strip()
        generic_heading = re.compile(r"^(?:第\s*[0-9一二三四五六七八九十百千]+\s*章|Chapter\s*\d+)\b", re.IGNORECASE)
        if chapter_heading_pattern(number).search(heading) or generic_heading.search(heading) or (title and str(title).strip() in heading):
            lines = lines[1:]
    return "\n".join(lines).strip()
