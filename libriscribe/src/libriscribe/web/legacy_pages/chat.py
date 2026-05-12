# src/libriscribe/web/pages/chat.py
"""
聊天式指令界面

提供自然语言和斜杠命令两种交互方式，支持：
- 章节写作、审阅、编辑
- 大纲、概念、角色、世界观生成
- 引用提取、导出、术语管理
- 自然语言意图识别（通过 LLM）
"""

import logging
import re
import traceback
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st

from libriscribe.knowledge_base import ProjectKnowledgeBase
from libriscribe.utils.llm_client import LLMClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

HELP_TEXT = """📖 **可用命令**

| 命令 | 说明 |
|------|------|
| `/write [章节号]` | 撰写指定章节 |
| `/review [章节号]` | 审阅指定章节 |
| `/edit [章节号]` | 编辑指定章节 |
| `/outline` | 生成大纲 |
| `/concept` | 生成概念 |
| `/characters` | 生成角色 |
| `/worldbuilding` | 生成世界观 |
| `/cite [章节号]` | 提取章节引用 |
| `/export [格式]` | 导出书籍（docx / latex / pdf） |
| `/terminology add [术语] [定义]` | 添加术语 |
| `/terminology search [关键词]` | 搜索术语 |
| `/terminology list` | 列出所有术语 |
| `/help` | 显示此帮助信息 |

你也可以用自然语言描述需求，例如：
- "帮我写第三章"
- "检查一下第二章有没有问题"
- "把这本书导出为 Word 文档"
"""

# ---------------------------------------------------------------------------
# 辅助：初始化 session state
# ---------------------------------------------------------------------------


def _init_session_state():
    """确保 chat 相关的 session_state 键存在。"""
    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = []
    if "project_data" not in st.session_state:
        st.session_state.project_data = None
    if "llm_client" not in st.session_state:
        st.session_state.llm_client = None


def _get_project() -> Optional[ProjectKnowledgeBase]:
    """从 session_state 获取当前项目。"""
    return st.session_state.get("project_data")


def _get_llm_client() -> Optional[LLMClient]:
    """从 session_state 获取 LLM 客户端。"""
    return st.session_state.get("llm_client")


def _append_message(role: str, content: str):
    """向聊天历史追加一条消息。"""
    st.session_state.chat_messages.append({"role": role, "content": content})


def _read_chapter_content(project: ProjectKnowledgeBase, chapter_number: int) -> str:
    """尝试读取章节文件内容。"""
    if not project.project_dir:
        return ""
    from pathlib import Path

    chapter_dir = Path(project.project_dir) / "chapters"
    # 尝试常见文件名模式
    for pattern in [
        f"chapter_{chapter_number:02d}.md",
        f"chapter_{chapter_number}.md",
        f"ch{chapter_number}.md",
    ]:
        path = chapter_dir / pattern
        if path.exists():
            return path.read_text(encoding="utf-8")
    return ""


# ---------------------------------------------------------------------------
# 命令处理
# ---------------------------------------------------------------------------


def process_command(command: str, project_data: Optional[ProjectKnowledgeBase] = None) -> str:
    """
    解析并执行斜杠命令。

    Args:
        command: 用户输入的命令字符串（以 / 开头）。
        project_data: 当前项目知识库。

    Returns:
        命令执行结果的文本消息。
    """
    command = command.strip()
    parts = command.split(maxsplit=2)
    cmd = parts[0].lower()
    args = parts[1:] if len(parts) > 1 else []

    llm_client = _get_llm_client()
    project = project_data or _get_project()

    # ---- /help ----
    if cmd == "/help":
        return HELP_TEXT

    # ---- /write ----
    if cmd == "/write":
        return _cmd_write(args, project, llm_client)

    # ---- /review ----
    if cmd == "/review":
        return _cmd_review(args, project, llm_client)

    # ---- /edit ----
    if cmd == "/edit":
        return _cmd_edit(args, project, llm_client)

    # ---- /outline ----
    if cmd == "/outline":
        return _cmd_outline(project, llm_client)

    # ---- /concept ----
    if cmd == "/concept":
        return _cmd_concept(project, llm_client)

    # ---- /characters ----
    if cmd == "/characters":
        return _cmd_characters(project, llm_client)

    # ---- /worldbuilding ----
    if cmd == "/worldbuilding":
        return _cmd_worldbuilding(project, llm_client)

    # ---- /cite ----
    if cmd == "/cite":
        return _cmd_cite(args, project, llm_client)

    # ---- /export ----
    if cmd == "/export":
        return _cmd_export(args, project)

    # ---- /terminology ----
    if cmd == "/terminology":
        return _cmd_terminology(args, project)

    return f"⚠️ 未知命令：`{cmd}`。输入 `/help` 查看可用命令。"


# ---------------------------------------------------------------------------
# 各命令实现
# ---------------------------------------------------------------------------


def _cmd_write(
    args: List[str],
    project: Optional[ProjectKnowledgeBase],
    llm_client: Optional[LLMClient],
) -> str:
    """撰写章节。"""
    if not project:
        return "❌ 请先加载或创建一个项目。"
    if not llm_client:
        return "❌ LLM 客户端未初始化，请检查配置。"
    if not args:
        return "⚠️ 请指定章节号，例如：`/write 3`"

    try:
        chapter_number = int(args[0])
    except ValueError:
        return f"⚠️ 无效的章节号：`{args[0]}`"

    try:
        from libriscribe.agents.chapter_writer import ChapterWriterAgent

        agent = ChapterWriterAgent(llm_client)
        agent.execute(project, chapter_number)
        return f"✅ 第 {chapter_number} 章撰写完成！"
    except Exception as e:
        logger.exception("撰写章节失败")
        return f"❌ 撰写第 {chapter_number} 章时出错：{e}"


def _cmd_review(
    args: List[str],
    project: Optional[ProjectKnowledgeBase],
    llm_client: Optional[LLMClient],
) -> str:
    """审阅章节。"""
    if not project:
        return "❌ 请先加载或创建一个项目。"
    if not llm_client:
        return "❌ LLM 客户端未初始化，请检查配置。"
    if not args:
        return "⚠️ 请指定章节号，例如：`/review 3`"

    try:
        chapter_number = int(args[0])
    except ValueError:
        return f"⚠️ 无效的章节号：`{args[0]}`"

    chapter_content = _read_chapter_content(project, chapter_number)
    if not chapter_content:
        return f"⚠️ 未找到第 {chapter_number} 章的内容文件。"

    try:
        from libriscribe.agents.content_reviewer import ContentReviewerAgent

        agent = ContentReviewerAgent(llm_client)
        result = agent.execute(project, chapter_number, chapter_content)
        return f"📋 **第 {chapter_number} 章审阅结果**\n\n{result}"
    except Exception as e:
        logger.exception("审阅章节失败")
        return f"❌ 审阅第 {chapter_number} 章时出错：{e}"


def _cmd_edit(
    args: List[str],
    project: Optional[ProjectKnowledgeBase],
    llm_client: Optional[LLMClient],
) -> str:
    """编辑章节。"""
    if not project:
        return "❌ 请先加载或创建一个项目。"
    if not llm_client:
        return "❌ LLM 客户端未初始化，请检查配置。"
    if not args:
        return "⚠️ 请指定章节号，例如：`/edit 3`"

    try:
        chapter_number = int(args[0])
    except ValueError:
        return f"⚠️ 无效的章节号：`{args[0]}`"

    chapter_content = _read_chapter_content(project, chapter_number)
    if not chapter_content:
        return f"⚠️ 未找到第 {chapter_number} 章的内容文件。"

    try:
        from libriscribe.agents.editor import EditorAgent

        agent = EditorAgent(llm_client)
        result = agent.execute(project, chapter_number, chapter_content)
        return f"✏️ **第 {chapter_number} 章编辑完成**\n\n{result}"
    except Exception as e:
        logger.exception("编辑章节失败")
        return f"❌ 编辑第 {chapter_number} 章时出错：{e}"


def _cmd_outline(
    project: Optional[ProjectKnowledgeBase],
    llm_client: Optional[LLMClient],
) -> str:
    """生成大纲。"""
    if not project:
        return "❌ 请先加载或创建一个项目。"
    if not llm_client:
        return "❌ LLM 客户端未初始化，请检查配置。"

    try:
        from libriscribe.agents.outliner import OutlinerAgent

        agent = OutlinerAgent(llm_client)
        agent.execute(project)
        return "✅ 大纲生成完成！"
    except Exception as e:
        logger.exception("生成大纲失败")
        return f"❌ 生成大纲时出错：{e}"


def _cmd_concept(
    project: Optional[ProjectKnowledgeBase],
    llm_client: Optional[LLMClient],
) -> str:
    """生成概念。"""
    if not project:
        return "❌ 请先加载或创建一个项目。"
    if not llm_client:
        return "❌ LLM 客户端未初始化，请检查配置。"

    try:
        from libriscribe.agents.concept_generator import ConceptGeneratorAgent

        agent = ConceptGeneratorAgent(llm_client)
        agent.execute(project)
        return "✅ 概念生成完成！"
    except Exception as e:
        logger.exception("生成概念失败")
        return f"❌ 生成概念时出错：{e}"


def _cmd_characters(
    project: Optional[ProjectKnowledgeBase],
    llm_client: Optional[LLMClient],
) -> str:
    """生成角色。"""
    if not project:
        return "❌ 请先加载或创建一个项目。"
    if not llm_client:
        return "❌ LLM 客户端未初始化，请检查配置。"

    try:
        from libriscribe.agents.character_generator import CharacterGeneratorAgent

        agent = CharacterGeneratorAgent(llm_client)
        agent.execute(project)
        return "✅ 角色生成完成！"
    except Exception as e:
        logger.exception("生成角色失败")
        return f"❌ 生成角色时出错：{e}"


def _cmd_worldbuilding(
    project: Optional[ProjectKnowledgeBase],
    llm_client: Optional[LLMClient],
) -> str:
    """生成世界观。"""
    if not project:
        return "❌ 请先加载或创建一个项目。"
    if not llm_client:
        return "❌ LLM 客户端未初始化，请检查配置。"

    try:
        from libriscribe.agents.worldbuilding import WorldbuildingAgent

        agent = WorldbuildingAgent(llm_client)
        agent.execute(project)
        return "✅ 世界观生成完成！"
    except Exception as e:
        logger.exception("生成世界观失败")
        return f"❌ 生成世界观时出错：{e}"


def _cmd_cite(
    args: List[str],
    project: Optional[ProjectKnowledgeBase],
    llm_client: Optional[LLMClient],
) -> str:
    """提取章节引用。"""
    if not project:
        return "❌ 请先加载或创建一个项目。"
    if not llm_client:
        return "❌ LLM 客户端未初始化，请检查配置。"
    if not args:
        return "⚠️ 请指定章节号，例如：`/cite 3`"

    try:
        chapter_number = int(args[0])
    except ValueError:
        return f"⚠️ 无效的章节号：`{args[0]}`"

    chapter_content = _read_chapter_content(project, chapter_number)
    if not chapter_content:
        return f"⚠️ 未找到第 {chapter_number} 章的内容文件。"

    try:
        from libriscribe.agents.citation_agent import CitationAgent

        agent = CitationAgent(llm_client)
        citations = agent.execute(project, chapter_number, chapter_content)

        if not citations:
            return f"📄 第 {chapter_number} 章未发现需要引用的内容。"

        lines = [f"📚 **第 {chapter_number} 章引用提取结果**（共 {len(citations)} 条）\n"]
        for i, c in enumerate(citations, 1):
            lines.append(f"{i}. **{c.sentence}**")
            if c.source:
                lines.append(f"   - 来源：{c.source}")
            if c.formatted_ref:
                lines.append(f"   - 参考文献：{c.formatted_ref}")
            lines.append("")
        return "\n".join(lines)
    except Exception as e:
        logger.exception("提取引用失败")
        return f"❌ 提取第 {chapter_number} 章引用时出错：{e}"


def _cmd_export(
    args: List[str],
    project: Optional[ProjectKnowledgeBase],
) -> str:
    """导出书籍。"""
    if not project:
        return "❌ 请先加载或创建一个项目。"

    fmt = args[0].lower() if args else "docx"
    supported_formats = {"docx", "latex", "pdf"}

    if fmt not in supported_formats:
        return f"⚠️ 不支持的导出格式：`{fmt}`。支持的格式：{', '.join(supported_formats)}"

    if not project.project_dir:
        return "❌ 项目目录未设置，无法导出。"

    from pathlib import Path

    output_dir = Path(project.project_dir) / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 收集章节内容
        chapters_data = []
        for ch_num in sorted(project.chapters.keys()):
            content = _read_chapter_content(project, ch_num)
            chapter = project.get_chapter(ch_num)
            chapters_data.append(
                {
                    "chapter_number": ch_num,
                    "title": chapter.title if chapter else f"Chapter {ch_num}",
                    "content": content,
                }
            )

        if fmt == "docx":
            from libriscribe.export.docx_export import DocxExporter

            exporter = DocxExporter()
            output_path = str(output_dir / f"{project.title}.docx")
            exporter.export(
                chapters_data,
                output_path,
                title=project.title,
                genre=project.genre,
                language=project.language,
            )
            return f"✅ DOCX 导出完成：`{output_path}`"

        elif fmt == "latex":
            from libriscribe.export.latex_export import LatexExporter

            exporter = LatexExporter()
            output_path = str(output_dir / f"{project.title}.tex")
            exporter.export(chapters_data, output_path, title=project.title)
            return f"✅ LaTeX 导出完成：`{output_path}`"

        elif fmt == "pdf":
            # PDF 导出通过 fpdf 或 LaTeX 编译
            return "⚠️ PDF 导出请先使用 `/export latex` 生成 .tex 文件，然后使用 Pandoc 或 LaTeX 编译器转换。"

    except ImportError as e:
        return f"❌ 导出所需依赖未安装：{e}"
    except Exception as e:
        logger.exception("导出失败")
        return f"❌ 导出时出错：{e}"

    return "⚠️ 导出未完成。"


def _cmd_terminology(
    args: List[str],
    project: Optional[ProjectKnowledgeBase],
) -> str:
    """管理术语表。"""
    if not project:
        return "❌ 请先加载或创建一个项目。"

    if not args:
        return "⚠️ 请指定操作：`add`、`search` 或 `list`。例如：`/terminology add 量子纠缠 一种物理现象`"

    action = args[0].lower()

    if action == "add":
        if len(args) < 3:
            return "⚠️ 用法：`/terminology add [术语] [定义]`"
        term = args[1]
        definition = args[2]
        project.add_terminology(term, definition)
        return f"✅ 已添加术语：**{term}** → {definition}"

    elif action == "search":
        if len(args) < 2:
            return "⚠️ 用法：`/terminology search [关键词]`"
        keyword = args[1].lower()
        matches = {
            t: d
            for t, d in project.terminology.items()
            if keyword in t.lower() or keyword in d.lower()
        }
        if not matches:
            return f"🔍 未找到与 `{args[1]}` 相关的术语。"
        lines = [f"🔍 搜索结果（{len(matches)} 条）：\n"]
        for t, d in matches.items():
            lines.append(f"- **{t}**: {d}")
        return "\n".join(lines)

    elif action == "list":
        if not project.terminology:
            return "📖 术语表为空。使用 `/terminology add` 添加术语。"
        lines = [f"📖 **术语表**（共 {len(project.terminology)} 条）：\n"]
        for t, d in project.terminology.items():
            lines.append(f"- **{t}**: {d}")
        return "\n".join(lines)

    return f"⚠️ 未知的术语操作：`{action}`。支持：add、search、list。"


# ---------------------------------------------------------------------------
# 自然语言处理
# ---------------------------------------------------------------------------


def process_natural_language(
    message: str,
    project_data: Optional[ProjectKnowledgeBase] = None,
) -> str:
    """
    使用 LLM 理解用户自然语言意图，映射到对应操作。

    Args:
        message: 用户的自然语言输入。
        project_data: 当前项目知识库。

    Returns:
        处理结果的文本消息。
    """
    llm_client = _get_llm_client()
    project = project_data or _get_project()

    if not llm_client:
        return "❌ LLM 客户端未初始化，无法处理自然语言请求。请检查配置。"

    # 构建意图识别 prompt
    intent_prompt = f"""你是一个意图识别助手。根据用户的输入，判断其意图并返回对应的命令。

可用命令：
- /write [章节号] - 撰写章节
- /review [章节号] - 审阅章节
- /edit [章节号] - 编辑章节
- /outline - 生成大纲
- /concept - 生成概念
- /characters - 生成角色
- /worldbuilding - 生成世界观
- /cite [章节号] - 提取引用
- /export [格式] - 导出书籍（docx/latex/pdf）
- /terminology add [术语] [定义] - 添加术语
- /terminology search [关键词] - 搜索术语
- /terminology list - 列出术语
- /help - 显示帮助
- UNKNOWN - 无法识别

用户输入："{message}"

请只返回一个命令（如 /write 3），不要返回其他内容。如果无法识别，返回 UNKNOWN。"""

    try:
        response = llm_client.generate_content(
            intent_prompt, max_tokens=100, temperature=0.1
        )
        detected_command = response.strip()

        if detected_command == "UNKNOWN" or not detected_command.startswith("/"):
            # 无法映射到命令，直接用 LLM 回答
            context_parts = []
            if project:
                context_parts.append(f"项目名称：{project.title}")
                context_parts.append(f"类型：{project.genre}")
                context_parts.append(f"描述：{project.description}")
                if project.chapters:
                    context_parts.append(f"已有章节：{', '.join(str(k) for k in sorted(project.chapters.keys()))}")
                if project.terminology:
                    context_parts.append(f"术语数量：{len(project.terminology)}")

            context_str = "\n".join(context_parts) if context_parts else "（无项目上下文）"

            chat_prompt = f"""你是一个 AI 写作助手。请根据以下项目信息回答用户的问题。

项目信息：
{context_str}

用户问题：{message}

请用中文回答，提供有帮助的建议。"""

            answer = llm_client.generate_content(
                chat_prompt, max_tokens=1500, temperature=0.7
            )
            return answer if answer else "🤔 抱歉，我无法理解您的请求。请尝试更具体的描述，或输入 `/help` 查看可用命令。"

        # 检测到命令，执行它
        return process_command(detected_command, project)

    except Exception as e:
        logger.exception("自然语言处理失败")
        return f"❌ 处理请求时出错：{e}"


# ---------------------------------------------------------------------------
# Streamlit 页面渲染
# ---------------------------------------------------------------------------


def render_chat():
    """
    渲染聊天式指令界面。

    功能：
    - 显示聊天历史（st.chat_message）
    - 底部输入框（st.chat_input）
    - 斜杠命令和自然语言双模式处理
    - 处理中显示 spinner
    - 错误优雅处理
    """
    _init_session_state()

    st.title("💬 聊天指令")
    st.caption("使用斜杠命令或自然语言与好编辑交互")

    # ---- 侧边栏：快捷命令 ----
    with st.sidebar:
        st.subheader("📌 快捷命令")
        quick_commands = [
            ("/help", "显示帮助"),
            ("/outline", "生成大纲"),
            ("/concept", "生成概念"),
            ("/characters", "生成角色"),
            ("/worldbuilding", "生成世界观"),
            ("/terminology list", "查看术语表"),
        ]
        for cmd, label in quick_commands:
            if st.button(label, key=f"quick_{cmd}", use_container_width=True):
                _append_message("user", cmd)
                with st.spinner(f"正在执行 {cmd} ..."):
                    result = process_command(cmd)
                _append_message("assistant", result)
                st.rerun()

        st.divider()
        st.subheader("📝 章节操作")
        project = _get_project()
        if project and project.chapters:
            for ch_num in sorted(project.chapters.keys()):
                col1, col2, col3 = st.columns(3)
                with col1:
                    if st.button(f"写{ch_num}", key=f"sw_{ch_num}"):
                        cmd = f"/write {ch_num}"
                        _append_message("user", cmd)
                        with st.spinner(f"正在撰写第 {ch_num} 章..."):
                            result = process_command(cmd)
                        _append_message("assistant", result)
                        st.rerun()
                with col2:
                    if st.button(f"审{ch_num}", key=f"sr_{ch_num}"):
                        cmd = f"/review {ch_num}"
                        _append_message("user", cmd)
                        with st.spinner(f"正在审阅第 {ch_num} 章..."):
                            result = process_command(cmd)
                        _append_message("assistant", result)
                        st.rerun()
                with col3:
                    if st.button(f"引{ch_num}", key=f"sc_{ch_num}"):
                        cmd = f"/cite {ch_num}"
                        _append_message("user", cmd)
                        with st.spinner(f"正在提取第 {ch_num} 章引用..."):
                            result = process_command(cmd)
                        _append_message("assistant", result)
                        st.rerun()
        else:
            st.info("加载项目后可快速操作章节。")

    # ---- 显示聊天历史 ----
    for msg in st.session_state.chat_messages:
        role = msg["role"]
        with st.chat_message(role):
            st.markdown(msg["content"])

    # ---- 输入框 ----
    if prompt := st.chat_input("输入命令或自然语言描述..."):
        # 显示用户消息
        _append_message("user", prompt)
        with st.chat_message("user"):
            st.markdown(prompt)

        # 处理并显示助手回复
        with st.chat_message("assistant"):
            if prompt.strip().startswith("/"):
                # 斜杠命令
                with st.spinner("正在执行命令..."):
                    response = process_command(prompt)
            else:
                # 自然语言
                with st.spinner("正在思考..."):
                    response = process_natural_language(prompt)

            st.markdown(response)
            _append_message("assistant", response)

    # ---- 初始欢迎消息 ----
    if not st.session_state.chat_messages:
        welcome = (
            "👋 欢迎使用好编辑聊天指令界面！\n\n"
            "你可以：\n"
            "- 输入斜杠命令（如 `/write 1`）执行操作\n"
            "- 用自然语言描述需求（如「帮我写第三章」）\n"
            "- 输入 `/help` 查看所有可用命令\n\n"
            "从左侧快捷按钮开始吧！"
        )
        _append_message("assistant", welcome)
        with st.chat_message("assistant"):
            st.markdown(welcome)
