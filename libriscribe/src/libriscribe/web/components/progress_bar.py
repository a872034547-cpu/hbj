"""
进度展示组件 — Streamlit Web UI

提供书籍整体进度、章节进度、写作统计等可视化展示。
"""

from typing import Any, Dict, List, Optional

import streamlit as st


# ---------------------------------------------------------------------------
# 常量：阶段定义及权重
# ---------------------------------------------------------------------------

PHASES: List[Dict[str, Any]] = [
    {"key": "concept", "label": "选题定位", "icon": "💡", "weight": 0.10},
    {"key": "sources", "label": "资料注入", "icon": "📚", "weight": 0.15},
    {"key": "outline", "label": "大纲规划", "icon": "📋", "weight": 0.15},
    {"key": "writing", "label": "章节写作", "icon": "✍️", "weight": 0.35},
    {"key": "review", "label": "引用审校", "icon": "🔍", "weight": 0.15},
    {"key": "export", "label": "交付导出", "icon": "📤", "weight": 0.10},
]

# 状态 → 颜色 / emoji 映射
_STATUS_STYLE = {
    "done": {"color": "green", "icon": "✅", "label": "已完成"},
    "in_progress": {"color": "orange", "icon": "🔄", "label": "进行中"},
    "not_started": {"color": "gray", "icon": "⬜", "label": "未开始"},
}


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _safe_get(data: Any, key: str, default: Any = None) -> Any:
    """兼容 dict 和 Pydantic model 的安全取值。"""
    if isinstance(data, dict):
        return data.get(key, default)
    return getattr(data, key, default)


def _determine_phase_status(project_data: Any, phase_key: str) -> str:
    """根据项目数据推断某个阶段的完成状态。

    Returns:
        "done" | "in_progress" | "not_started"
    """
    if phase_key == "concept":
        logline = _safe_get(project_data, "logline", "")
        if logline and logline != "No logline available":
            return "done"
        title = _safe_get(project_data, "title", "")
        if title and title != "Untitled":
            return "in_progress"
        return "not_started"

    if phase_key == "outline":
        outline = _safe_get(project_data, "outline", "")
        if outline:
            return "done"
        return "not_started"

    if phase_key == "sources":
        source_documents = _safe_get(project_data, "source_documents", []) or []
        evidence_chunks = _safe_get(project_data, "evidence_chunks", []) or []
        citations = _safe_get(project_data, "citations", []) or []
        if source_documents and (evidence_chunks or citations):
            return "done"
        if source_documents or evidence_chunks or citations:
            return "in_progress"
        return "not_started"

    if phase_key == "writing":
        chapters = _safe_get(project_data, "chapters", {})
        num_chapters = _safe_get(project_data, "num_chapters", 1)
        if isinstance(num_chapters, tuple):
            num_chapters = num_chapters[0]
        if not chapters:
            return "not_started"
        # 检查已完成的章节数：优先按专著写作正文/摘要判断，旧 scenes 仅作为历史兼容数据。
        written = sum(
            1 for ch in chapters.values()
            if _safe_get(ch, "content", "") or _safe_get(ch, "summary", "") or _safe_get(ch, "sections", [])
        )
        if written >= num_chapters:
            return "done"
        return "in_progress"

    if phase_key == "review":
        chapter_reviews = _safe_get(project_data, "chapter_reviews", {})
        if not chapter_reviews:
            return "not_started"
        chapters = _safe_get(project_data, "chapters", {})
        num_chapters = _safe_get(project_data, "num_chapters", 1)
        if isinstance(num_chapters, tuple):
            num_chapters = num_chapters[0]
        reviewed = sum(1 for ch_num in chapters if ch_num in chapter_reviews)
        if reviewed >= num_chapters:
            return "done"
        return "in_progress"

    if phase_key == "export":
        # 导出状态无法从知识库直接推断，默认未开始
        return "not_started"

    return "not_started"


def calculate_overall_progress(project_data: Any) -> float:
    """计算加权整体进度，返回 0.0 ~ 1.0。"""
    total = 0.0
    for phase in PHASES:
        status = _determine_phase_status(project_data, phase["key"])
        if status == "done":
            total += phase["weight"]
        elif status == "in_progress":
            # 进行中的阶段给予一半权重
            total += phase["weight"] * 0.5
    return min(total, 1.0)


def render_phase_indicator(phase: str, status: str) -> None:
    """渲染单个阶段的状态指示器。

    Args:
        phase: 阶段显示名称（如 "概念生成"）
        status: "done" | "in_progress" | "not_started"
    """
    style = _STATUS_STYLE.get(status, _STATUS_STYLE["not_started"])
    st.markdown(
        f"{style['icon']} **{phase}** — "
        f":{style['color']}[{style['label']}]"
    )


# ---------------------------------------------------------------------------
# 主渲染函数
# ---------------------------------------------------------------------------

def render_book_progress(project_data: Any) -> None:
    """展示书籍整体完成进度。

    包含：整体进度条 + 各阶段状态指示器。
    """
    st.subheader("📊 书籍整体进度")

    progress = calculate_overall_progress(project_data)
    st.progress(progress)
    st.caption(f"完成度：**{progress:.0%}**")

    st.markdown("---")
    st.markdown("#### 各阶段进度")

    # 使用两列布局展示阶段
    cols = st.columns(2)
    for idx, phase in enumerate(PHASES):
        status = _determine_phase_status(project_data, phase["key"])
        with cols[idx % 2]:
            st.markdown(
                f"{phase['icon']} **{phase['label']}** — "
                f":{_STATUS_STYLE[status]['color']}[{_STATUS_STYLE[status]['label']}]"
            )


def render_chapter_progress(project_data: Any) -> None:
    """展示每个章节的详细进度。

    每章显示：大纲 / 写作 / 审校 / 编辑 四项状态。
    """
    st.subheader("📖 章节进度详情")

    chapters = _safe_get(project_data, "chapters", {})
    num_chapters = _safe_get(project_data, "num_chapters", 1)
    if isinstance(num_chapters, tuple):
        num_chapters = num_chapters[0]

    chapter_reviews = _safe_get(project_data, "chapter_reviews", {})

    if not chapters:
        st.info("暂无章节数据。请先完成大纲规划和章节写作。")
        return

    for ch_num in sorted(chapters.keys()):
        chapter = chapters[ch_num]
        title = _safe_get(chapter, "title", f"第 {ch_num} 章")
        st.markdown(f"**第 {ch_num} 章：{title}**")

        col1, col2, col3, col4 = st.columns(4)

        # 大纲状态
        scenes = _safe_get(chapter, "scenes", [])
        outline_status = "done" if scenes else "not_started"
        with col1:
            _render_status_badge("大纲", outline_status)

        # 写作状态
        summary = _safe_get(chapter, "summary", "")
        writing_status = "done" if summary else ("in_progress" if scenes else "not_started")
        with col2:
            _render_status_badge("写作", writing_status)

        # 审校状态
        reviews = chapter_reviews.get(ch_num, [])
        if reviews:
            review_status = "done"
        elif summary:
            review_status = "in_progress"
        else:
            review_status = "not_started"
        with col3:
            _render_status_badge("审校", review_status)

        # 编辑状态（基于最新评审分数）
        if reviews:
            latest_score = _safe_get(reviews[-1], "score", 0.0)
            edit_status = "done" if latest_score >= 0.8 else "in_progress"
        else:
            edit_status = "not_started"
        with col4:
            _render_status_badge("编辑", edit_status)

        st.markdown("")  # 间距


def render_writing_stats(project_data: Any) -> None:
    """展示写作统计数据。

    包含：总字数、章均字数、预计阅读时间、完成章节比例、评审分数分布。
    """
    st.subheader("📈 写作统计")

    chapters = _safe_get(project_data, "chapters", {})
    num_chapters = _safe_get(project_data, "num_chapters", 1)
    if isinstance(num_chapters, tuple):
        num_chapters = num_chapters[0]

    chapter_reviews = _safe_get(project_data, "chapter_reviews", {})

    # 计算总字数（基于章节摘要长度估算）
    total_words = 0
    completed_chapters = 0
    for ch in chapters.values():
        summary = _safe_get(ch, "summary", "")
        if summary:
            # 中文按字符数计，英文按空格分词
            total_words += len(summary)
            completed_chapters += 1

    avg_words = total_words // max(completed_chapters, 1)
    # 中文阅读速度约 400 字/分钟
    reading_minutes = total_words / 400 if total_words > 0 else 0

    # 指标卡片
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("总字数", f"{total_words:,}")
    with col2:
        st.metric("章均字数", f"{avg_words:,}")
    with col3:
        if reading_minutes < 60:
            reading_str = f"{reading_minutes:.0f} 分钟"
        else:
            reading_str = f"{reading_minutes / 60:.1f} 小时"
        st.metric("预计阅读时间", reading_str)
    with col4:
        st.metric("已完成章节", f"{completed_chapters} / {num_chapters}")

    # 评审分数分布
    all_scores: List[float] = []
    for reviews in chapter_reviews.values():
        for review in reviews:
            score = _safe_get(review, "score", 0.0)
            if score > 0:
                all_scores.append(score)

    if all_scores:
        st.markdown("---")
        st.markdown("#### 评审分数分布")

        score_col1, score_col2, score_col3 = st.columns(3)
        with score_col1:
            st.metric("平均分", f"{sum(all_scores) / len(all_scores):.2f}")
        with score_col2:
            st.metric("最高分", f"{max(all_scores):.2f}")
        with score_col3:
            st.metric("最低分", f"{min(all_scores):.2f}")

        # 分数区间分布
        brackets = {"优秀 (≥0.8)": 0, "良好 (0.6-0.8)": 0, "待改进 (<0.6)": 0}
        for s in all_scores:
            if s >= 0.8:
                brackets["优秀 (≥0.8)"] += 1
            elif s >= 0.6:
                brackets["良好 (0.6-0.8)"] += 1
            else:
                brackets["待改进 (<0.6)"] += 1

        dist_cols = st.columns(3)
        for idx, (label, count) in enumerate(brackets.items()):
            with dist_cols[idx]:
                st.metric(label, count)


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------

def _render_status_badge(label: str, status: str) -> None:
    """渲染一个带颜色的状态标签。"""
    style = _STATUS_STYLE.get(status, _STATUS_STYLE["not_started"])
    st.markdown(
        f"{style['icon']} {label}："
        f":{style['color']}[{style['label']}]"
    )
