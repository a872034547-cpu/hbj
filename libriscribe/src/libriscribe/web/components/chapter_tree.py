"""
章节树状导航组件

提供可复用的章节/场景层级导航，支持：
- 章节展开/折叠
- 完成状态图标
- 字数统计与评审分数
- 按状态筛选与标题搜索
- 当前选中项高亮
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

import streamlit as st

from libriscribe.knowledge_base import (
    Chapter,
    ChapterReview,
    ProjectKnowledgeBase,
    Scene,
)


# ---------------------------------------------------------------------------
# 状态枚举
# ---------------------------------------------------------------------------

class ChapterStatus(str, Enum):
    """章节完成状态"""
    WRITTEN = "written"
    REVIEWED = "reviewed"
    PENDING = "pending"
    ERROR = "error"


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def get_chapter_status(
    chapter: Chapter,
    chapter_reviews: Optional[Dict[int, List[ChapterReview]]] = None,
    chapter_content: Optional[Dict[int, str]] = None,
) -> ChapterStatus:
    """
    根据内容和评审信息判断章节状态。

    优先级：
    1. 有评审记录且分数 >= 0.6 → REVIEWED
    2. 有内容（chapter_content 或 summary 非空）→ WRITTEN
    3. 否则 → PENDING
    """
    reviews = (chapter_reviews or {}).get(chapter.chapter_number, [])
    has_content = False

    # 检查外部提供的内容字典
    if chapter_content and chapter.chapter_number in chapter_content:
        has_content = bool(chapter_content[chapter.chapter_number].strip())

    # 回退到章节摘要
    if not has_content:
        has_content = bool(chapter.summary and chapter.summary.strip())

    # 检查场景是否有内容
    if not has_content and chapter.scenes:
        has_content = any(s.summary and s.summary.strip() for s in chapter.scenes)

    if reviews:
        latest = reviews[-1]
        if latest.score >= 0.6:
            return ChapterStatus.REVIEWED
        elif latest.score < 0.3 and has_content:
            return ChapterStatus.ERROR

    if has_content:
        return ChapterStatus.WRITTEN

    return ChapterStatus.PENDING


def _status_icon(status: ChapterStatus) -> str:
    """返回状态对应的 emoji 图标"""
    return {
        ChapterStatus.WRITTEN: "✅",
        ChapterStatus.REVIEWED: "⭐",
        ChapterStatus.PENDING: "⏳",
        ChapterStatus.ERROR: "❌",
    }[status]


def _status_label(status: ChapterStatus) -> str:
    """返回状态的中文标签"""
    return {
        ChapterStatus.WRITTEN: "已撰写",
        ChapterStatus.REVIEWED: "已评审",
        ChapterStatus.PENDING: "待撰写",
        ChapterStatus.ERROR: "需修改",
    }[status]


def _estimate_word_count(text: str) -> int:
    """估算文本字数（中文按字符计，英文按空格分词）"""
    if not text:
        return 0
    # 简单方案：去除空白后按字符数估算
    cleaned = text.strip()
    return len(cleaned)


def _truncate(text: str, max_len: int = 60) -> str:
    """截断文本到指定长度"""
    if not text:
        return ""
    text = text.replace("\n", " ").strip()
    if len(text) <= max_len:
        return text
    return text[:max_len] + "…"


def _get_review_score(
    chapter_number: int,
    chapter_reviews: Optional[Dict[int, List[ChapterReview]]],
) -> Optional[float]:
    """获取章节最新评审分数"""
    reviews = (chapter_reviews or {}).get(chapter_number, [])
    if reviews:
        return reviews[-1].score
    return None


# ---------------------------------------------------------------------------
# 节点渲染
# ---------------------------------------------------------------------------

def render_scene_node(
    scene: Scene,
    scene_number: int,
    is_selected: bool = False,
    on_select: Optional[Callable[[str, int, int], None]] = None,
    chapter_number: int = 0,
) -> None:
    """
    渲染单个场景节点。

    Parameters
    ----------
    scene : Scene
        场景数据对象
    scene_number : int
        场景序号
    is_selected : bool
        是否为当前选中项
    on_select : callable, optional
        选中回调 ``(item_type, chapter_number, scene_number)``
    chapter_number : int
        所属章节号
    """
    border_color = "#4CAF50" if is_selected else "transparent"
    bg_color = "#e8f5e9" if is_selected else "transparent"

    title = scene.summary if scene.summary else f"场景 {scene_number}"
    truncated_title = _truncate(title, 40)

    # 角色列表
    char_display = ""
    if scene.characters:
        char_display = " · ".join(scene.characters[:5])
        if len(scene.characters) > 5:
            char_display += f" +{len(scene.characters) - 5}"

    # 场景描述
    description_parts = []
    if scene.setting:
        description_parts.append(f"📍 {_truncate(scene.setting, 30)}")
    if scene.goal:
        description_parts.append(f"🎯 {_truncate(scene.goal, 30)}")
    if scene.emotional_beat:
        description_parts.append(f"🎭 {_truncate(scene.emotional_beat, 20)}")

    description_html = "<br>".join(description_parts) if description_parts else ""

    selected_marker = "▸ " if is_selected else ""

    html = f"""
    <div style="
        padding: 6px 12px 6px 28px;
        margin: 2px 0;
        border-left: 3px solid {border_color};
        background-color: {bg_color};
        border-radius: 4px;
        cursor: pointer;
        font-size: 0.88em;
    ">
        <div style="font-weight: {'600' if is_selected else '400'}; color: #333;">
            {selected_marker}🎬 场景 {scene_number}：{truncated_title}
        </div>
        {"<div style='color: #666; font-size: 0.82em; margin-top: 2px;'>" + description_html + "</div>" if description_html else ""}
        {"<div style='color: #888; font-size: 0.80em; margin-top: 2px;'>👥 " + char_display + "</div>" if char_display else ""}
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)

    # 使用隐藏按钮实现点击交互
    if on_select and st.button(
        f"选择场景 {scene_number}",
        key=f"scene_btn_{chapter_number}_{scene_number}",
        help=f"选择场景 {scene_number}",
        use_container_width=True,
        type="secondary" if not is_selected else "primary",
    ):
        on_select("scene", chapter_number, scene_number)


def render_chapter_node(
    chapter: Chapter,
    chapter_number: int,
    is_selected: bool = False,
    chapter_reviews: Optional[Dict[int, List[ChapterReview]]] = None,
    chapter_content: Optional[Dict[int, str]] = None,
    on_select: Optional[Callable[[str, int, int], None]] = None,
    search_query: str = "",
) -> None:
    """
    渲染单个章节节点（含可展开的场景列表）。

    Parameters
    ----------
    chapter : Chapter
        章节数据对象
    chapter_number : int
        章节序号
    is_selected : bool
        是否为当前选中项
    chapter_reviews : dict, optional
        章节评审记录映射
    chapter_content : dict, optional
        章节内容映射（章节号 → 文本）
    on_select : callable, optional
        选中回调 ``(item_type, chapter_number, scene_number)``
    search_query : str
        搜索关键词（用于高亮匹配）
    """
    status = get_chapter_status(chapter, chapter_reviews, chapter_content)
    icon = _status_icon(status)
    status_label = _status_label(status)

    # 字数统计
    content_text = ""
    if chapter_content and chapter.chapter_number in chapter_content:
        content_text = chapter_content[chapter.chapter_number]
    elif chapter.summary:
        content_text = chapter.summary

    word_count = _estimate_word_count(content_text)
    word_display = f"{word_count:,} 字" if word_count > 0 else ""

    # 评审分数
    score = _get_review_score(chapter_number, chapter_reviews)
    score_display = ""
    if score is not None:
        score_pct = int(score * 100)
        if score_pct >= 80:
            score_color = "#4CAF50"
        elif score_pct >= 60:
            score_color = "#FF9800"
        else:
            score_color = "#f44336"
        score_display = (
            f'<span style="color: {score_color}; font-weight: 600;">'
            f"📊 {score_pct}分</span>"
        )

    title = chapter.title if chapter.title else f"第 {chapter_number} 章"
    selected_marker = "▸ " if is_selected else ""

    # 构建章节标题行
    meta_parts = []
    if word_display:
        meta_parts.append(f"📝 {word_display}")
    if score_display:
        meta_parts.append(score_display)
    meta_html = " · ".join(meta_parts) if meta_parts else ""

    # 章节摘要预览
    summary_preview = ""
    if chapter.summary:
        summary_preview = _truncate(chapter.summary, 80)

    # 场景数量
    scene_count = len(chapter.scenes) if chapter.scenes else 0
    scene_badge = f'<span style="background:#e3f2fd; color:#1565c0; padding:1px 6px; border-radius:10px; font-size:0.78em;">{scene_count} 个场景</span>' if scene_count > 0 else ""

    # 章节标题栏 HTML
    header_html = f"""
    <div style="
        padding: 8px 12px;
        margin: 4px 0;
        border-left: 4px solid {'#4CAF50' if is_selected else '#ddd'};
        background-color: {'#f1f8e9' if is_selected else '#fafafa'};
        border-radius: 4px;
    ">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <div>
                <span style="font-size: 1.05em; font-weight: {'700' if is_selected else '500'}; color: #222;">
                    {selected_marker}{icon} 第 {chapter_number} 章：{title}
                </span>
                <span style="margin-left: 8px; font-size: 0.82em; color: #888;">{status_label}</span>
                {" " + scene_badge if scene_badge else ""}
            </div>
            <div style="font-size: 0.85em; color: #666;">
                {meta_html}
            </div>
        </div>
        {"<div style='color: #777; font-size: 0.84em; margin-top: 4px;'>" + summary_preview + "</div>" if summary_preview else ""}
    </div>
    """
    st.markdown(header_html, unsafe_allow_html=True)

    # 章节选择按钮
    if on_select and st.button(
        f"选择第 {chapter_number} 章",
        key=f"chapter_btn_{chapter_number}",
        help=f"选择第 {chapter_number} 章：{title}",
        use_container_width=True,
        type="primary" if is_selected else "secondary",
    ):
        on_select("chapter", chapter_number, 0)

    # 展开场景列表
    if chapter.scenes:
        with st.expander(
            f"📂 展开场景 ({scene_count})",
            expanded=is_selected,
        ):
            for idx, scene in enumerate(chapter.scenes):
                scene_is_selected = (
                    is_selected
                    and st.session_state.get("selected_scene", 0) == scene.scene_number
                )
                render_scene_node(
                    scene=scene,
                    scene_number=scene.scene_number,
                    is_selected=scene_is_selected,
                    on_select=on_select,
                    chapter_number=chapter_number,
                )


# ---------------------------------------------------------------------------
# 主入口：渲染完整章节树
# ---------------------------------------------------------------------------

def render_chapter_tree(
    project_data: ProjectKnowledgeBase,
    on_select: Optional[Callable[[str, int, int], None]] = None,
    chapter_content: Optional[Dict[int, str]] = None,
) -> None:
    """
    渲染完整的章节树状导航。

    Parameters
    ----------
    project_data : ProjectKnowledgeBase
        项目知识库数据
    on_select : callable, optional
        选中回调 ``(item_type, chapter_number, scene_number)``
        若不提供则通过 ``st.session_state`` 管理选中状态
    chapter_content : dict, optional
        章节正文内容映射（章节号 → 文本），用于字数统计
    """
    # 初始化 session state
    if "selected_chapter" not in st.session_state:
        st.session_state.selected_chapter = 0
    if "selected_scene" not in st.session_state:
        st.session_state.selected_scene = 0
    if "tree_filter" not in st.session_state:
        st.session_state.tree_filter = "all"
    if "tree_search" not in st.session_state:
        st.session_state.tree_search = ""

    # 默认回调：更新 session state
    def _default_on_select(item_type: str, ch_num: int, sc_num: int) -> None:
        if item_type == "chapter":
            st.session_state.selected_chapter = ch_num
            st.session_state.selected_scene = 0
        elif item_type == "scene":
            st.session_state.selected_chapter = ch_num
            st.session_state.selected_scene = sc_num

    effective_on_select = on_select or _default_on_select

    chapters = project_data.chapters
    if not chapters:
        st.info("📭 暂无章节数据。请先生成大纲和章节。")
        return

    # -----------------------------------------------------------------------
    # 工具栏：筛选 + 搜索
    # -----------------------------------------------------------------------
    toolbar_col1, toolbar_col2 = st.columns([1, 2])

    with toolbar_col1:
        filter_options = {
            "all": "📋 全部",
            "written": "✅ 已撰写",
            "pending": "⏳ 待撰写",
            "reviewed": "⭐ 已评审",
            "error": "❌ 需修改",
        }
        selected_filter = st.selectbox(
            "状态筛选",
            options=list(filter_options.keys()),
            format_func=lambda x: filter_options[x],
            index=list(filter_options.keys()).index(st.session_state.tree_filter),
            key="chapter_tree_filter_select",
            label_visibility="collapsed",
        )
        st.session_state.tree_filter = selected_filter

    with toolbar_col2:
        search_query = st.text_input(
            "🔍 搜索章节/场景",
            value=st.session_state.tree_search,
            key="chapter_tree_search_input",
            placeholder="输入关键词搜索…",
            label_visibility="collapsed",
        )
        st.session_state.tree_search = search_query

    # -----------------------------------------------------------------------
    # 统计摘要
    # -----------------------------------------------------------------------
    total_chapters = len(chapters)
    status_counts: Dict[str, int] = {
        "written": 0,
        "reviewed": 0,
        "pending": 0,
        "error": 0,
    }
    for ch in chapters.values():
        s = get_chapter_status(ch, project_data.chapter_reviews, chapter_content)
        status_counts[s.value] = status_counts.get(s.value, 0) + 1

    stats_html = f"""
    <div style="
        display: flex; gap: 16px; padding: 8px 12px;
        background: #f5f5f5; border-radius: 6px; margin-bottom: 12px;
        font-size: 0.88em; color: #555;
    ">
        <span>📚 共 <b>{total_chapters}</b> 章</span>
        <span>✅ {status_counts['written']}</span>
        <span>⭐ {status_counts['reviewed']}</span>
        <span>⏳ {status_counts['pending']}</span>
        <span>❌ {status_counts['error']}</span>
    </div>
    """
    st.markdown(stats_html, unsafe_allow_html=True)

    # -----------------------------------------------------------------------
    # 过滤与搜索
    # -----------------------------------------------------------------------
    sorted_chapter_numbers = sorted(chapters.keys())
    search_lower = search_query.lower().strip() if search_query else ""

    rendered_count = 0

    for ch_num in sorted_chapter_numbers:
        chapter = chapters[ch_num]
        status = get_chapter_status(chapter, project_data.chapter_reviews, chapter_content)

        # 状态筛选
        if selected_filter != "all" and status.value != selected_filter:
            continue

        # 搜索匹配（章节标题 / 章节摘要 / 场景摘要）
        if search_lower:
            chapter_match = (
                search_lower in (chapter.title or "").lower()
                or search_lower in (chapter.summary or "").lower()
            )
            scene_match = any(
                search_lower in (s.summary or "").lower()
                for s in (chapter.scenes or [])
            )
            if not chapter_match and not scene_match:
                continue

        is_selected = st.session_state.selected_chapter == ch_num

        render_chapter_node(
            chapter=chapter,
            chapter_number=ch_num,
            is_selected=is_selected,
            chapter_reviews=project_data.chapter_reviews,
            chapter_content=chapter_content,
            on_select=effective_on_select,
            search_query=search_query,
        )
        rendered_count += 1

    if rendered_count == 0:
        if search_lower:
            st.warning(f"🔍 未找到匹配「{search_query}」的章节。")
        else:
            st.info(f"📭 没有符合「{filter_options[selected_filter]}」条件的章节。")
