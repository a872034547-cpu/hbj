# src/libriscribe/web/pages/outline.py
"""大纲管理页面 - Streamlit Web UI

提供书籍概念展示/编辑、章节大纲树状视图、场景详情、
章节/场景的增删改查、以及大纲生成/重新生成功能。
"""

import logging
from typing import Dict, List, Optional, Any

import streamlit as st

from libriscribe.knowledge_base import (
    ProjectKnowledgeBase,
    Chapter,
    Scene,
    Character,
)
from libriscribe.utils.llm_client import LLMClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 辅助工具
# ---------------------------------------------------------------------------

def _get_project() -> Optional[ProjectKnowledgeBase]:
    """从 session_state 获取当前项目知识库。"""
    return st.session_state.get("project")


def _save_project(project: ProjectKnowledgeBase) -> None:
    """将修改后的项目知识库写回 session_state 并持久化。"""
    st.session_state["project"] = project
    if project.project_dir:
        try:
            project.save_to_file(str(project.project_dir / "knowledge_base.json"))
        except Exception as exc:
            logger.error("保存项目失败: %s", exc)
            st.error(f"保存项目失败: {exc}")


def _get_llm_client() -> Optional[LLMClient]:
    """从 session_state 获取 LLM 客户端。"""
    return st.session_state.get("llm_client")


# ---------------------------------------------------------------------------
# 1. render_concept_section — 书籍概念展示与编辑
# ---------------------------------------------------------------------------

def render_concept_section(project: ProjectKnowledgeBase) -> None:
    """展示并允许编辑书籍概念信息。

    包括：标题、类型、简介、基调、目标读者、logline 等。
    """
    st.subheader("📖 书籍概念")

    with st.expander("查看 / 编辑书籍概念", expanded=False):
        col1, col2 = st.columns(2)

        with col1:
            new_title = st.text_input("书名", value=project.title, key="concept_title")
            new_genre = st.text_input("类型", value=project.genre, key="concept_genre")
            new_tone = st.text_input("基调", value=project.tone, key="concept_tone")
            new_language = st.text_input("语言", value=project.language, key="concept_language")

        with col2:
            new_category = st.text_input("分类", value=project.category, key="concept_category")
            new_audience = st.text_input("目标读者", value=project.target_audience, key="concept_audience")
            new_book_length = st.text_input("篇幅", value=project.book_length, key="concept_book_length")
            new_num_chapters = st.text_input(
                "章节数",
                value=str(project.num_chapters_str or project.num_chapters),
                key="concept_num_chapters",
            )

        new_description = st.text_area(
            "书籍简介",
            value=project.description,
            height=120,
            key="concept_description",
        )
        new_logline = st.text_area(
            "Logline（一句话概括）",
            value=project.logline,
            height=80,
            key="concept_logline",
        )

        if st.button("💾 保存概念修改", key="save_concept"):
            project.title = new_title
            project.genre = new_genre
            project.tone = new_tone
            project.language = new_language
            project.category = new_category
            project.target_audience = new_audience
            project.book_length = new_book_length
            project.description = new_description
            project.logline = new_logline
            _save_project(project)
            st.success("✅ 书籍概念已更新！")

    # 只读摘要卡片
    st.markdown(
        f"""
        | 字段 | 值 |
        |------|-----|
        | **书名** | {project.title} |
        | **类型** | {project.genre} |
        | **分类** | {project.category} |
        | **基调** | {project.tone} |
        | **目标读者** | {project.target_audience} |
        | **篇幅** | {project.book_length} |
        | **Logline** | {project.logline} |
        """
    )


# ---------------------------------------------------------------------------
# 2. render_scene_detail — 单个场景详情
# ---------------------------------------------------------------------------

def render_scene_detail(
    scene: Scene,
    chapter_number: int,
    scene_number: int,
    project: ProjectKnowledgeBase,
) -> None:
    """渲染单个场景的详情卡片，支持内联编辑。"""

    scene_key = f"ch{chapter_number}_sc{scene_number}"

    with st.expander(
        f"🎬 场景 {scene_number}: {scene.summary[:60] or '(无摘要)'}",
        expanded=False,
    ):
        col1, col2 = st.columns([3, 1])

        with col1:
            new_summary = st.text_area(
                "场景摘要",
                value=scene.summary,
                height=100,
                key=f"scene_summary_{scene_key}",
            )
            new_setting = st.text_input(
                "场景地点 / 环境",
                value=scene.setting,
                key=f"scene_setting_{scene_key}",
            )
            new_goal = st.text_area(
                "场景目标",
                value=scene.goal,
                height=68,
                key=f"scene_goal_{scene_key}",
            )
            new_emotional_beat = st.text_input(
                "情感节拍",
                value=scene.emotional_beat,
                key=f"scene_emotion_{scene_key}",
            )

        with col2:
            # 角色多选
            all_char_names = list(project.characters.keys())
            current_chars = [c for c in scene.characters if c in all_char_names]
            new_characters = st.multiselect(
                "出场角色",
                options=all_char_names,
                default=current_chars,
                key=f"scene_chars_{scene_key}",
            )

            # 角色信息速览
            if new_characters:
                st.markdown("**角色速览**")
                for cname in new_characters:
                    char = project.characters.get(cname)
                    if char:
                        st.caption(f"🧑 {cname}: {char.role or '未设定角色'}")

        # 保存 / 删除按钮
        btn_col1, btn_col2 = st.columns(2)
        with btn_col1:
            if st.button("💾 保存场景", key=f"save_scene_{scene_key}"):
                scene.summary = new_summary
                scene.setting = new_setting
                scene.goal = new_goal
                scene.emotional_beat = new_emotional_beat
                scene.characters = new_characters
                _save_project(project)
                st.success(f"✅ 场景 {scene_number} 已保存")

        with btn_col2:
            if st.button("🗑️ 删除场景", key=f"del_scene_{scene_key}"):
                chapter = project.get_chapter(chapter_number)
                if chapter:
                    chapter.scenes = [
                        s for s in chapter.scenes if s.scene_number != scene_number
                    ]
                    # 重新编号
                    for idx, s in enumerate(chapter.scenes, start=1):
                        s.scene_number = idx
                    _save_project(project)
                    st.success(f"🗑️ 场景 {scene_number} 已删除")
                    st.rerun()


# ---------------------------------------------------------------------------
# 3. render_chapter_detail — 单个章节详情
# ---------------------------------------------------------------------------

def render_chapter_detail(
    chapter: Chapter,
    chapter_number: int,
    project: ProjectKnowledgeBase,
) -> None:
    """渲染单个章节的详情，包含场景列表和编辑功能。"""

    ch_key = f"ch{chapter_number}"

    with st.expander(
        f"📕 第 {chapter_number} 章: {chapter.title or '(未命名)'}",
        expanded=False,
    ):
        # --- 章节元信息编辑 ---
        col1, col2 = st.columns([3, 1])

        with col1:
            new_title = st.text_input(
                "章节标题",
                value=chapter.title,
                key=f"ch_title_{ch_key}",
            )
            new_summary = st.text_area(
                "章节摘要",
                value=chapter.summary,
                height=120,
                key=f"ch_summary_{ch_key}",
            )

        with col2:
            word_count_target = st.number_input(
                "目标字数",
                min_value=0,
                max_value=50000,
                value=int(
                    getattr(chapter, "word_count_target", 0) or 0
                ),
                step=500,
                key=f"ch_wc_{ch_key}",
            )
            st.metric("场景数", len(chapter.scenes))

        # 保存章节信息
        if st.button("💾 保存章节信息", key=f"save_ch_{ch_key}"):
            chapter.title = new_title
            chapter.summary = new_summary
            if hasattr(chapter, "word_count_target"):
                chapter.word_count_target = word_count_target
            _save_project(project)
            st.success(f"✅ 第 {chapter_number} 章信息已保存")

        st.divider()

        # --- 场景列表 ---
        st.markdown(f"**🎬 场景列表**（共 {len(chapter.scenes)} 个）")

        if not chapter.scenes:
            st.info("暂无场景。点击下方按钮添加。")
        else:
            for scene in chapter.scenes:
                render_scene_detail(scene, chapter_number, scene.scene_number, project)

        # --- 添加场景 ---
        st.markdown("---")
        add_col1, add_col2 = st.columns([3, 1])
        with add_col1:
            new_scene_summary = st.text_input(
                "新场景摘要",
                key=f"new_scene_summary_{ch_key}",
                placeholder="输入新场景的简要描述...",
            )
        with add_col2:
            st.write("")  # 垂直对齐
            if st.button("➕ 添加场景", key=f"add_scene_{ch_key}"):
                if new_scene_summary.strip():
                    new_scene = Scene(
                        scene_number=len(chapter.scenes) + 1,
                        summary=new_scene_summary.strip(),
                    )
                    chapter.scenes.append(new_scene)
                    _save_project(project)
                    st.success(f"✅ 场景已添加到第 {chapter_number} 章")
                    st.rerun()
                else:
                    st.warning("请输入场景摘要")

        # --- 删除章节 ---
        st.markdown("---")
        if st.button(
            f"🗑️ 删除第 {chapter_number} 章",
            key=f"del_ch_{ch_key}",
            type="secondary",
        ):
            del project.chapters[chapter_number]
            # 重新编号剩余章节
            sorted_keys = sorted(project.chapters.keys())
            new_chapters: Dict[int, Chapter] = {}
            for new_idx, old_key in enumerate(sorted_keys, start=1):
                ch = project.chapters[old_key]
                ch.chapter_number = new_idx
                new_chapters[new_idx] = ch
            project.chapters = new_chapters
            _save_project(project)
            st.success(f"🗑️ 第 {chapter_number} 章已删除，章节已重新编号")
            st.rerun()


# ---------------------------------------------------------------------------
# 4. render_chapter_tree — 章节大纲树状视图
# ---------------------------------------------------------------------------

def render_chapter_tree(project: ProjectKnowledgeBase) -> None:
    """渲染完整的章节大纲树状视图。"""

    st.subheader("📑 章节大纲")

    chapters = project.chapters

    if not chapters:
        st.info("📭 暂无章节大纲。请先生成大纲或手动添加章节。")
        return

    # --- 章节排序与导航 ---
    sorted_chapter_nums = sorted(chapters.keys())

    # 快速导航
    nav_options = [
        f"第 {num} 章: {chapters[num].title or '(未命名)'}"
        for num in sorted_chapter_nums
    ]
    selected_nav = st.selectbox(
        "🔍 快速跳转",
        options=["全部展开"] + nav_options,
        key="chapter_nav",
    )

    # --- 统计概览 ---
    total_scenes = sum(len(ch.scenes) for ch in chapters.values())
    total_chars_used = set()
    for ch in chapters.values():
        for sc in ch.scenes:
            total_chars_used.update(sc.characters)

    stat_col1, stat_col2, stat_col3 = st.columns(3)
    stat_col1.metric("总章节数", len(chapters))
    stat_col2.metric("总场景数", total_scenes)
    stat_col3.metric("涉及角色数", len(total_chars_used))

    st.markdown("---")

    # --- 章节排序操作（上移/下移） ---
    for idx, ch_num in enumerate(sorted_chapter_nums):
        chapter = chapters[ch_num]

        # 如果选择了特定章节导航，只显示该章节
        if selected_nav != "全部展开":
            if f"第 {ch_num} 章" not in selected_nav:
                continue

        # 排序按钮
        move_col1, move_col2, content_col = st.columns([0.5, 0.5, 9])

        with move_col1:
            if idx > 0:
                if st.button("⬆️", key=f"up_ch_{ch_num}"):
                    prev_num = sorted_chapter_nums[idx - 1]
                    # 交换 chapter_number
                    chapter.chapter_number = prev_num
                    chapters[prev_num].chapter_number = ch_num
                    # 交换字典键
                    project.chapters[prev_num] = chapter
                    project.chapters[ch_num] = chapters[prev_num]
                    _save_project(project)
                    st.rerun()

        with move_col2:
            if idx < len(sorted_chapter_nums) - 1:
                if st.button("⬇️", key=f"down_ch_{ch_num}"):
                    next_num = sorted_chapter_nums[idx + 1]
                    chapter.chapter_number = next_num
                    chapters[next_num].chapter_number = ch_num
                    project.chapters[next_num] = chapter
                    project.chapters[ch_num] = chapters[next_num]
                    _save_project(project)
                    st.rerun()

        with content_col:
            render_chapter_detail(chapter, ch_num, project)

    # --- 添加新章节 ---
    st.markdown("---")
    st.markdown("### ➕ 添加新章节")

    add_col1, add_col2, add_col3 = st.columns([4, 3, 1])

    with add_col1:
        new_ch_title = st.text_input(
            "新章节标题",
            key="new_ch_title",
            placeholder="输入章节标题...",
        )
    with add_col2:
        new_ch_summary = st.text_area(
            "新章节摘要",
            key="new_ch_summary",
            placeholder="输入章节摘要...",
            height=68,
        )
    with add_col3:
        st.write("")  # 垂直对齐
        if st.button("➕ 添加章节", key="add_chapter_btn"):
            if new_ch_title.strip() or new_ch_summary.strip():
                new_ch_num = max(chapters.keys(), default=0) + 1
                new_chapter = Chapter(
                    chapter_number=new_ch_num,
                    title=new_ch_title.strip(),
                    summary=new_ch_summary.strip(),
                )
                project.chapters[new_ch_num] = new_chapter
                _save_project(project)
                st.success(f"✅ 第 {new_ch_num} 章已添加")
                st.rerun()
            else:
                st.warning("请输入章节标题或摘要")


# ---------------------------------------------------------------------------
# 5. render_outline_actions — 大纲生成 / 重新生成
# ---------------------------------------------------------------------------

def render_outline_actions(project: ProjectKnowledgeBase) -> None:
    """渲染大纲生成和重新生成的操作按钮区域。"""

    st.subheader("⚡ 大纲操作")

    action_col1, action_col2, action_col3 = st.columns(3)

    with action_col1:
        generate_disabled = bool(project.chapters)
        if st.button(
            "🤖 生成大纲",
            key="generate_outline",
            disabled=generate_disabled,
            use_container_width=True,
        ):
            _generate_outline(project, regenerate=False)

    with action_col2:
        regenerate_disabled = not bool(project.chapters)
        if st.button(
            "🔄 重新生成大纲",
            key="regenerate_outline",
            disabled=regenerate_disabled,
            use_container_width=True,
        ):
            _generate_outline(project, regenerate=True)

    with action_col3:
        if st.button(
            "🗑️ 清空大纲",
            key="clear_outline",
            disabled=not bool(project.chapters),
            use_container_width=True,
        ):
            project.chapters = {}
            project.outline = ""
            _save_project(project)
            st.success("🗑️ 大纲已清空")
            st.rerun()

    # 显示当前大纲 Markdown（如果有）
    if project.outline:
        with st.expander("📄 原始大纲 Markdown", expanded=False):
            st.markdown(project.outline)


def _generate_outline(
    project: ProjectKnowledgeBase,
    regenerate: bool = False,
) -> None:
    """调用 OutlinerAgent 生成或重新生成大纲。"""

    llm_client = _get_llm_client()
    if llm_client is None:
        st.error("❌ LLM 客户端未初始化，请先在设置中配置 API Key。")
        return

    action_text = "重新生成" if regenerate else "生成"
    st.info(f"🤖 正在{action_text}大纲，请稍候...")

    try:
        from libriscribe.agents.outliner import OutlinerAgent

        agent = OutlinerAgent(llm_client)

        with st.spinner(f"正在{action_text}大纲..."):
            agent.execute(project)

        _save_project(project)
        st.success(f"✅ 大纲{action_text}完成！共 {len(project.chapters)} 章")
        st.rerun()

    except ImportError:
        st.error("❌ 无法导入 OutlinerAgent，请检查 libriscribe 安装。")
    except Exception as exc:
        logger.exception("大纲生成失败: %s", exc)
        st.error(f"❌ 大纲{action_text}失败: {exc}")


# ---------------------------------------------------------------------------
# 6. render_references — 角色与世界观参考
# ---------------------------------------------------------------------------

def render_references(project: ProjectKnowledgeBase) -> None:
    """展示角色和世界观参考信息，供大纲编辑时参考。"""

    st.subheader("📚 参考资料")

    ref_col1, ref_col2 = st.columns(2)

    with ref_col1:
        with st.expander("🧑 角色列表", expanded=False):
            if not project.characters:
                st.info("暂无角色信息。")
            else:
                for name, char in project.characters.items():
                    st.markdown(
                        f"**{name}** — {char.role or '未设定'}  \n"
                        f"_{char.personality_traits or '无性格描述'}_"
                    )

    with ref_col2:
        with st.expander("🌍 世界观设定", expanded=False):
            wb = project.worldbuilding
            if wb is None:
                st.info("暂无世界观设定。")
            else:
                for field_name in [
                    "geography",
                    "culture_and_society",
                    "history",
                    "rules_and_laws",
                    "technology_level",
                    "magic_system",
                    "key_locations",
                ]:
                    value = getattr(wb, field_name, "")
                    if value:
                        label = field_name.replace("_", " ").title()
                        st.markdown(f"**{label}:** {value[:200]}{'...' if len(value) > 200 else ''}")


# ---------------------------------------------------------------------------
# 7. render_outline — 主入口函数
# ---------------------------------------------------------------------------

def render_outline() -> None:
    """大纲管理页面主入口。

    整合概念展示、章节树、大纲操作和参考资料四个区域。
    """

    st.title("📋 大纲管理")

    project = _get_project()

    if project is None:
        st.warning("⚠️ 请先创建或加载一个项目。")
        st.info("💡 前往 **仪表盘** 页面创建新项目，或加载已有项目。")
        return

    # 页面布局：主内容 + 侧边参考
    main_col, ref_col = st.columns([3, 1])

    with main_col:
        # 1. 书籍概念
        render_concept_section(project)

        st.markdown("---")

        # 2. 大纲操作按钮
        render_outline_actions(project)

        st.markdown("---")

        # 3. 章节大纲树
        render_chapter_tree(project)

    with ref_col:
        # 4. 参考资料（侧边栏）
        render_references(project)
