"""项目设置页面

提供项目配置、LLM 设置、RAG 设置、导出设置和术语表管理的 Streamlit 界面。
"""

import io
import csv
from pathlib import Path
from typing import Dict, List, Optional

import streamlit as st

from libriscribe.settings import Settings
from libriscribe.knowledge_base import ProjectKnowledgeBase
from libriscribe.memory.terminology import TerminologyManager


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

LLM_PROVIDERS = ["openai", "claude", "gemini", "deepseek", "mistral", "openrouter", "custom"]

PROVIDER_DISPLAY_NAMES = {
    "openai": "OpenAI",
    "claude": "Claude (Anthropic)",
    "gemini": "Google AI Studio",
    "deepseek": "DeepSeek",
    "mistral": "Mistral",
    "openrouter": "OpenRouter",
    "custom": "自定义第三方 API",
}

PROVIDER_MODELS: Dict[str, List[str]] = {
    "openai": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
    "claude": ["claude-3-5-sonnet-20241022", "claude-3-haiku-20240307", "claude-3-opus-20240229"],
    "gemini": ["gemini-1.5-pro", "gemini-1.5-flash", "gemini-1.0-pro"],
    "deepseek": ["deepseek-chat", "deepseek-coder"],
    "mistral": ["mistral-large-latest", "mistral-medium-latest", "mistral-small-latest"],
    "openrouter": ["anthropic/claude-3-haiku", "openai/gpt-4o", "meta-llama/llama-3-70b-instruct"],
    "custom": [],
}

EMBEDDING_PROVIDERS = ["openai", "local"]

OUTPUT_FORMATS = ["Markdown", "DOCX", "LaTeX", "PDF"]

REFERENCE_STYLES = ["GB/T 7714", "APA", "MLA", "Chicago", "IEEE"]

CATEGORIES = [
    "Fiction", "Non-Fiction", "Science Fiction", "Fantasy", "Mystery",
    "Romance", "Thriller", "Horror", "Historical", "Biography",
    "Self-Help", "Business", "Technology", "Academic", "Other",
]

LANGUAGES = [
    "English", "Chinese (Simplified)", "Chinese (Traditional)", "Japanese",
    "Korean", "French", "German", "Spanish", "Portuguese", "Russian", "Other",
]

BOOK_LENGTHS = [
    "Short Story (< 7,500 words)",
    "Novelette (7,500 – 17,500 words)",
    "Novella (17,500 – 40,000 words)",
    "Novel (40,000 – 80,000 words)",
    "Long Novel (80,000 – 120,000 words)",
    "Epic (120,000+ words)",
]


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _get_settings() -> Settings:
    """从 session state 获取或初始化全局设置。"""
    if "settings" not in st.session_state:
        st.session_state.settings = Settings()
    return st.session_state.settings


def _get_knowledge_base() -> Optional[ProjectKnowledgeBase]:
    """从 session state 获取当前项目知识库。"""
    return st.session_state.get("knowledge_base")


def _get_terminology_manager() -> TerminologyManager:
    """从 session state 获取或初始化术语管理器。"""
    if "terminology_manager" not in st.session_state:
        kb = _get_knowledge_base()
        project_dir = str(kb.project_dir) if kb and kb.project_dir else None
        tm = TerminologyManager(project_dir=project_dir)
        if project_dir:
            tm.load()
        # 从知识库同步术语
        if kb and kb.terminology:
            tm.merge_from_knowledge_base(kb.terminology)
        st.session_state.terminology_manager = tm
    return st.session_state.terminology_manager


def _save_settings(settings: Settings) -> None:
    """保存全局设置到 session state。"""
    st.session_state.settings = settings


def _save_knowledge_base(kb: ProjectKnowledgeBase) -> None:
    """保存知识库到 session state 并持久化到磁盘。"""
    st.session_state.knowledge_base = kb
    # 持久化到项目目录
    if kb.project_dir:
        kb_path = Path(kb.project_dir) / "knowledge_base.json"
        kb_path.parent.mkdir(parents=True, exist_ok=True)
        with open(kb_path, "w", encoding="utf-8") as f:
            f.write(kb.json(indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# 标签页渲染函数
# ---------------------------------------------------------------------------

def _render_project_settings_tab() -> None:
    """渲染项目设置标签页。"""
    kb = _get_knowledge_base()
    if kb is None:
        st.info("📭 尚未加载项目。请先在仪表盘创建或打开一个项目。")
        return

    with st.form("project_settings_form"):
        st.subheader("📖 基本信息")

        col1, col2 = st.columns(2)
        with col1:
            project_name = st.text_input("项目名称", value=kb.project_name, key="ps_project_name")
            title = st.text_input("书名", value=kb.title, key="ps_title")
            category = st.selectbox(
                "分类",
                options=CATEGORIES,
                index=CATEGORIES.index(kb.category) if kb.category in CATEGORIES else 0,
                key="ps_category",
            )
        with col2:
            genre = st.text_input("类型/体裁", value=kb.genre, key="ps_genre")
            language = st.selectbox(
                "语言",
                options=LANGUAGES,
                index=LANGUAGES.index(kb.language) if kb.language in LANGUAGES else 0,
                key="ps_language",
            )
            book_length = st.selectbox(
                "书籍长度",
                options=BOOK_LENGTHS,
                index=BOOK_LENGTHS.index(kb.book_length) if kb.book_length in BOOK_LENGTHS else 0,
                key="ps_book_length",
            )

        description = st.text_area(
            "项目描述",
            value=kb.description,
            height=100,
            key="ps_description",
        )

        st.subheader("🎨 风格指南")
        style_guide = st.text_area(
            "风格指南（用于指导 AI 写作风格）",
            value=kb.style_guide,
            height=200,
            key="ps_style_guide",
            placeholder="例如：使用简洁明快的语言，避免冗长的描写。对话要自然流畅，符合角色性格……",
        )

        submitted = st.form_submit_button("💾 保存项目设置", use_container_width=True)
        if submitted:
            kb.project_name = project_name
            kb.title = title
            kb.category = category
            kb.genre = genre
            kb.language = language
            kb.book_length = book_length
            kb.description = description
            kb.style_guide = style_guide
            _save_knowledge_base(kb)
            st.success("✅ 项目设置已保存！")


def _render_llm_settings_tab() -> None:
    """渲染 LLM 设置标签页。"""
    settings = _get_settings()
    kb = _get_knowledge_base()

    with st.form("llm_settings_form"):
        st.subheader("🤖 LLM 提供商")

        # 当前使用的提供商
        current_provider = kb.llm_provider if kb else settings.default_llm
        provider = st.selectbox(
            "LLM 提供商",
            options=LLM_PROVIDERS,
            index=LLM_PROVIDERS.index(current_provider) if current_provider in LLM_PROVIDERS else 0,
            format_func=lambda p: PROVIDER_DISPLAY_NAMES.get(p, p),
            key="llm_provider",
        )

        # ── 自定义第三方 API 配置 ──
        custom_api_base = ""
        custom_api_key = ""
        custom_model_name = ""

        if provider == "custom":
            st.info("🔗 自定义第三方 API：填写兼容 OpenAI Chat Completions 格式的 API 地址、密钥和模型名称。")
            # 从知识库读取已保存的自定义配置
            saved_base = getattr(kb, 'custom_api_base', '') if kb else ''
            saved_key = getattr(kb, 'custom_api_key', '') if kb else ''
            saved_model = getattr(kb, 'custom_model', '') if kb else ''

            custom_api_base = st.text_input(
                "API Base URL",
                value=saved_base,
                key="llm_custom_api_base",
                placeholder="例如: https://api.example.com/v1",
                help="第三方 API 的基础地址，需兼容 OpenAI Chat Completions 接口格式",
            )
            custom_api_key = st.text_input(
                "API Key",
                value=saved_key,
                type="password",
                key="llm_custom_api_key",
                placeholder="输入第三方 API 密钥",
            )
            custom_model_name = st.text_input(
                "模型名称",
                value=saved_model,
                key="llm_custom_model",
                placeholder="例如: gpt-4o-mini, deepseek-chat 等",
            )
            model = custom_model_name
        else:
            # API Key 输入（非自定义提供商）
            api_key_map = {
                "openai": ("OpenAI API Key", settings.openai_api_key),
                "claude": ("Claude API Key", settings.claude_api_key),
                "gemini": ("Google AI Studio API Key", settings.google_ai_studio_api_key),
                "deepseek": ("DeepSeek API Key", settings.deepseek_api_key),
                "mistral": ("Mistral API Key", settings.mistral_api_key),
                "openrouter": ("OpenRouter API Key", settings.openrouter_api_key),
            }
            key_label, key_value = api_key_map.get(provider, ("API Key", ""))
            api_key = st.text_input(key_label, value=key_value, type="password", key="llm_api_key")

            # 模型选择
            models = PROVIDER_MODELS.get(provider, [])
            if provider == "openrouter":
                custom_model = st.text_input(
                    "自定义模型名称（OpenRouter）",
                    value=settings.openrouter_model,
                    key="llm_openrouter_model",
                )
                model = custom_model
            else:
                model = st.selectbox("模型", options=models, key="llm_model")

        st.divider()
        st.subheader("⚙️ 生成参数")

        col1, col2 = st.columns(2)
        with col1:
            temperature = st.slider(
                "Temperature（创造性）",
                min_value=0.0,
                max_value=2.0,
                value=0.7,
                step=0.05,
                key="llm_temperature",
                help="值越高越有创造性，值越低越稳定",
            )
        with col2:
            max_tokens = st.number_input(
                "最大 Token 数",
                min_value=256,
                max_value=128000,
                value=4096,
                step=256,
                key="llm_max_tokens",
            )

        st.divider()
        st.subheader("💰 成本优化")

        cost_optimization = st.toggle(
            "启用成本优化模式",
            value=settings.cost_optimization,
            key="llm_cost_optimization",
            help="初稿使用低成本模型，润色使用高质量模型",
        )

        col1, col2 = st.columns(2)
        with col1:
            draft_model = st.text_input(
                "初稿模型",
                value=settings.draft_model,
                key="llm_draft_model",
                disabled=not cost_optimization,
            )
        with col2:
            polish_model = st.text_input(
                "润色模型",
                value=settings.polish_model,
                key="llm_polish_model",
                disabled=not cost_optimization,
            )

        submitted = st.form_submit_button("💾 保存 LLM 设置", use_container_width=True)
        if submitted:
            # 更新全局设置
            settings.default_llm = provider
            settings.cost_optimization = cost_optimization
            settings.draft_model = draft_model
            settings.polish_model = polish_model

            # 更新 API Key（仅非自定义提供商）
            if provider != "custom" and api_key:
                api_key_setters = {
                    "openai": lambda v: setattr(settings, "openai_api_key", v),
                    "claude": lambda v: setattr(settings, "claude_api_key", v),
                    "gemini": lambda v: setattr(settings, "google_ai_studio_api_key", v),
                    "deepseek": lambda v: setattr(settings, "deepseek_api_key", v),
                    "mistral": lambda v: setattr(settings, "mistral_api_key", v),
                    "openrouter": lambda v: setattr(settings, "openrouter_api_key", v),
                }
                setter = api_key_setters.get(provider)
                if setter:
                    setter(api_key)

            if provider == "openrouter":
                settings.openrouter_model = model

            _save_settings(settings)

            # 更新知识库中的提供商和自定义配置
            if kb:
                kb.llm_provider = provider
                if provider == "custom":
                    kb.custom_api_base = custom_api_base
                    kb.custom_api_key = custom_api_key
                    kb.custom_model = custom_model_name
                _save_knowledge_base(kb)

            st.success("✅ LLM 设置已保存！")


def _render_rag_settings_tab() -> None:
    """渲染 RAG 设置标签页。"""
    settings = _get_settings()
    kb = _get_knowledge_base()

    with st.form("rag_settings_form"):
        st.subheader("📐 嵌入模型配置")

        col1, col2 = st.columns(2)
        with col1:
            embedding_provider = st.selectbox(
                "嵌入提供商",
                options=EMBEDDING_PROVIDERS,
                index=EMBEDDING_PROVIDERS.index(settings.embedding_provider)
                if settings.embedding_provider in EMBEDDING_PROVIDERS
                else 0,
                key="rag_embedding_provider",
            )
        with col2:
            embedding_model = st.text_input(
                "嵌入模型名称",
                value=settings.embedding_model,
                key="rag_embedding_model",
            )

        st.divider()
        st.subheader("🗄️ ChromaDB 配置")

        chroma_persist_dir = st.text_input(
            "ChromaDB 持久化目录",
            value=settings.chroma_persist_dir,
            key="rag_chroma_dir",
        )

        top_k = st.slider(
            "检索 Top-K 结果数",
            min_value=1,
            max_value=20,
            value=settings.rag_top_k,
            key="rag_top_k",
            help="每次检索返回的最相关文档片段数量",
        )

        st.divider()
        st.subheader("📄 文本分块参数")

        col1, col2 = st.columns(2)
        with col1:
            chunk_size = st.number_input(
                "分块大小（字符数）",
                min_value=100,
                max_value=10000,
                value=settings.rag_chunk_size,
                step=100,
                key="rag_chunk_size",
            )
        with col2:
            chunk_overlap = st.number_input(
                "分块重叠（字符数）",
                min_value=0,
                max_value=2000,
                value=settings.rag_chunk_overlap,
                step=50,
                key="rag_chunk_overlap",
            )

        submitted = st.form_submit_button("💾 保存 RAG 设置", use_container_width=True)
        if submitted:
            settings.embedding_provider = embedding_provider
            settings.embedding_model = embedding_model
            settings.chroma_persist_dir = chroma_persist_dir
            settings.rag_top_k = top_k
            settings.rag_chunk_size = chunk_size
            settings.rag_chunk_overlap = chunk_overlap
            _save_settings(settings)
            st.success("✅ RAG 设置已保存！")

    # 文档管理区域（不在 form 内，因为 file_uploader 不兼容 form）
    st.divider()
    st.subheader("📚 文档管理")

    uploaded_files = st.file_uploader(
        "上传参考文档",
        type=["pdf", "docx", "txt"],
        accept_multiple_files=True,
        key="rag_file_uploader",
        help="支持 PDF、DOCX、TXT 格式",
    )

    if uploaded_files:
        if st.button("📥 导入上传的文档", key="rag_import_btn"):
            kb = _get_knowledge_base()
            if kb is None:
                st.warning("请先加载一个项目。")
            else:
                project_dir = Path(kb.project_dir) if kb.project_dir else Path(".")
                docs_dir = project_dir / "rag_documents"
                docs_dir.mkdir(parents=True, exist_ok=True)

                imported_count = 0
                for uploaded_file in uploaded_files:
                    save_path = docs_dir / uploaded_file.name
                    with open(save_path, "wb") as f:
                        f.write(uploaded_file.getbuffer())
                    if str(save_path) not in kb.rag_documents:
                        kb.rag_documents.append(str(save_path))
                    imported_count += 1

                _save_knowledge_base(kb)
                st.success(f"✅ 成功导入 {imported_count} 个文档！")
                st.rerun()

    # 已索引文档列表
    if kb and kb.rag_documents:
        st.markdown("**已索引文档：**")
        for i, doc_path in enumerate(kb.rag_documents):
            doc_name = Path(doc_path).name
            col1, col2 = st.columns([4, 1])
            with col1:
                st.text(f"📄 {doc_name}")
            with col2:
                if st.button("🗑️ 删除", key=f"rag_del_doc_{i}"):
                    kb.rag_documents.remove(doc_path)
                    _save_knowledge_base(kb)
                    st.success(f"已删除文档：{doc_name}")
                    st.rerun()
    else:
        st.info("📭 暂无已索引的文档。")


def _render_export_settings_tab() -> None:
    """渲染导出设置标签页。"""
    settings = _get_settings()
    kb = _get_knowledge_base()

    with st.form("export_settings_form"):
        st.subheader("📦 导出格式")

        output_format = st.selectbox(
            "默认输出格式",
            options=OUTPUT_FORMATS,
            index=0,
            key="export_format",
        )

        st.divider()
        st.subheader("🔧 导出工具配置")

        pandoc_path = st.text_input(
            "Pandoc 可执行文件路径",
            value=settings.pandoc_path,
            key="export_pandoc_path",
            help="用于 DOCX/LaTeX 导出，需提前安装 Pandoc",
        )

        st.divider()
        st.subheader("📖 参考文献格式")

        reference_style = st.selectbox(
            "引用格式",
            options=REFERENCE_STYLES,
            index=0,
            key="export_ref_style",
            help="选择参考文献的格式化标准",
        )

        submitted = st.form_submit_button("💾 保存导出设置", use_container_width=True)
        if submitted:
            settings.pandoc_path = pandoc_path
            _save_settings(settings)
            # 将导出格式和引用风格存入 session state
            st.session_state["export_format"] = output_format
            st.session_state["reference_style"] = reference_style
            st.success("✅ 导出设置已保存！")

    # 导出预览区域
    st.divider()
    st.subheader("📤 导出预览")

    if kb is None:
        st.info("📭 尚未加载项目，无法预览导出。")
        return

    if st.button("🔍 生成导出预览", key="export_preview_btn"):
        with st.spinner("正在生成预览..."):
            preview_text = _generate_export_preview(kb)
            st.text_area(
                "导出预览",
                value=preview_text,
                height=400,
                key="export_preview_text",
            )

    if st.button("📥 执行导出", key="export_execute_btn", type="primary"):
        st.info("导出功能将在后续版本中完善。当前可使用 CLI 命令导出。")


def _generate_export_preview(kb: ProjectKnowledgeBase) -> str:
    """生成导出预览文本。"""
    lines = [
        f"# {kb.title}",
        f"",
        f"**作者项目**: {kb.project_name}",
        f"**分类**: {kb.category} | **类型**: {kb.genre}",
        f"**语言**: {kb.language}",
        f"",
        f"## 简介",
        f"",
        kb.description,
        f"",
        f"## 目录",
        f"",
    ]

    if kb.chapters:
        for ch_num in sorted(kb.chapters.keys()):
            ch = kb.chapters[ch_num]
            ch_title = ch.title if ch.title else f"第 {ch_num} 章"
            lines.append(f"- {ch_title}")
    else:
        lines.append("（暂无章节）")

    lines.extend([
        "",
        "---",
        f"风格指南: {kb.style_guide[:200] + '...' if len(kb.style_guide) > 200 else kb.style_guide}",
        "",
        f"参考文献: {len(kb.citations)} 条引用",
        f"术语表: {len(kb.terminology)} 个术语",
    ])

    return "\n".join(lines)


def _render_terminology_tab() -> None:
    """渲染术语表管理标签页。"""
    tm = _get_terminology_manager()
    kb = _get_knowledge_base()

    # 搜索区域
    st.subheader("🔍 搜索术语")
    search_keyword = st.text_input(
        "搜索关键词",
        key="term_search",
        placeholder="输入术语名称或定义中的关键词…",
    )

    # 添加新术语
    st.divider()
    st.subheader("➕ 添加新术语")

    with st.form("add_term_form", clear_on_submit=True):
        col1, col2 = st.columns([1, 2])
        with col1:
            new_term = st.text_input("术语名称", key="term_new_name")
        with col2:
            new_definition = st.text_input("定义/统一写法", key="term_new_def")

        add_submitted = st.form_submit_button("➕ 添加术语", use_container_width=True)
        if add_submitted:
            if new_term.strip() and new_definition.strip():
                tm.add(new_term.strip(), new_definition.strip())
                # 同步到知识库
                if kb:
                    kb.terminology = tm.get_all()
                    _save_knowledge_base(kb)
                st.success(f"✅ 已添加术语：{new_term.strip()}")
                st.rerun()
            else:
                st.warning("⚠️ 术语名称和定义不能为空。")

    # 导入/导出区域
    st.divider()
    st.subheader("📥📤 导入/导出术语")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**导入 CSV**")
        csv_file = st.file_uploader(
            "上传 CSV 文件（列：term, definition）",
            type=["csv"],
            key="term_csv_upload",
        )
        if csv_file and st.button("📥 导入", key="term_import_btn"):
            try:
                content = csv_file.getvalue().decode("utf-8-sig")
                reader = csv.DictReader(io.StringIO(content))
                imported = {}
                for row in reader:
                    term = row.get("term", "").strip()
                    defn = row.get("definition", "").strip()
                    if term and defn:
                        imported[term] = defn
                if imported:
                    tm.add_batch(imported)
                    if kb:
                        kb.terminology = tm.get_all()
                        _save_knowledge_base(kb)
                    st.success(f"✅ 成功导入 {len(imported)} 个术语！")
                    st.rerun()
                else:
                    st.warning("⚠️ CSV 文件中未找到有效术语。")
            except Exception as e:
                st.error(f"❌ 导入失败：{e}")

    with col2:
        st.markdown("**导出 CSV**")
        if tm.count > 0:
            csv_buffer = io.StringIO()
            writer = csv.DictWriter(csv_buffer, fieldnames=["term", "definition"])
            writer.writeheader()
            for term, defn in sorted(tm.get_all().items()):
                writer.writerow({"term": term, "definition": defn})

            st.download_button(
                "📤 导出术语表",
                data=csv_buffer.getvalue(),
                file_name="terminology.csv",
                mime="text/csv",
                key="term_export_btn",
            )
        else:
            st.info("暂无术语可导出。")

    # 术语表展示
    st.divider()
    st.subheader(f"📋 术语表（共 {tm.count} 个术语）")

    # 根据搜索关键词过滤
    if search_keyword:
        display_terms = tm.search(search_keyword)
        st.caption(f"搜索 \"{search_keyword}\" 找到 {len(display_terms)} 个结果")
    else:
        display_terms = list(tm.get_all().items())

    if display_terms:
        # 分页显示
        page_size = 20
        total_pages = max(1, (len(display_terms) + page_size - 1) // page_size)
        page_num = st.number_input(
            "页码",
            min_value=1,
            max_value=total_pages,
            value=1,
            key="term_page",
        )
        start_idx = (page_num - 1) * page_size
        end_idx = start_idx + page_size
        page_terms = display_terms[start_idx:end_idx]

        for i, (term, defn) in enumerate(page_terms):
            col1, col2, col3 = st.columns([2, 4, 1])
            with col1:
                st.markdown(f"**{term}**")
            with col2:
                st.text(defn)
            with col3:
                if st.button("🗑️", key=f"term_del_{start_idx + i}"):
                    tm.remove(term)
                    if kb:
                        kb.terminology = tm.get_all()
                        _save_knowledge_base(kb)
                    st.success(f"已删除术语：{term}")
                    st.rerun()

        st.caption(f"第 {page_num}/{total_pages} 页")
    else:
        if search_keyword:
            st.info(f"未找到匹配 \"{search_keyword}\" 的术语。")
        else:
            st.info("📭 术语表为空，请添加术语或导入 CSV 文件。")


# ---------------------------------------------------------------------------
# 主渲染函数
# ---------------------------------------------------------------------------

def render_settings() -> None:
    """渲染项目设置页面。

    包含五个标签页：项目设置、LLM 设置、RAG 设置、导出设置、术语表。
    """
    st.title("⚙️ 项目设置")
    st.markdown("管理项目配置、模型参数、RAG 检索、导出选项和术语表。")

    tab_project, tab_llm, tab_rag, tab_export, tab_terminology = st.tabs([
        "📖 项目设置",
        "🤖 LLM 设置",
        "📐 RAG 设置",
        "📤 导出设置",
        "📝 术语表",
    ])

    with tab_project:
        _render_project_settings_tab()

    with tab_llm:
        _render_llm_settings_tab()

    with tab_rag:
        _render_rag_settings_tab()

    with tab_export:
        _render_export_settings_tab()

    with tab_terminology:
        _render_terminology_tab()
