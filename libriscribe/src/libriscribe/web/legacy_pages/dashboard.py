# src/libriscribe/web/pages/dashboard.py
"""项目仪表盘页面

展示项目概览、统计数据、章节进度、快速操作和项目健康指标。
"""

from typing import Optional, Dict, Any, List
from datetime import datetime

import streamlit as st

from libriscribe.knowledge_base import ProjectKnowledgeBase, ChapterReview


# ---------------------------------------------------------------------------
# 辅助：从 session_state 获取项目数据
# ---------------------------------------------------------------------------

def _get_project() -> Optional[ProjectKnowledgeBase]:
    """从 Streamlit session_state 获取当前项目数据。"""
    return st.session_state.get("project_data")


def _save_project(project: ProjectKnowledgeBase) -> None:
    """将项目数据保存回 session_state 并持久化到文件。"""
    st.session_state["project_data"] = project
    project_dir = project.project_dir
    if project_dir:
        save_path = str(project_dir / "knowledge_base.json")
        project.save_to_file(save_path)


# ---------------------------------------------------------------------------
# 统计计算
# ---------------------------------------------------------------------------

def _calc_stats(project: ProjectKnowledgeBase) -> Dict[str, Any]:
    """计算项目统计数据。"""
    chapters = project.chapters or {}
    total_chapters = len(chapters)

    # 已完成章节：有摘要或有场景的章节视为已完成
    completed_chapters = sum(
        1 for ch in chapters.values()
        if ch.summary or ch.scenes
    )

    # 总字数：基于摘要长度估算（实际项目中应从章节文件读取）
    total_word_count = sum(len(ch.summary) for ch in chapters.values())

    # 平均章节长度
    avg_chapter_length = (
        total_word_count // total_chapters if total_chapters > 0 else 0
    )

    # 术语数量
    terminology_count = len(project.terminology or {})

    # 引用数量
    citation_count = len(project.citations or [])

    # 评审记录数
    review_count = sum(
        len(reviews) for reviews in (project.chapter_reviews or {}).values()
    )

    # 平均评审分数
    all_scores = []
    for reviews in (project.chapter_reviews or {}).values():
        for review in reviews:
            if review.score > 0:
                all_scores.append(review.score)
    avg_review_score = sum(all_scores) / len(all_scores) if all_scores else 0.0

    # RAG 文档数
    rag_doc_count = len(project.rag_documents or [])

    return {
        "total_chapters": total_chapters,
        "completed_chapters": completed_chapters,
        "total_word_count": total_word_count,
        "avg_chapter_length": avg_chapter_length,
        "terminology_count": terminology_count,
        "citation_count": citation_count,
        "review_count": review_count,
        "avg_review_score": avg_review_score,
        "rag_doc_count": rag_doc_count,
    }


# ---------------------------------------------------------------------------
# 欢迎 / 设置页面（无项目时）
# ---------------------------------------------------------------------------

def _render_welcome() -> None:
    """当没有加载项目时显示欢迎页面。"""
    st.title("📚 好编辑 项目仪表盘")
    st.markdown("---")

    st.info("👋 欢迎使用好编辑！请先创建或加载一个项目。")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("🆕 创建新项目")
        st.markdown(
            "从零开始创建一个新项目，配置书名、类型、章节数等基本信息。"
        )
        if st.button("创建新项目", key="btn_create_project", use_container_width=True):
            st.session_state["current_page"] = "settings"
            st.rerun()

    with col2:
        st.subheader("📂 加载已有项目")
        st.markdown(
            "从本地文件系统加载一个已有的项目。"
        )
        project_path = st.text_input(
            "项目路径",
            placeholder="例如: D:/my_books/my_novel",
            key="input_project_path",
        )
        if st.button("加载项目", key="btn_load_project", use_container_width=True):
            if project_path:
                from pathlib import Path
                kb_path = Path(project_path) / "knowledge_base.json"
                project = ProjectKnowledgeBase.load_from_file(str(kb_path))
                if project:
                    st.session_state["project_data"] = project
                    st.success(f"✅ 项目 '{project.title}' 加载成功！")
                    st.rerun()
                else:
                    st.error(f"❌ 无法加载项目，请检查路径是否正确: {kb_path}")
            else:
                st.warning("请输入项目路径。")

    st.markdown("---")
    st.subheader("📖 快速开始")
    st.markdown("""
    1. **创建项目** — 填写书名、类型、目标读者等基本信息
    2. **生成大纲** — AI 根据你的设定自动生成章节大纲
    3. **撰写章节** — 逐章生成内容，支持 RAG 参考资料注入
    4. **审校优化** — AI 评审 + 人工修改，迭代提升质量
    5. **导出成书** — 支持 Markdown / DOCX / LaTeX / PDF 格式
    """)


# ---------------------------------------------------------------------------
# 项目概览卡片
# ---------------------------------------------------------------------------

def _render_overview_card(project: ProjectKnowledgeBase) -> None:
    """渲染项目概览卡片。"""
    st.subheader("📋 项目概览")

    col1, col2 = st.columns([2, 1])

    with col1:
        st.markdown(f"**书名：** {project.title}")
        st.markdown(f"**分类：** {project.category}")
        st.markdown(f"**类型：** {project.genre}")
        st.markdown(f"**语言：** {project.language}")
        st.markdown(f"**目标读者：** {project.target_audience}")
        st.markdown(f"**基调：** {project.tone}")

    with col2:
        st.markdown("**简介：**")
        st.caption(project.description or "暂无简介")

    # 时间信息
    if project.created_at or project.updated_at:
        st.markdown("---")
        time_cols = st.columns(2)
        with time_cols[0]:
            if project.created_at:
                st.caption(f"🕐 创建时间：{project.created_at[:19]}")
        with time_cols[1]:
            if project.updated_at:
                st.caption(f"🕐 最后更新：{project.updated_at[:19]}")


# ---------------------------------------------------------------------------
# 统计数据展示
# ---------------------------------------------------------------------------

def render_project_stats(project_data: Optional[ProjectKnowledgeBase] = None) -> None:
    """计算并展示项目统计数据。

    Args:
        project_data: 项目知识库对象。如果为 None，从 session_state 获取。
    """
    if project_data is None:
        project_data = _get_project()
    if project_data is None:
        return

    stats = _calc_stats(project_data)

    st.subheader("📊 项目统计")

    # 第一行：核心指标
    row1 = st.columns(4)
    with row1[0]:
        st.metric("总章节数", stats["total_chapters"])
    with row1[1]:
        st.metric("已完成章节", stats["completed_chapters"])
    with row1[2]:
        st.metric("总字数", f"{stats['total_word_count']:,}")
    with row1[3]:
        st.metric("平均章节字数", f"{stats['avg_chapter_length']:,}")

    # 第二行：扩展指标
    row2 = st.columns(4)
    with row2[0]:
        st.metric("术语数量", stats["terminology_count"])
    with row2[1]:
        st.metric("引用数量", stats["citation_count"])
    with row2[2]:
        st.metric("评审次数", stats["review_count"])
    with row2[3]:
        score_display = f"{stats['avg_review_score']:.1%}" if stats["avg_review_score"] > 0 else "N/A"
        st.metric("平均评审分数", score_display)

    # 完成率进度条
    if stats["total_chapters"] > 0:
        completion_rate = stats["completed_chapters"] / stats["total_chapters"]
        st.progress(completion_rate, text=f"整体完成率：{completion_rate:.0%}")
    else:
        st.progress(0, text="整体完成率：0%")


# ---------------------------------------------------------------------------
# 章节进度图表
# ---------------------------------------------------------------------------

def render_chapter_progress(project_data: Optional[ProjectKnowledgeBase] = None) -> None:
    """展示章节完成状态的进度图表。

    Args:
        project_data: 项目知识库对象。如果为 None，从 session_state 获取。
    """
    if project_data is None:
        project_data = _get_project()
    if project_data is None:
        return

    st.subheader("📈 章节进度")

    chapters = project_data.chapters or {}
    if not chapters:
        st.info("📭 尚未创建任何章节。请先生成大纲或手动添加章节。")
        return

    # 构建进度数据
    progress_data = []
    for ch_num in sorted(chapters.keys()):
        ch = chapters[ch_num]
        # 计算完成度：有标题 20% + 有摘要 30% + 有场景 30% + 有评审 20%
        completion = 0.0
        if ch.title:
            completion += 0.2
        if ch.summary:
            completion += 0.3
        if ch.scenes:
            completion += 0.3
        if project_data.chapter_reviews.get(ch_num):
            latest_review = project_data.get_latest_review(ch_num)
            if latest_review and latest_review.score > 0:
                completion += 0.2

        progress_data.append({
            "章节": f"第{ch_num}章",
            "完成度": round(completion * 100, 1),
            "标题": ch.title or f"第{ch_num}章（未命名）",
        })

    # 使用 st.bar_chart 展示
    import pandas as pd
    df = pd.DataFrame(progress_data)
    chart_df = df.set_index("章节")[["完成度"]]
    st.bar_chart(chart_df, height=300)

    # 详细进度列表
    with st.expander("📑 查看章节详情", expanded=False):
        for item in progress_data:
            col_a, col_b, col_c = st.columns([2, 4, 1])
            with col_a:
                st.markdown(f"**{item['章节']}**")
            with col_b:
                st.progress(item["完成度"] / 100, text=item["标题"])
            with col_c:
                st.caption(f"{item['完成度']:.0f}%")


# ---------------------------------------------------------------------------
# 最近活动
# ---------------------------------------------------------------------------

def _render_recent_activity(project: ProjectKnowledgeBase) -> None:
    """展示最近修改的章节。"""
    st.subheader("🕐 最近活动")

    chapters = project.chapters or {}
    if not chapters:
        st.info("暂无活动记录。")
        return

    # 按章节号倒序排列，取最近 5 个
    recent_chapters = sorted(chapters.items(), key=lambda x: x[0], reverse=True)[:5]

    for ch_num, ch in recent_chapters:
        # 获取最新评审
        latest_review = project.get_latest_review(ch_num)
        review_info = ""
        if latest_review:
            review_info = f" | 评审分数: {latest_review.score:.0%}"

        # 状态标签
        if ch.summary and ch.scenes:
            status = "✅ 已完成"
        elif ch.summary:
            status = "📝 有摘要"
        elif ch.title:
            status = "📋 仅有标题"
        else:
            status = "⬜ 未开始"

        st.markdown(
            f"- **第{ch_num}章** — {ch.title or '未命名'} — {status}{review_info}"
        )


# ---------------------------------------------------------------------------
# 快速操作
# ---------------------------------------------------------------------------

def render_quick_actions(project_data: Optional[ProjectKnowledgeBase] = None) -> None:
    """渲染快速操作按钮。

    每个按钮触发对应的代理操作，显示 spinner 并更新 session_state。

    Args:
        project_data: 项目知识库对象。如果为 None，从 session_state 获取。
    """
    if project_data is None:
        project_data = _get_project()
    if project_data is None:
        return

    st.subheader("⚡ 快速操作")

    col1, col2, col3, col4 = st.columns(4)

    # ---- 生成大纲 ----
    with col1:
        if st.button("📝 生成大纲", key="btn_gen_outline", use_container_width=True):
            with st.spinner("正在生成大纲..."):
                try:
                    from libriscribe.agents.outliner import OutlinerAgent
                    from libriscribe.utils.llm_client import LLMClient

                    llm_client = LLMClient(provider=project_data.llm_provider)
                    agent = OutlinerAgent(llm_client=llm_client)
                    result = agent.execute(project_data)
                    if result:
                        _save_project(project_data)
                        st.success("✅ 大纲生成完成！")
                        st.session_state["last_action"] = "outline_generated"
                    else:
                        st.warning("⚠️ 大纲生成未返回结果。")
                except Exception as e:
                    st.error(f"❌ 大纲生成失败：{e}")

    # ---- 撰写下一章 ----
    with col2:
        # 找到下一个待写章节
        chapters = project_data.chapters or {}
        next_chapter = None
        for ch_num in sorted(chapters.keys()):
            ch = chapters[ch_num]
            if not ch.summary:
                next_chapter = ch_num
                break

        btn_label = f"✍️ 写第{next_chapter}章" if next_chapter else "✍️ 写下一章"
        disabled = next_chapter is None and not chapters

        if st.button(btn_label, key="btn_write_chapter", use_container_width=True, disabled=disabled):
            if next_chapter is None:
                st.warning("⚠️ 所有章节已完成，或请先生成大纲。")
            else:
                with st.spinner(f"正在撰写第{next_chapter}章..."):
                    try:
                        from libriscribe.agents.chapter_writer import ChapterWriterAgent
                        from libriscribe.utils.llm_client import LLMClient

                        llm_client = LLMClient(provider=project_data.llm_provider)
                        agent = ChapterWriterAgent(llm_client=llm_client)
                        result = agent.execute(project_data, chapter_number=next_chapter)
                        if result:
                            _save_project(project_data)
                            st.success(f"✅ 第{next_chapter}章撰写完成！")
                            st.session_state["last_action"] = f"chapter_{next_chapter}_written"
                        else:
                            st.warning("⚠️ 章节撰写未返回结果。")
                    except Exception as e:
                        st.error(f"❌ 章节撰写失败：{e}")

    # ---- 审校章节 ----
    with col3:
        if st.button("🔍 审校章节", key="btn_review_chapter", use_container_width=True):
            # 选择要审校的章节
            chapters = project_data.chapters or {}
            reviewable = [
                ch_num for ch_num, ch in chapters.items()
                if ch.summary
            ]
            if not reviewable:
                st.warning("⚠️ 没有可审校的章节，请先撰写章节内容。")
            else:
                # 默认审校最新完成的章节
                target_chapter = max(reviewable)
                with st.spinner(f"正在审校第{target_chapter}章..."):
                    try:
                        from libriscribe.agents.content_reviewer import ContentReviewerAgent
                        from libriscribe.utils.llm_client import LLMClient

                        llm_client = LLMClient(provider=project_data.llm_provider)
                        agent = ContentReviewerAgent(llm_client=llm_client)
                        result = agent.execute(project_data, chapter_number=target_chapter)
                        if result:
                            _save_project(project_data)
                            st.success(f"✅ 第{target_chapter}章审校完成！")
                            st.session_state["last_action"] = f"chapter_{target_chapter}_reviewed"
                        else:
                            st.warning("⚠️ 审校未返回结果。")
                    except Exception as e:
                        st.error(f"❌ 审校失败：{e}")

    # ---- 导出书籍 ----
    with col4:
        export_format = st.selectbox(
            "导出格式",
            ["Markdown", "DOCX", "LaTeX", "PDF"],
            key="select_export_format",
        )
        if st.button("📦 导出书籍", key="btn_export", use_container_width=True):
            with st.spinner(f"正在导出为 {export_format}..."):
                try:
                    from libriscribe.agents.formatting import FormattingAgent
                    from libriscribe.utils.llm_client import LLMClient

                    llm_client = LLMClient(provider=project_data.llm_provider)
                    agent = FormattingAgent(llm_client=llm_client)
                    result = agent.execute(project_data, output_format=export_format.lower())
                    if result:
                        st.success(f"✅ 书籍已导出为 {export_format} 格式！")
                        st.session_state["last_action"] = f"exported_{export_format.lower()}"
                    else:
                        st.warning("⚠️ 导出未返回结果。")
                except Exception as e:
                    st.error(f"❌ 导出失败：{e}")


# ---------------------------------------------------------------------------
# 项目健康指标
# ---------------------------------------------------------------------------

def _render_health_indicators(project: ProjectKnowledgeBase) -> None:
    """展示项目健康指标：术语一致性、引用覆盖率、评审分数。"""
    st.subheader("🏥 项目健康")

    col1, col2, col3 = st.columns(3)

    # 术语一致性
    with col1:
        terminology_count = len(project.terminology or {})
        if terminology_count > 0:
            # 简单指标：术语数量越多，一致性保障越好
            consistency_score = min(terminology_count / 20, 1.0)  # 20个术语为满分
            st.metric("术语一致性", f"{consistency_score:.0%}")
            st.progress(consistency_score)
            st.caption(f"已定义 {terminology_count} 个术语")
        else:
            st.metric("术语一致性", "N/A")
            st.progress(0)
            st.caption("尚未定义术语表")

    # 引用覆盖率
    with col2:
        citation_count = len(project.citations or [])
        chapters = project.chapters or {}
        completed_count = sum(
            1 for ch in chapters.values() if ch.summary
        )
        if completed_count > 0 and citation_count > 0:
            # 每章至少 1 条引用为满分
            coverage = min(citation_count / completed_count, 1.0)
            st.metric("引用覆盖率", f"{coverage:.0%}")
            st.progress(coverage)
            st.caption(f"{citation_count} 条引用 / {completed_count} 个已完成章节")
        else:
            st.metric("引用覆盖率", "N/A")
            st.progress(0)
            st.caption("暂无引用数据")

    # 评审分数
    with col3:
        all_scores = []
        for reviews in (project.chapter_reviews or {}).values():
            for review in reviews:
                if review.score > 0:
                    all_scores.append(review.score)
        if all_scores:
            avg_score = sum(all_scores) / len(all_scores)
            st.metric("平均评审分数", f"{avg_score:.0%}")
            st.progress(avg_score)
            st.caption(f"共 {len(all_scores)} 次评审")
        else:
            st.metric("平均评审分数", "N/A")
            st.progress(0)
            st.caption("暂无评审记录")


# ---------------------------------------------------------------------------
# 主渲染函数
# ---------------------------------------------------------------------------

def render_dashboard() -> None:
    """渲染项目仪表盘主页面。

    根据 session_state 中是否有项目数据，展示欢迎页面或项目仪表盘。
    """
    project = _get_project()

    # 无项目时显示欢迎页面
    if project is None:
        _render_welcome()
        return

    # ---- 有项目时显示完整仪表盘 ----

    # 页面标题
    st.title(f"📚 {project.title}")
    st.caption(f"项目仪表盘 · {project.project_name}")

    # 上次操作反馈
    last_action = st.session_state.pop("last_action", None)
    if last_action:
        action_messages = {
            "outline_generated": "📝 大纲已生成",
            "exported_markdown": "📦 已导出为 Markdown",
            "exported_docx": "📦 已导出为 DOCX",
            "exported_latex": "📦 已导出为 LaTeX",
            "exported_pdf": "📦 已导出为 PDF",
        }
        msg = action_messages.get(last_action, f"✅ 操作完成：{last_action}")
        st.toast(msg)

    st.markdown("---")

    # 项目概览卡片
    _render_overview_card(project)

    st.markdown("---")

    # 统计数据
    render_project_stats(project)

    st.markdown("---")

    # 章节进度图表
    render_chapter_progress(project)

    st.markdown("---")

    # 最近活动 + 项目健康（并排）
    left_col, right_col = st.columns([3, 2])
    with left_col:
        _render_recent_activity(project)
    with right_col:
        _render_health_indicators(project)

    st.markdown("---")

    # 快速操作
    render_quick_actions(project)
