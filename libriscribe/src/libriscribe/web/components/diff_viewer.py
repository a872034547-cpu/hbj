"""
版本差异查看器组件

提供章节版本对比功能，支持行级和词级差异高亮显示。
"""

import difflib
import html
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import streamlit as st


# ──────────────────────────────────────────────
# CSS 样式
# ──────────────────────────────────────────────

DIFF_CSS = """
<style>
.diff-container {
    font-family: 'Courier New', Courier, monospace;
    font-size: 13px;
    line-height: 1.6;
    border: 1px solid #e0e0e0;
    border-radius: 6px;
    overflow: hidden;
    margin-bottom: 1rem;
}
.diff-header {
    background: #f5f5f5;
    padding: 8px 12px;
    font-weight: bold;
    border-bottom: 1px solid #e0e0e0;
    font-family: sans-serif;
    font-size: 14px;
}
.diff-line {
    padding: 1px 12px;
    white-space: pre-wrap;
    word-wrap: break-word;
}
.diff-line-add {
    background-color: #e6ffed;
    color: #22863a;
}
.diff-line-del {
    background-color: #ffeef0;
    color: #cb2431;
}
.diff-line-mod {
    background-color: #fff5b1;
    color: #735c0f;
}
.diff-line-ctx {
    background-color: #ffffff;
    color: #555555;
}
.diff-line-num {
    display: inline-block;
    width: 40px;
    text-align: right;
    padding-right: 10px;
    color: #999;
    user-select: none;
    border-right: 1px solid #e0e0e0;
    margin-right: 10px;
}
.diff-word-add {
    background-color: #acf2bd;
    border-radius: 3px;
    padding: 0 2px;
}
.diff-word-del {
    background-color: #fdb8c0;
    border-radius: 3px;
    padding: 0 2px;
    text-decoration: line-through;
}
.diff-stats {
    display: flex;
    gap: 16px;
    padding: 8px 12px;
    background: #f8f9fa;
    border: 1px solid #e0e0e0;
    border-radius: 6px;
    margin-bottom: 1rem;
    font-family: sans-serif;
    font-size: 14px;
}
.diff-stat-add { color: #22863a; font-weight: bold; }
.diff-stat-del { color: #cb2431; font-weight: bold; }
.diff-stat-mod { color: #735c0f; font-weight: bold; }
.diff-stat-pct { color: #6f42c1; font-weight: bold; }
.diff-collapse-btn {
    background: #f0f0f0;
    border: 1px dashed #ccc;
    padding: 4px 12px;
    cursor: pointer;
    text-align: center;
    color: #666;
    font-family: sans-serif;
    font-size: 12px;
}
.side-by-side {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0;
}
.side-panel {
    border-right: 1px solid #e0e0e0;
    overflow-x: auto;
}
.side-panel:last-child {
    border-right: none;
}
</style>
"""


# ──────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────


def _escape(text: str) -> str:
    """HTML 转义，防止 XSS。"""
    return html.escape(text, quote=True)


def _compute_line_diff(
    old_text: str, new_text: str
) -> List[Tuple[str, str, str]]:
    """
    计算行级差异。

    返回列表，每项为 (tag, old_line, new_line)：
    - tag: 'equal' | 'delete' | 'insert' | 'replace'
    """
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)

    matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    results: List[Tuple[str, str, str]] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                results.append(("equal", old_lines[i1 + k], new_lines[j1 + k]))
        elif tag == "delete":
            for k in range(i1, i2):
                results.append(("delete", old_lines[k], ""))
        elif tag == "insert":
            for k in range(j1, j2):
                results.append(("insert", "", new_lines[k]))
        elif tag == "replace":
            old_chunk = old_lines[i1:i2]
            new_chunk = new_lines[j1:j2]
            max_len = max(len(old_chunk), len(new_chunk))
            for k in range(max_len):
                o = old_chunk[k] if k < len(old_chunk) else ""
                n = new_chunk[k] if k < len(new_chunk) else ""
                results.append(("replace", o, n))

    return results


def _word_diff_html(old_line: str, new_line: str) -> Tuple[str, str]:
    """
    对两行文本做词级差异，返回带高亮 HTML 的 (old_html, new_html)。
    """
    old_words = old_line.split()
    new_words = new_line.split()

    matcher = difflib.SequenceMatcher(None, old_words, new_words, autojunk=False)

    old_parts: List[str] = []
    new_parts: List[str] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            segment = " ".join(old_words[i1:i2])
            old_parts.append(_escape(segment))
            new_parts.append(_escape(" ".join(new_words[j1:j2])))
        elif tag == "delete":
            segment = " ".join(old_words[i1:i2])
            old_parts.append(f'<span class="diff-word-del">{_escape(segment)}</span>')
        elif tag == "insert":
            segment = " ".join(new_words[j1:j2])
            new_parts.append(f'<span class="diff-word-add">{_escape(segment)}</span>')
        elif tag == "replace":
            old_seg = " ".join(old_words[i1:i2])
            new_seg = " ".join(new_words[j1:j2])
            old_parts.append(f'<span class="diff-word-del">{_escape(old_seg)}</span>')
            new_parts.append(f'<span class="diff-word-add">{_escape(new_seg)}</span>')

    return " ".join(old_parts), " ".join(new_parts)


# ──────────────────────────────────────────────
# 核心渲染函数
# ──────────────────────────────────────────────


def compute_diff_stats(old_text: str, new_text: str) -> Dict[str, float]:
    """
    计算两段文本的差异统计信息。

    返回字典：
    - lines_added: 新增行数
    - lines_removed: 删除行数
    - lines_modified: 修改行数
    - percentage_change: 变化百分比 (0-100)
    """
    diff_results = _compute_line_diff(old_text, new_text)

    added = 0
    removed = 0
    modified = 0
    total_old = 0

    for tag, old_line, new_line in diff_results:
        if tag == "equal":
            total_old += 1
        elif tag == "delete":
            removed += 1
            total_old += 1
        elif tag == "insert":
            added += 1
        elif tag == "replace":
            modified += 1
            total_old += 1

    total_changes = added + removed + modified
    base = max(total_old, 1)
    percentage = round((total_changes / base) * 100, 1)

    return {
        "lines_added": added,
        "lines_removed": removed,
        "lines_modified": modified,
        "percentage_change": min(percentage, 100.0),
    }


def render_inline_diff(old_text: str, new_text: str) -> str:
    """
    计算词级差异并返回带颜色高亮的 HTML 字符串。

    参数:
        old_text: 旧版本文本
        new_text: 新版本文本

    返回:
        包含差异高亮的 HTML 字符串
    """
    diff_results = _compute_line_diff(old_text, new_text)

    lines_html: List[str] = []

    for idx, (tag, old_line, new_line) in enumerate(diff_results):
        line_num = idx + 1
        num_span = f'<span class="diff-line-num">{line_num}</span>'

        if tag == "equal":
            lines_html.append(
                f'<div class="diff-line diff-line-ctx">'
                f"{num_span}{_escape(old_line)}</div>"
            )
        elif tag == "delete":
            lines_html.append(
                f'<div class="diff-line diff-line-del">'
                f"{num_span}{_escape(old_line)}</div>"
            )
        elif tag == "insert":
            lines_html.append(
                f'<div class="diff-line diff-line-add">'
                f"{num_span}{_escape(new_line)}</div>"
            )
        elif tag == "replace":
            old_html, new_html = _word_diff_html(old_line, new_line)
            lines_html.append(
                f'<div class="diff-line diff-line-mod">'
                f"{num_span}{old_html}</div>"
            )
            lines_html.append(
                f'<div class="diff-line diff-line-mod">'
                f"{num_span}{new_html}</div>"
            )

    return "\n".join(lines_html)


def render_diff_viewer(
    old_text: str,
    new_text: str,
    old_label: str = "Previous",
    new_label: str = "Current",
) -> None:
    """
    渲染版本差异查看器。

    支持侧边对比和统一视图两种模式，可折叠未变更区域。

    参数:
        old_text: 旧版本文本
        new_text: 新版本文本
        old_label: 旧版本标签
        new_label: 新版本标签
    """
    st.markdown(DIFF_CSS, unsafe_allow_html=True)

    # ── 差异统计 ──
    stats = compute_diff_stats(old_text, new_text)
    st.markdown(
        f"""
        <div class="diff-stats">
            <span class="diff-stat-add">+{int(stats['lines_added'])} added</span>
            <span class="diff-stat-del">-{int(stats['lines_removed'])} removed</span>
            <span class="diff-stat-mod">~{int(stats['lines_modified'])} modified</span>
            <span class="diff-stat-pct">{stats['percentage_change']}% changed</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── 视图模式切换 ──
    col_toggle, col_collapse = st.columns([1, 1])
    with col_toggle:
        view_mode = st.radio(
            "视图模式",
            ["统一视图", "侧边对比"],
            horizontal=True,
            key="diff_view_mode",
        )
    with col_collapse:
        collapse_unchanged = st.checkbox(
            "折叠未变更区域", value=True, key="diff_collapse"
        )

    diff_results = _compute_line_diff(old_text, new_text)

    if view_mode == "统一视图":
        _render_unified_view(diff_results, collapse_unchanged)
    else:
        _render_side_by_side_view(
            diff_results, old_label, new_label, collapse_unchanged
        )


def _render_unified_view(
    diff_results: List[Tuple[str, str, str]],
    collapse_unchanged: bool,
    context_lines: int = 3,
) -> None:
    """渲染统一差异视图。"""
    lines_html: List[str] = []
    equal_buffer: List[str] = []
    line_num_old = 0
    line_num_new = 0

    def _flush_equal_buffer():
        """处理缓冲的未变更行（折叠或展开）。"""
        nonlocal line_num_old, line_num_new
        if not equal_buffer:
            return

        if collapse_unchanged and len(equal_buffer) > context_lines * 2:
            # 显示前 context_lines 行
            for i in range(context_lines):
                line_num_old += 1
                line_num_new += 1
                num = (
                    f'<span class="diff-line-num">{line_num_old}</span>'
                    f'<span class="diff-line-num" style="border-left:1px solid #e0e0e0;'
                    f'margin-left:4px;padding-left:6px;">{line_num_new}</span>'
                )
                lines_html.append(
                    f'<div class="diff-line diff-line-ctx">'
                    f"{num}{_escape(equal_buffer[i])}</div>"
                )

            # 折叠提示
            hidden = len(equal_buffer) - context_lines * 2
            lines_html.append(
                f'<div class="diff-collapse-btn">'
                f"⋯ {hidden} unchanged lines hidden ⋯</div>"
            )

            # 显示后 context_lines 行
            for i in range(context_lines, 0, -1):
                line_num_old += 1
                line_num_new += 1
                idx = len(equal_buffer) - i
                num = (
                    f'<span class="diff-line-num">{line_num_old}</span>'
                    f'<span class="diff-line-num" style="border-left:1px solid #e0e0e0;'
                    f'margin-left:4px;padding-left:6px;">{line_num_new}</span>'
                )
                lines_html.append(
                    f'<div class="diff-line diff-line-ctx">'
                    f"{num}{_escape(equal_buffer[idx])}</div>"
                )

            # 跳过的行数
            skipped = len(equal_buffer) - context_lines * 2
            line_num_old += skipped
            line_num_new += skipped
        else:
            for line in equal_buffer:
                line_num_old += 1
                line_num_new += 1
                num = (
                    f'<span class="diff-line-num">{line_num_old}</span>'
                    f'<span class="diff-line-num" style="border-left:1px solid #e0e0e0;'
                    f'margin-left:4px;padding-left:6px;">{line_num_new}</span>'
                )
                lines_html.append(
                    f'<div class="diff-line diff-line-ctx">'
                    f"{num}{_escape(line)}</div>"
                )

        equal_buffer.clear()

    for tag, old_line, new_line in diff_results:
        if tag == "equal":
            equal_buffer.append(old_line.rstrip("\n"))
            continue

        _flush_equal_buffer()

        if tag == "delete":
            line_num_old += 1
            num = f'<span class="diff-line-num">{line_num_old}</span>'
            lines_html.append(
                f'<div class="diff-line diff-line-del">'
                f'{num}<span style="color:#cb2431;font-weight:bold;">- </span>'
                f"{_escape(old_line.rstrip(chr(10)))}</div>"
            )
        elif tag == "insert":
            line_num_new += 1
            num = (
                f'<span class="diff-line-num" style="margin-left:50px;">'
                f"{line_num_new}</span>"
            )
            lines_html.append(
                f'<div class="diff-line diff-line-add">'
                f'{num}<span style="color:#22863a;font-weight:bold;">+ </span>'
                f"{_escape(new_line.rstrip(chr(10)))}</div>"
            )
        elif tag == "replace":
            line_num_old += 1
            line_num_new += 1
            old_html, new_html_word = _word_diff_html(
                old_line.rstrip("\n"), new_line.rstrip("\n")
            )
            num_old = f'<span class="diff-line-num">{line_num_old}</span>'
            num_new = (
                f'<span class="diff-line-num" style="margin-left:50px;">'
                f"{line_num_new}</span>"
            )
            lines_html.append(
                f'<div class="diff-line diff-line-mod">'
                f'{num_old}<span style="color:#cb2431;">- </span>{old_html}</div>'
            )
            lines_html.append(
                f'<div class="diff-line diff-line-mod">'
                f'{num_new}<span style="color:#22863a;">+ </span>{new_html_word}</div>'
            )

    _flush_equal_buffer()

    content = "\n".join(lines_html)
    st.markdown(
        f'<div class="diff-container">{content}</div>',
        unsafe_allow_html=True,
    )


def _render_side_by_side_view(
    diff_results: List[Tuple[str, str, str]],
    old_label: str,
    new_label: str,
    collapse_unchanged: bool,
    context_lines: int = 3,
) -> None:
    """渲染侧边对比视图。"""
    left_lines: List[str] = []
    right_lines: List[str] = []
    equal_buffer: List[Tuple[str, str]] = []
    line_num_old = 0
    line_num_new = 0

    def _flush_equal_buffer():
        nonlocal line_num_old, line_num_new
        if not equal_buffer:
            return

        if collapse_unchanged and len(equal_buffer) > context_lines * 2:
            for i in range(context_lines):
                line_num_old += 1
                line_num_new += 1
                o, n = equal_buffer[i]
                left_lines.append(
                    f'<div class="diff-line diff-line-ctx">'
                    f'<span class="diff-line-num">{line_num_old}</span>'
                    f"{_escape(o)}</div>"
                )
                right_lines.append(
                    f'<div class="diff-line diff-line-ctx">'
                    f'<span class="diff-line-num">{line_num_new}</span>'
                    f"{_escape(n)}</div>"
                )

            hidden = len(equal_buffer) - context_lines * 2
            collapse_html = (
                f'<div class="diff-collapse-btn">'
                f"⋯ {hidden} unchanged lines ⋯</div>"
            )
            left_lines.append(collapse_html)
            right_lines.append(collapse_html)

            for i in range(context_lines, 0, -1):
                line_num_old += 1
                line_num_new += 1
                idx = len(equal_buffer) - i
                o, n = equal_buffer[idx]
                left_lines.append(
                    f'<div class="diff-line diff-line-ctx">'
                    f'<span class="diff-line-num">{line_num_old}</span>'
                    f"{_escape(o)}</div>"
                )
                right_lines.append(
                    f'<div class="diff-line diff-line-ctx">'
                    f'<span class="diff-line-num">{line_num_new}</span>'
                    f"{_escape(n)}</div>"
                )

            skipped = len(equal_buffer) - context_lines * 2
            line_num_old += skipped
            line_num_new += skipped
        else:
            for o, n in equal_buffer:
                line_num_old += 1
                line_num_new += 1
                left_lines.append(
                    f'<div class="diff-line diff-line-ctx">'
                    f'<span class="diff-line-num">{line_num_old}</span>'
                    f"{_escape(o)}</div>"
                )
                right_lines.append(
                    f'<div class="diff-line diff-line-ctx">'
                    f'<span class="diff-line-num">{line_num_new}</span>'
                    f"{_escape(n)}</div>"
                )

        equal_buffer.clear()

    for tag, old_line, new_line in diff_results:
        old_clean = old_line.rstrip("\n")
        new_clean = new_line.rstrip("\n")

        if tag == "equal":
            equal_buffer.append((old_clean, new_clean))
            continue

        _flush_equal_buffer()

        if tag == "delete":
            line_num_old += 1
            left_lines.append(
                f'<div class="diff-line diff-line-del">'
                f'<span class="diff-line-num">{line_num_old}</span>'
                f"{_escape(old_clean)}</div>"
            )
            right_lines.append(
                '<div class="diff-line diff-line-ctx">'
                '<span class="diff-line-num"></span></div>'
            )
        elif tag == "insert":
            line_num_new += 1
            left_lines.append(
                '<div class="diff-line diff-line-ctx">'
                '<span class="diff-line-num"></span></div>'
            )
            right_lines.append(
                f'<div class="diff-line diff-line-add">'
                f'<span class="diff-line-num">{line_num_new}</span>'
                f"{_escape(new_clean)}</div>"
            )
        elif tag == "replace":
            line_num_old += 1
            line_num_new += 1
            old_html, new_html = _word_diff_html(old_clean, new_clean)
            left_lines.append(
                f'<div class="diff-line diff-line-mod">'
                f'<span class="diff-line-num">{line_num_old}</span>'
                f"{old_html}</div>"
            )
            right_lines.append(
                f'<div class="diff-line diff-line-mod">'
                f'<span class="diff-line-num">{line_num_new}</span>'
                f"{new_html}</div>"
            )

    _flush_equal_buffer()

    left_content = "\n".join(left_lines)
    right_content = "\n".join(right_lines)

    col_left, col_right = st.columns(2)
    with col_left:
        st.markdown(f"**{old_label}**", help="旧版本")
        st.markdown(
            f'<div class="diff-container"><div class="diff-header">'
            f"{_escape(old_label)}</div>{left_content}</div>",
            unsafe_allow_html=True,
        )
    with col_right:
        st.markdown(f"**{new_label}**", help="新版本")
        st.markdown(
            f'<div class="diff-container"><div class="diff-header">'
            f"{_escape(new_label)}</div>{right_content}</div>",
            unsafe_allow_html=True,
        )


# ──────────────────────────────────────────────
# 版本选择器
# ──────────────────────────────────────────────


def render_version_selector(
    project_data: dict, chapter_number: int
) -> Optional[Tuple[str, str]]:
    """
    渲染版本选择器，允许用户选择两个版本进行对比。

    参数:
        project_data: 项目数据字典，需包含 version_history 字段
        chapter_number: 章节编号

    返回:
        选中的两个版本文本元组 (old_text, new_text)，未选择时返回 None
    """
    version_history = project_data.get("version_history", {})

    # 版本历史可能按章节存储
    chapter_key = f"chapter_{chapter_number}"
    versions: List[Dict] = version_history.get(chapter_key, [])

    if not versions:
        # 尝试扁平结构
        versions = [
            v
            for v in version_history.get("versions", [])
            if v.get("chapter_number") == chapter_number
        ]

    if not versions:
        st.info(f"第 {chapter_number} 章暂无版本历史记录。")
        return None

    st.subheader(f"📖 第 {chapter_number} 章 — 版本对比")

    # 按时间倒序排列
    sorted_versions = sorted(
        versions,
        key=lambda v: v.get("timestamp", ""),
        reverse=True,
    )

    # 构建版本选项标签
    def _format_version(v: Dict, idx: int) -> str:
        ts = v.get("timestamp", "未知时间")
        desc = v.get("description", "无描述")
        # 尝试格式化时间戳
        try:
            dt = datetime.fromisoformat(ts)
            ts = dt.strftime("%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
            pass
        return f"v{len(sorted_versions) - idx} | {ts} | {desc}"

    version_labels = [_format_version(v, i) for i, v in enumerate(sorted_versions)]

    col_old, col_new = st.columns(2)
    with col_old:
        old_idx = st.selectbox(
            "选择旧版本",
            range(len(version_labels)),
            format_func=lambda i: version_labels[i],
            key="diff_old_version",
        )
    with col_new:
        # 默认选择最新版本（索引 0）
        default_new = 0 if len(version_labels) > 1 else 0
        new_idx = st.selectbox(
            "选择新版本",
            range(len(version_labels)),
            format_func=lambda i: version_labels[i],
            index=default_new,
            key="diff_new_version",
        )

    if old_idx == new_idx:
        st.warning("请选择两个不同的版本进行对比。")
        return None

    old_version = sorted_versions[old_idx]
    new_version = sorted_versions[new_idx]

    old_text = old_version.get("content", "")
    new_text = new_version.get("content", "")

    if not old_text and not new_text:
        st.warning("所选版本的内容为空。")
        return None

    # 显示版本信息
    with st.expander("📋 版本详情", expanded=False):
        info_col1, info_col2 = st.columns(2)
        with info_col1:
            st.markdown(f"**旧版本**: {version_labels[old_idx]}")
            st.markdown(f"- 时间: {old_version.get('timestamp', 'N/A')}")
            st.markdown(f"- 描述: {old_version.get('description', 'N/A')}")
        with info_col2:
            st.markdown(f"**新版本**: {version_labels[new_idx]}")
            st.markdown(f"- 时间: {new_version.get('timestamp', 'N/A')}")
            st.markdown(f"- 描述: {new_version.get('description', 'N/A')}")

    return old_text, new_text
