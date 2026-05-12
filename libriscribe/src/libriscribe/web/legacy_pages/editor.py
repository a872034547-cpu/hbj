# src/libriscribe/web/pages/editor.py
"""
章节编辑器页面 - Streamlit Web UI

提供章节选择、Markdown 编辑、元数据展示、操作按钮（保存/重新生成/评审/添加引用/检查术语），
以及侧边面板（大纲/评审反馈/引用/术语高亮）。
"""

import logging
from pathlib import Path
from typing import Optional, Dict, List, Any
from datetime import datetime

import streamlit as st

from libriscribe.knowledge_base import (
    ProjectKnowledgeBase,
    Chapter,
    Scene,
    Citation,
    ChapterReview,
)
from libriscribe.utils.llm_client import LLMClient
from libriscribe.utils.file_utils import read_markdown_file, write_markdown_file
from libriscribe.memory.terminology import TerminologyManager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _get_project_data() -> Optional[ProjectKnowledgeBase]:
    """从 session_state 获取当前项目数据。"""
    return st.session_state.get("project_data")


def _get_project_dir() -> Optional[str]:
    """获取项目目录路径。"""
    project_data = _get_project_data()
    if project_data and project_data.project_dir:
        return str(project_data.project_dir)
    return st.session_state.get("project_dir")


def _get_llm_client() -> Optional[LLMClient]:
    """获取或创建 LLMClient 实例（缓存在 session_state）。"""
    if "llm_client" not in st.session_state:
        try:
            st.session_state.llm_client = LLMClient()
        except Exception as e:
            st.error(f"初始化 LLM 客户端失败: {e}")
            return None
    return st.session_state.llm_client


def _load_chapter_content(chapter_number: int) -> str:
    """从文件加载章节 Markdown 内容。"""
    project_dir = _get_project_dir()
    if not project_dir:
        return ""
    chapter_path = Path(project_dir) / f"chapter_{chapter_number}.md"
    content = read_markdown_file(str(chapter_path))
    return content or ""


def _save_chapter_content(chapter_number: int, content: str) -> bool:
    """将章节内容保存到 Markdown 文件。"""
    project_dir = _get_project_dir()
    if not project_dir:
        st.error("项目目录未设置，无法保存。")
        return False
    chapter_path = Path(project_dir) / f"chapter_{chapter_number}.md"
    try:
        write_markdown_file(str(chapter_path), content)
        return True
    except Exception as e:
        st.error(f"保存失败: {e}")
        return False


def _compute_word_count(text: str) -> int:
    """计算字数（中文按字符计，英文按空格分词）。"""
    if not text:
        return 0
    # 简单统计：去除空白后的字符数
    return len(text.replace(" ", "").replace("\n", ""))


def _compute_scene_count(chapter: Chapter) -> int:
    """获取章节数。"""
    return len(chapter.scenes) if chapter.scenes else 0


def _get_last_modified(chapter_number: int) -> str:
    """获取章节文件最后修改时间。"""
    project_dir = _get_project_dir()
    if not project_dir:
        return "未知"
    chapter_path = Path(project_dir) / f"chapter_{chapter_number}.md"
    if chapter_path.exists():
        mtime = datetime.fromtimestamp(chapter_path.stat().st_mtime)
        return mtime.strftime("%Y-%m-%d %H:%M:%S")
    return "未创建"


def _highlight_terminology(text: str, terminology: Dict[str, str]) -> List[Dict[str, str]]:
    """在文本中查找术语匹配，返回匹配列表。"""
    matches = []
    if not terminology or not text:
        return matches
    for term, definition in terminology.items():
        if term in text:
            count = text.count(term)
            matches.append({"term": term, "definition": definition, "count": count})
    return matches


# ---------------------------------------------------------------------------
# 章节选择器
# ---------------------------------------------------------------------------

def render_chapter_selector(project_data: ProjectKnowledgeBase) -> Optional[int]:
    """
    渲染章节选择下拉框。

    Args:
        project_data: 项目知识库实例。

    Returns:
        选中的章节编号，无章节时返回 None。
    """
    if not project_data.chapters:
        st.info("📭 项目中暂无章节。请先通过大纲生成章节。")
        return None

    chapter_numbers = sorted(project_data.chapters.keys())
    chapter_options = {}
    for num in chapter_numbers:
        ch = project_data.chapters[num]
        label = f"第 {num} 章"
        if ch.title:
            label += f" - {ch.title}"
        chapter_options[label] = num

    selected_label = st.selectbox(
        "选择章节",
        options=list(chapter_options.keys()),
        key="editor_chapter_selector",
        help="选择要编辑的章节",
    )

    return chapter_options.get(selected_label)


# ---------------------------------------------------------------------------
# 章节内容编辑区
# ---------------------------------------------------------------------------

def render_chapter_content(chapter: Chapter, chapter_number: int) -> None:
    """
    渲染章节 Markdown 编辑区及元数据。

    Args:
        chapter: 章节对象。
        chapter_number: 章节编号。
    """
    # 加载章节内容
    content_key = f"chapter_content_{chapter_number}"
    if content_key not in st.session_state:
        st.session_state[content_key] = _load_chapter_content(chapter_number)

    # 元数据展示
    current_content = st.session_state[content_key]
    word_count = _compute_word_count(current_content)
    scene_count = _compute_scene_count(chapter)
    last_modified = _get_last_modified(chapter_number)

    meta_cols = st.columns(3)
    with meta_cols[0]:
        st.metric("字数", f"{word_count:,}")
    with meta_cols[1]:
        st.metric("场景数", scene_count)
    with meta_cols[2]:
        st.caption(f"最后修改: {last_modified}")

    st.divider()

    # Markdown 编辑器
    st.subheader(f"📝 第 {chapter_number} 章" + (f" — {chapter.title}" if chapter.title else ""))
    edited_content = st.text_area(
        "章节内容（Markdown）",
        value=current_content,
        height=500,
        key=f"editor_textarea_{chapter_number}",
        help="直接编辑章节的 Markdown 内容",
    )

    # 检测变更
    if edited_content != current_content:
        st.session_state[f"editor_dirty_{chapter_number}"] = True
        st.session_state[content_key] = edited_content
    else:
        st.session_state[f"editor_dirty_{chapter_number}"] = False


# ---------------------------------------------------------------------------
# 操作按钮区
# ---------------------------------------------------------------------------

def render_chapter_actions(chapter_number: int, project_data: ProjectKnowledgeBase) -> None:
    """
    渲染章节操作按钮：保存、重新生成、评审、添加引用、检查术语。

    Args:
        chapter_number: 章节编号。
        project_data: 项目知识库实例。
    """
    st.subheader("⚡ 操作")

    action_cols = st.columns(5)

    # ---- 保存 ----
    with action_cols[0]:
        is_dirty = st.session_state.get(f"editor_dirty_{chapter_number}", False)
        if st.button(
            "💾 保存",
            key=f"save_chapter_{chapter_number}",
            disabled=not is_dirty,
            use_container_width=True,
        ):
            content = st.session_state.get(f"chapter_content_{chapter_number}", "")
            with st.spinner("正在保存章节内容..."):
                if _save_chapter_content(chapter_number, content):
                    st.session_state[f"editor_dirty_{chapter_number}"] = False
                    st.success("✅ 章节已保存！")
                    st.rerun()

    # ---- 重新生成 ----
    with action_cols[1]:
        if st.button(
            "🔄 重新生成",
            key=f"regen_chapter_{chapter_number}",
            use_container_width=True,
        ):
            llm_client = _get_llm_client()
            if llm_client:
                with st.spinner(f"正在重新生成第 {chapter_number} 章..."):
                    try:
                        from libriscribe.agents.chapter_writer import ChapterWriterAgent
                        agent = ChapterWriterAgent(llm_client)
                        agent.execute(project_data, chapter_number)
                        # 重新加载内容
                        new_content = _load_chapter_content(chapter_number)
                        st.session_state[f"chapter_content_{chapter_number}"] = new_content
                        st.success("✅ 章节已重新生成！")
                        st.rerun()
                    except Exception as e:
                        st.error(f"重新生成失败: {e}")
                        logger.error(f"重新生成章节 {chapter_number} 失败: {e}", exc_info=True)

    # ---- 评审 ----
    with action_cols[2]:
        if st.button(
            "🔍 评审",
            key=f"review_chapter_{chapter_number}",
            use_container_width=True,
        ):
            llm_client = _get_llm_client()
            project_dir = _get_project_dir()
            if llm_client and project_dir:
                with st.spinner(f"正在评审第 {chapter_number} 章..."):
                    try:
                        from libriscribe.agents.content_reviewer import ContentReviewerAgent
                        agent = ContentReviewerAgent(llm_client)
                        chapter_path = str(Path(project_dir) / f"chapter_{chapter_number}.md")
                        review_result = agent.execute(chapter_path)
                        # 保存评审结果到知识库
                        review = ChapterReview(
                            iteration=len(project_data.chapter_reviews.get(chapter_number, [])) + 1,
                            score=review_result.get("score", 0.0),
                            suggestions=[review_result.get("review", "")],
                            reviewed_at=datetime.now().isoformat(),
                        )
                        project_data.add_review(chapter_number, review)
                        # 保存知识库
                        kb_path = Path(project_dir) / "project_data.json"
                        project_data.save_to_file(str(kb_path))
                        st.success("✅ 评审完成！请查看右侧面板。")
                        st.rerun()
                    except Exception as e:
                        st.error(f"评审失败: {e}")
                        logger.error(f"评审章节 {chapter_number} 失败: {e}", exc_info=True)

    # ---- 添加引用 ----
    with action_cols[3]:
        if st.button(
            "📚 添加引用",
            key=f"cite_chapter_{chapter_number}",
            use_container_width=True,
        ):
            llm_client = _get_llm_client()
            if llm_client:
                content = st.session_state.get(f"chapter_content_{chapter_number}", "")
                if not content.strip():
                    st.warning("章节内容为空，无法提取引用。")
                else:
                    with st.spinner(f"正在为第 {chapter_number} 章提取引用..."):
                        try:
                            from libriscribe.agents.citation_agent import CitationAgent
                            agent = CitationAgent(llm_client)
                            citations = agent.execute(project_data, chapter_number, content)
                            if citations:
                                for c in citations:
                                    project_data.add_citation(c)
                                # 保存知识库
                                project_dir = _get_project_dir()
                                if project_dir:
                                    kb_path = Path(project_dir) / "project_data.json"
                                    project_data.save_to_file(str(kb_path))
                                st.success(f"✅ 提取到 {len(citations)} 条引用！")
                            else:
                                st.info("未发现需要引用的内容。")
                            st.rerun()
                        except Exception as e:
                            st.error(f"引用提取失败: {e}")
                            logger.error(f"提取引用失败: {e}", exc_info=True)

    # ---- 检查术语 ----
    with action_cols[4]:
        if st.button(
            "📖 检查术语",
            key=f"check_terms_{chapter_number}",
            use_container_width=True,
        ):
            project_dir = _get_project_dir()
            if project_dir:
                with st.spinner("正在检查术语一致性..."):
                    try:
                        term_manager = TerminologyManager(project_dir)
                        term_manager.load()
                        content = st.session_state.get(f"chapter_content_{chapter_number}", "")
                        matches = _highlight_terminology(content, term_manager.get_all())
                        # 存入 session_state 供面板展示
                        st.session_state[f"term_matches_{chapter_number}"] = matches
                        if matches:
                            st.success(f"✅ 发现 {len(matches)} 个术语匹配。")
                        else:
                            st.info("未发现术语匹配（或术语表为空）。")
                        st.rerun()
                    except Exception as e:
                        st.error(f"术语检查失败: {e}")
                        logger.error(f"术语检查失败: {e}", exc_info=True)


# ---------------------------------------------------------------------------
# 评审反馈面板
# ---------------------------------------------------------------------------

def render_review_panel(chapter_number: int, project_data: ProjectKnowledgeBase) -> None:
    """
    渲染评审反馈侧边面板。

    Args:
        chapter_number: 章节编号。
        project_data: 项目知识库实例。
    """
    st.subheader("🔍 评审反馈")

    latest_review = project_data.get_latest_review(chapter_number)

    if not latest_review:
        st.info("暂无评审记录。点击「评审」按钮生成评审反馈。")
        return

    # 评分
    score_pct = int(latest_review.score * 100) if latest_review.score <= 1 else int(latest_review.score)
    st.metric("评分", f"{score_pct}%")

    # 评审轮次
    st.caption(f"评审轮次: 第 {latest_review.iteration} 轮 | {latest_review.reviewed_at}")

    # 建议
    if latest_review.suggestions:
        st.markdown("**评审意见：**")
        for i, suggestion in enumerate(latest_review.suggestions, 1):
            st.markdown(f"{i}. {suggestion}")

    # 一致性问题
    if latest_review.consistency_issues:
        st.markdown("**一致性问题：**")
        for issue in latest_review.consistency_issues:
            st.warning(issue)

    # 术语问题
    if latest_review.terminology_issues:
        st.markdown("**术语问题：**")
        for issue in latest_review.terminology_issues:
            st.error(issue)

    # 历史评审
    all_reviews = project_data.chapter_reviews.get(chapter_number, [])
    if len(all_reviews) > 1:
        with st.expander(f"历史评审记录 ({len(all_reviews)} 条)"):
            for rev in reversed(all_reviews[:-1]):
                st.caption(f"第 {rev.iteration} 轮 — 评分: {int(rev.score * 100)}% — {rev.reviewed_at}")


# ---------------------------------------------------------------------------
# 引用面板
# ---------------------------------------------------------------------------

def render_citation_panel(chapter_number: int, project_data: ProjectKnowledgeBase) -> None:
    """
    渲染引用溯源侧边面板。

    Args:
        chapter_number: 章节编号。
        project_data: 项目知识库实例。
    """
    st.subheader("📚 引用溯源")

    citations = project_data.get_citations_for_chapter(chapter_number)

    if not citations:
        st.info("暂无引用记录。点击「添加引用」按钮自动提取。")
        return

    st.caption(f"共 {len(citations)} 条引用")

    for i, citation in enumerate(citations, 1):
        with st.expander(f"引用 {i}: {citation.sentence[:50]}..."):
            st.markdown(f"**原句:** {citation.sentence}")
            if citation.source:
                st.markdown(f"**来源:** {citation.source}")
            if citation.page:
                st.markdown(f"**页码:** {citation.page}")
            if citation.quote_original:
                st.markdown(f"**原文引用:** {citation.quote_original}")
            if citation.formatted_ref:
                st.code(citation.formatted_ref, language=None)
            if citation.confidence > 0:
                st.progress(citation.confidence, text=f"置信度: {int(citation.confidence * 100)}%")


# ---------------------------------------------------------------------------
# 术语高亮面板
# ---------------------------------------------------------------------------

def render_terminology_panel(chapter_number: int, project_data: ProjectKnowledgeBase) -> None:
    """
    渲染术语高亮侧边面板。

    Args:
        chapter_number: 章节编号。
        project_data: 项目知识库实例。
    """
    st.subheader("📖 术语表")

    # 从 session_state 获取检查结果
    term_matches = st.session_state.get(f"term_matches_{chapter_number}", [])

    if term_matches:
        st.markdown(f"**本章匹配到 {len(term_matches)} 个术语：**")
        for match in term_matches:
            st.markdown(
                f"- **{match['term']}** (出现 {match['count']} 次): {match['definition']}"
            )
    else:
        # 显示全局术语表
        project_dir = _get_project_dir()
        if project_dir:
            try:
                term_manager = TerminologyManager(project_dir)
                term_manager.load()
                all_terms = term_manager.get_all()
                if all_terms:
                    st.caption(f"术语表共 {len(all_terms)} 个术语（尚未检查本章匹配）")
                    for term, defn in list(all_terms.items())[:20]:
                        st.markdown(f"- **{term}**: {defn}")
                    if len(all_terms) > 20:
                        st.caption(f"... 还有 {len(all_terms) - 20} 个术语")
                else:
                    st.info("术语表为空。")
            except Exception as e:
                st.warning(f"加载术语表失败: {e}")
        else:
            st.info("术语表为空。点击「检查术语」按钮进行检查。")


# ---------------------------------------------------------------------------
# 场景/大纲面板
# ---------------------------------------------------------------------------

def render_scene_panel(chapter: Chapter) -> None:
    """
    渲染章节场景/大纲侧边面板。

    Args:
        chapter: 章节对象。
    """
    st.subheader("📋 场景大纲")

    if not chapter.scenes:
        st.info("该章节暂无场景信息。")
        return

    for scene in sorted(chapter.scenes, key=lambda s: s.scene_number):
        with st.expander(f"场景 {scene.scene_number}" + (f": {scene.summary[:40]}..." if len(scene.summary) > 40 else f": {scene.summary}")):
            if scene.summary:
                st.markdown(f"**摘要:** {scene.summary}")
            if scene.setting:
                st.markdown(f"**场景:** {scene.setting}")
            if scene.characters:
                st.markdown(f"**角色:** {', '.join(scene.characters)}")
            if scene.goal:
                st.markdown(f"**目标:** {scene.goal}")
            if scene.emotional_beat:
                st.markdown(f"**情感基调:** {scene.emotional_beat}")


# ---------------------------------------------------------------------------
# 主渲染函数
# ---------------------------------------------------------------------------

def render_editor() -> None:
    """
    渲染章节编辑器主页面。

    布局：
    - 左侧（宽）：章节选择器 + 元数据 + Markdown 编辑器 + 操作按钮
    - 右侧（窄）：场景大纲 / 评审反馈 / 引用 / 术语（标签页切换）
    """
    st.title("📝 章节编辑器")

    # 检查项目是否加载
    project_data = _get_project_data()
    if not project_data:
        st.warning("⚠️ 请先加载或创建一个项目。")
        st.info("前往 **项目仪表盘** 页面加载项目，或通过 CLI 创建新项目。")
        return

    # 章节选择
    chapter_number = render_chapter_selector(project_data)
    if chapter_number is None:
        return

    chapter = project_data.get_chapter(chapter_number)
    if not chapter:
        st.error(f"第 {chapter_number} 章数据不存在。")
        return

    # 主布局：左侧编辑区 + 右侧面板
    left_col, right_col = st.columns([3, 1], gap="large")

    with left_col:
        # 章节内容编辑
        render_chapter_content(chapter, chapter_number)

        st.divider()

        # 操作按钮
        render_chapter_actions(chapter_number, project_data)

    with right_col:
        # 侧边面板（标签页切换）
        tab_scene, tab_review, tab_cite, tab_term = st.tabs(
            ["📋 大纲", "🔍 评审", "📚 引用", "📖 术语"]
        )

        with tab_scene:
            render_scene_panel(chapter)

        with tab_review:
            render_review_panel(chapter_number, project_data)

        with tab_cite:
            render_citation_panel(chapter_number, project_data)

        with tab_term:
            render_terminology_panel(chapter_number, project_data)


# ---------------------------------------------------------------------------
# Streamlit 页面入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    render_editor()
