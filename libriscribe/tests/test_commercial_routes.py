"""Commercial route registry tests."""

from __future__ import annotations

import types
import inspect
import re
import io
import json
import zipfile
from pathlib import Path
from datetime import datetime

from libriscribe.web import app
from libriscribe.rag.embeddings import EmbeddingProvider
from libriscribe.agents.chapter_writer import ChapterWriterAgent
from libriscribe.export.docx_export import DocxExporter
from libriscribe.rag.retriever import Retriever
from libriscribe.rag.vector_store import VectorStore
from libriscribe.export.latex_export import LatexExporter
from libriscribe.export.pdf_export import PdfExporter
from libriscribe.export.pptx_export import PptxExporter
from libriscribe.knowledge_base import Chapter, ChapterSection, Citation, EvidenceChunk, ProjectKnowledgeBase, SourceDocument
from libriscribe.services.global_settings_service import GlobalSettingsService
from libriscribe.services.prompt_service import PromptService, PROMPT_ANALYSIS_GUIDE


EXPECTED_NAV_PAGES = [
    "Projects",
    "Sources",
    "Outline",
    "Editor",
    "Prompts",
    "Quality",
    "Exports",
    "AIConfig",
]

EXPECTED_INTERNAL_PAGES = [
    "Workspace",
    "Pipeline",
    "Citations",
    "Tools",
    "Settings",
    "Audit",
    "GlobalSettings",
]

EXPECTED_PLAYBOOK_IDS = {
    "academic_monograph",
    "textbook",
    "industry_whitepaper",
    "policy_research",
}


def test_nav_pages_include_commercial_routes() -> None:
    """NAV_PAGES exposes the simplified practical writing workflow."""
    assert app.NAV_PAGES == EXPECTED_NAV_PAGES


def test_every_nav_page_has_callable_renderer() -> None:
    """Each visible navigation page must have a callable renderer."""
    for page in app.NAV_PAGES:
        assert page in app.PAGE_RENDERERS
        assert callable(app.PAGE_RENDERERS[page])



def test_exports_page_shows_delivery_quality_gate() -> None:
    """导出页必须在生成文件按钮前展示正文质量和导出就绪风险。"""
    source = inspect.getsource(app.render_exports_page)

    assert "导出前交付门禁" in source
    assert "export_readiness_report" in source
    assert "manuscript_quality_report" in source
    assert "导出就绪风险" in source
    assert "正文质量风险" in source
    assert source.index("导出前交付门禁") < source.rindex("生成交付文件")


def test_internal_pages_remain_available_but_hidden_from_main_navigation() -> None:
    """Advanced commercial pages remain routable but do not clutter the sidebar."""
    for page in EXPECTED_INTERNAL_PAGES:
        assert page not in app.NAV_PAGES
        assert page in app.PAGE_RENDERERS
        assert callable(app.PAGE_RENDERERS[page])


def test_legacy_page_aliases_map_to_new_routes() -> None:
    """Legacy page names remain compatible with the new commercial routes."""
    assert app.LEGACY_PAGE_ALIASES["Dashboard"] == "Workspace"
    assert app.LEGACY_PAGE_ALIASES["Chat"] == "Tools"


def test_prompt_service_builtin_playbooks_include_commercial_templates() -> None:
    """Built-in playbooks include the required commercial writing workflows."""
    playbook_ids = {playbook.get("id") for playbook in PromptService.builtin_playbooks()}
    assert EXPECTED_PLAYBOOK_IDS <= playbook_ids


def test_prompt_service_load_save_reset_editable_global_chapter_prompt(monkeypatch, tmp_path) -> None:
    """Chapter writing prompt can be viewed, edited, and reset globally."""
    service = GlobalSettingsService(tmp_path / "global_settings.json")
    monkeypatch.setattr("libriscribe.services.global_settings_service.GlobalSettingsService", lambda: service)

    default_prompt = PromptService.load_chapter_prompt()
    assert "{book_title}" in default_prompt
    assert "{outline_tree}" in default_prompt

    custom_prompt = "全局自定义提示词：{book_title} / {section_title} / {rag_context}"
    saved_path = PromptService.save_chapter_prompt(None, custom_prompt)
    assert saved_path.name == "global_settings.json"
    assert PromptService.load_chapter_prompt() == custom_prompt

    PromptService.reset_chapter_prompt()
    assert PromptService.load_chapter_prompt() == default_prompt


def test_prompt_service_lists_previous_builtin_global_prompts() -> None:
    """All previous YAML prompt templates are visible as global prompts."""
    prompts = PromptService.list_all_global_prompts()
    keys = {prompt["key"] for prompt in prompts}
    assert "chapter_writer" in keys
    assert "editor" in keys
    chapter_prompt = next(prompt for prompt in prompts if prompt["key"] == "chapter_writer")
    assert chapter_prompt["is_active"] is True
    assert chapter_prompt["category"] == "当前生效"
    assert "学术专著" in chapter_prompt["default_template"] or "职称著作型" in chapter_prompt["current_template"]


    outliner_prompt = next(prompt for prompt in prompts if prompt["key"] == "outliner")
    assert "范文" in outliner_prompt["example"]
    assert "写作思路" in outliner_prompt["example"]
    assert "中文专著大纲生成提示词" in outliner_prompt["default_template"]


def test_outline_generation_helpers_use_chinese_monograph_format() -> None:
    """Outline helpers use the requested chapter-section-item-writing-idea format."""
    assert hasattr(app, "_generate_single_chapter_outline_with_ai")
    assert hasattr(app.PromptService, "load_outline_prompt")
    outline_prompt = app.PromptService.load_outline_prompt()
    assert "整体框架思考" in outline_prompt
    assert "写作思路" in outline_prompt
    assert "第一节" in outline_prompt


def test_parse_outline_supports_chinese_section_hierarchy() -> None:
    """章节管理应能解析“第一章/第一节/一、/（一）/写作思路”的专著大纲。"""
    project = app.ProjectKnowledgeBase(project_name="cn_outline", title="智慧工地建设与工程现场数字化管理")
    outline = """第一章 智慧工地建设总论（总字数 10000字）
第一节 工程现场数字化转型的时代背景（约3000字）
一、行业发展与政策驱动
（一）智慧工地的概念边界
写作思路：先界定智慧工地，再说明数字化管理价值。
第二节 工程现场管理的核心矛盾
一、组织协同与数据孤岛
第二章 技术体系与平台架构（总字数 12000字）
第一节 AIoT 与 BIM 融合
一、感知层与数据层
（一）设备接入与数据治理"""

    created = app._parse_outline_text(project, outline, persist=False, rerun=False, show_messages=False)

    assert created == 2
    assert project.chapters[1].title == "智慧工地建设总论"
    assert len(project.chapters[1].sections) == 5
    assert project.chapters[1].sections[0].section_number == "1.1"
    assert project.chapters[1].sections[1].section_number == "1.1.1"
    assert project.chapters[1].sections[2].section_number == "1.1.1.1"
    assert project.chapters[1].sections[2].summary.startswith("写作思路")
    assert project.chapters[2].sections[-1].section_number == "2.1.1.1"


def test_parse_outline_distributes_parent_words_to_leaf_children() -> None:
    """父级节有字数、叶子小节未标字数时，应把父级字数平均分配给所有叶子小节。"""
    project = app.ProjectKnowledgeBase(project_name="leaf_words", title="阅读行为研究")
    outline = """第一章 高职学生阅读行为研究（总字数 10000字）
第一节 高职学生的阅读行为画像（约5150字）
一、阅读时间与场景
（一）课内阅读行为
（二）课外阅读行为
二、阅读媒介与内容偏好
（一）纸质媒介偏好
（二）数字媒介偏好"""

    created = app._parse_outline_text(project, outline, persist=False, rerun=False, show_messages=False)

    assert created == 1
    level2_sections = [sec for sec in project.chapters[1].sections if sec.section_number.count(".") == 2]
    leaf_sections = [sec for sec in project.chapters[1].sections if sec.section_number.count(".") == 3]
    assert [sec.word_count for sec in level2_sections] == [2575, 2575]
    assert [sec.word_count for sec in leaf_sections] == [1288, 1287, 1288, 1287]
    assert sum(sec.word_count for sec in level2_sections) == 5150
    assert sum(sec.word_count for sec in leaf_sections) == 5150


def test_editor_outline_section_label_uses_chinese_hierarchy() -> None:
    """写章节页应把内部数字编号展示为与大纲一致的中文层级。"""
    assert app._format_outline_section_label("1.1", "智慧工地建设的时代背景与行业动因") == "第一节 智慧工地建设的时代背景与行业动因"
    assert app._format_outline_section_label("1.1.1", "建筑业数字化转型的宏观背景") == "一、 建筑业数字化转型的宏观背景"
    assert app._format_outline_section_label("1.1.1.1", "国家数字化战略与建筑业转型政策牵引") == "（一） 国家数字化战略与建筑业转型政策牵引"
    assert app._format_outline_section_label("2.12", "第十二节标题").startswith("第十二节")


def test_outline_and_generation_surfaces_do_not_leak_numeric_section_labels() -> None:
    """大纲页、后台返回和实时合并不应把 1.1/1.1.1 泄露到用户可见标题。"""
    outline_source = inspect.getsource(app.render_outline_page)
    bg_source = inspect.getsource(app._bg_write_chapter)
    live_source = inspect.getsource(app._run_live_chapter_generation)

    assert 'st.caption(f"{indent}{sec.section_number} {sec.title}{wc_str}")' not in outline_source
    assert "_format_outline_section_label(sec.section_number, sec.title)" in outline_source
    assert 'return f"第 {chapter_num} 章 {section_number} 小节已生成完成"' not in bg_source
    assert "section_display or _format_outline_section_label(section_number)" in bg_source
    assert "_merge_section_content_into_chapter(chapter_path, section_content, section_number, section_display)" not in live_source
    assert "_merge_section_content_into_chapter(chapter_path, section_content, section_number, section_title)" in live_source


def test_chapter_writer_generation_uses_chinese_outline_labels(monkeypatch) -> None:
    """生成进度、生成 Markdown 标题和提示词大纲树必须使用中文层级。"""
    project = ProjectKnowledgeBase(project_name="generation_labels", title="智慧工地建设与工程现场数字化管理")
    chapter = Chapter(
        chapter_number=1,
        title="智慧工地建设的背景、内涵与价值定位",
        word_count=1200,
        sections=[
            ChapterSection(section_number="1.1", title="智慧工地建设的时代背景与行业动因", level=1),
            ChapterSection(section_number="1.1.1", title="建筑业数字化转型的宏观背景", level=2),
            ChapterSection(section_number="1.1.1.1", title="国家数字化战略与建筑业转型政策牵引", level=3, word_count=800),
        ],
    )
    project.chapters[1] = chapter
    writer = ChapterWriterAgent(llm_client=object())
    prompts_seen = []
    progress_seen = []

    monkeypatch.setattr(writer, "_get_rag_context", lambda query, **kwargs: "")
    monkeypatch.setattr(writer, "_generate_section_with_retries", lambda **kwargs: prompts_seen.append(kwargs["prompt"]) or "　　这里是符合出版要求的正文内容，用于验证标题链路。")
    monkeypatch.setattr("libriscribe.agents.chapter_writer.finalize_academic_chapter", lambda text, target_words=0: (text, 50, "ok"))

    content = writer._write_academic_chapter(
        project,
        1,
        chapter,
        progress_callback=lambda current, total, title, status: progress_seen.append(title),
    )

    assert "## 第一节 智慧工地建设的时代背景与行业动因" in content
    assert "### 一、 建筑业数字化转型的宏观背景" in content
    assert "#### （一） 国家数字化战略与建筑业转型政策牵引" in content
    assert "1.1.1.1 国家数字化战略与建筑业转型政策牵引" not in content
    assert "（一） 国家数字化战略与建筑业转型政策牵引" in progress_seen
    assert prompts_seen and "- 第一节 智慧工地建设的时代背景与行业动因" in prompts_seen[0]
    assert "-   1.1.1" not in prompts_seen[0]


def test_chapter_writer_does_not_emit_outline_plan_as_chapter_intro(monkeypatch) -> None:
    """章摘要/写作思路只能进入提示词上下文，不能以“本章导语”等形式拼进正文预览。"""
    project = ProjectKnowledgeBase(project_name="no_intro_leak", title="智慧工地建设与工程现场数字化管理")
    chapter = Chapter(
        chapter_number=6,
        title="进度、质量、安全与绿色施工一体化管控",
        summary="第六章 进度、质量、安全与绿色施工一体化管控（总字数 10000字）\n写作思路：说明计划分解与动态纠偏。\n资料依据可包括施工组织设计。",
        word_count=800,
        sections=[ChapterSection(section_number="6.1", title="施工进度数字化计划", level=1, summary="写作思路：内部计划", word_count=200)],
    )
    project.chapters[6] = chapter
    writer = ChapterWriterAgent(llm_client=object())
    prompts_seen = []

    monkeypatch.setattr(writer, "_get_rag_context", lambda query, **kwargs: "")
    monkeypatch.setattr(writer, "_generate_section_with_retries", lambda **kwargs: prompts_seen.append(kwargs["prompt"]) or "　　施工进度数字化计划需要围绕总控计划、现场任务和反馈机制形成闭环。")
    monkeypatch.setattr("libriscribe.agents.chapter_writer.finalize_academic_chapter", lambda text, target_words=0: (text, 50, "ok"))

    content = writer._write_academic_chapter(project, 6, chapter)

    assert "本章导语" not in content
    assert "写作思路：" not in content
    assert "资料依据" not in content
    assert "施工进度数字化计划需要" in content
    assert prompts_seen and "写作思路" in prompts_seen[0]


def test_chapter_writer_section_prompt_enforces_evidence_binding(monkeypatch) -> None:
    """章节生成提示词必须把 RAG 来源、信息缺口和正文输出边界规则前置。"""
    project = ProjectKnowledgeBase(project_name="evidence_prompt", title="智慧工地建设与工程现场数字化管理")
    chapter = Chapter(chapter_number=1, title="证据绑定测试", summary="围绕智慧工地政策与应用证据展开。")
    section = ChapterSection(section_number="1.1.1.1", title="政策牵引", level=3, summary="说明政策依据。", word_count=800)
    writer = ChapterWriterAgent(llm_client=object())

    monkeypatch.setattr(PromptService, "load_chapter_prompt", lambda: "参考资料：\n{rag_context}\n\n请写：{section_title}")

    prompt = writer._build_academic_section_prompt(
        project=project,
        chapter=chapter,
        chapter_number=1,
        section=section,
        section_title="（一） 政策牵引",
        target_words=800,
        outline_tree="- （一） 政策牵引",
        terminology="智慧工地：工程现场数字化管理体系",
        previous_summaries="暂无",
        rag_context="[来源: 政策资料汇编 (p.12)]\n2024 年相关政策强调建筑业数字化转型。",
        generated_summaries="暂无",
    )

    assert "证据绑定规则（专著强制）" in prompt
    assert "关键事实句必须优先依托" in prompt
    assert "[来源: ...]" in prompt
    assert "资料来源：" in prompt
    assert "【信息缺失】" in prompt
    assert "[来源: 政策资料汇编 (p.12)]" in prompt
    assert "正文输出边界（强制）" in prompt
    assert "严禁原样输出到正文" in prompt
    assert "不输出“本章导语：”“写作思路：”“资料依据：”“证据边界：”“后续需补充：”" in prompt
    assert "去 AI 痕迹与出版级表达" in prompt
    assert "真实研究者或专业作者的自然表达" in prompt
    assert "禁止 AI 学术膨胀词" in prompt
    assert "不得使用任何形式的“不仅……而且……”" in prompt
    assert "定义必须带立场" in prompt


def test_chapter_writer_compact_retry_prompt_keeps_evidence_binding_rules() -> None:
    """精简重试提示也不能丢掉证据绑定约束，否则失败重试会退化为泛化编造。"""
    writer = ChapterWriterAgent(llm_client=object())

    prompt = writer._build_compact_retry_prompt(
        "可用参考资料：\n[来源: 行业报告 (p.3)]\n报告说明工程现场数字化管理范围。",
        "（一） 政策牵引",
        800,
    )

    assert "关键事实句必须优先依托" in prompt
    assert "[来源: ...]" in prompt
    assert "资料来源：" in prompt
    assert "【信息缺失】" in prompt
    assert "不得编造" in prompt



def test_chapter_writer_quality_rewrite_prompt_forbids_unsupported_facts() -> None:
    """质量门禁重写提示必须要求无资料依据的确定性事实改写或标记缺口。"""
    writer = ChapterWriterAgent(llm_client=object())

    prompt = writer._build_quality_rewrite_prompt(
        prompt="原始提示含 [来源: 资料库A (p.5)]。",
        section_title="（一） 政策牵引",
        content="已有研究表明智慧工地在2024年增长达到35%[3]。",
        target_words=800,
        issue_summary="疑似无来源事实句",
    )

    assert "关键事实句必须依托" in prompt
    assert "[来源: ...]" in prompt
    assert "项目 citation" in prompt
    assert "没有资料依据时不得写成确定性事实" in prompt
    assert "【信息缺失】" in prompt
    assert "资料来源：" in prompt



def test_chapter_writer_quality_gate_rewrites_risky_section(monkeypatch) -> None:
    """小节生成后发现伪引用/无来源事实句/语体风险时，应在写入前定向重写一次。"""

    class RewriteLLM:
        llm_provider = "custom"

        def __init__(self) -> None:
            self.calls = []

        def generate_content(self, prompt: str, max_tokens: int = 2000, temperature: float = 0.7) -> str:
            self.calls.append(prompt)
            return "　　本节围绕智慧工地建设的概念边界、运行机制、实施路径和风险治理展开分析，强调工程现场数字化管理需要在组织体系、数据治理、技术集成和价值评估之间形成稳定协同。"

    project = ProjectKnowledgeBase(project_name="quality_gate", title="智慧工地建设与工程现场数字化管理")
    chapter = Chapter(
        chapter_number=1,
        title="质量门禁测试",
        word_count=20,
        sections=[ChapterSection(section_number="1.1", title="风险小节", level=1, word_count=20)],
    )
    project.chapters[1] = chapter
    llm = RewriteLLM()
    writer = ChapterWriterAgent(llm_client=llm)

    monkeypatch.setattr(writer, "_get_rag_context", lambda query, **kwargs: "")
    monkeypatch.setattr(writer, "_generate_section_with_retries", lambda **kwargs: "　　已有研究表明智慧工地建设在2024年增长达到35%[3]。我们认为这是革命性的变化。")
    monkeypatch.setattr(writer, "_compress_to_target_words", lambda **kwargs: kwargs["content"])
    monkeypatch.setattr("libriscribe.agents.chapter_writer.finalize_academic_chapter", lambda text, target_words=0: (text, 50, "ok"))

    content = writer._write_academic_chapter(project, 1, chapter)

    assert len(llm.calls) == 1
    assert "质量门禁发现的问题" in llm.calls[0]
    assert "定向重写要求" in llm.calls[0]
    assert "已有研究表明" not in content
    assert "[3]" not in content
    assert "运行机制" in content


def test_chapter_writer_keeps_overlong_sections_without_forced_compression(monkeypatch) -> None:
    """模型明显超写时，也不再强制压缩或裁剪正文尾部。"""
    project = ProjectKnowledgeBase(project_name="compress_overlong", title="智慧工地建设与工程现场数字化管理")
    chapter = Chapter(
        chapter_number=1,
        title="字数偏差测试",
        word_count=20,
        sections=[ChapterSection(section_number="1.1", title="超长小节", level=1, word_count=20)],
    )
    project.chapters[1] = chapter
    writer = ChapterWriterAgent(llm_client=object())

    monkeypatch.setattr(writer, "_get_rag_context", lambda query, **kwargs: "")
    monkeypatch.setattr(writer, "_generate_section_with_retries", lambda **kwargs: "这是超长正文。" * 80)
    monkeypatch.setattr(writer, "_quality_gate_section_content", lambda **kwargs: kwargs["content"])
    monkeypatch.setattr("libriscribe.agents.chapter_writer.finalize_academic_chapter", lambda text, target_words=0: (text, 50, "ok"))

    content = writer._write_academic_chapter(project, 1, chapter)

    assert chapter.sections[0].actual_word_count > int(20 * 1.20)
    assert "这是超长正文" in content
    assert content.count("这是超长正文") == 80


def test_chapter_writer_keeps_overlong_content_when_compression_is_still_too_long(monkeypatch) -> None:
    """模型压缩仍超目标时，也不再按字数裁剪正文尾部。"""
    project = ProjectKnowledgeBase(project_name="trim_overlong", title="高职阅读研究")
    chapter = Chapter(
        chapter_number=1,
        title="阅读行为画像",
        word_count=430,
        sections=[ChapterSection(section_number="1.1", title="课表之外的隐性阅读空间", level=1, word_count=430)],
    )
    project.chapters[1] = chapter

    class LongCompressionLLM:
        def generate_content(self, prompt: str, max_tokens: int = 2000, temperature: float = 0.7) -> str:
            return "　　压缩后仍然很长。" * 120

    writer = ChapterWriterAgent(llm_client=LongCompressionLLM())
    monkeypatch.setattr(writer, "_get_rag_context", lambda query, **kwargs: "")
    monkeypatch.setattr(writer, "_generate_section_with_retries", lambda **kwargs: "　　这是严重超长正文。" * 220)
    monkeypatch.setattr(writer, "_quality_gate_section_content", lambda **kwargs: kwargs["content"])
    monkeypatch.setattr("libriscribe.agents.chapter_writer.finalize_academic_chapter", lambda text, target_words=0: (text, 50, "ok"))

    content = writer._write_academic_chapter(project, 1, chapter)

    assert chapter.sections[0].actual_word_count > int(430 * 1.20)
    assert "这是严重超长正文" in content
    assert "压缩后仍然很长" not in content



def test_chapter_writer_finalizes_after_quality_gate_even_without_compression(monkeypatch) -> None:
    """质量门禁返回超长正文时，只做格式规范，不再按字数裁剪正文。"""
    project = ProjectKnowledgeBase(project_name="finalize_after_quality", title="高职阅读研究")
    chapter = Chapter(
        chapter_number=1,
        title="阅读行为画像",
        word_count=430,
        sections=[
            ChapterSection(
                section_number="1.1",
                title="碎片化阅读时间的形成原因",
                level=1,
                word_count=430,
                summary="分析高职学生时间被实训、兼职、通勤切割的原因，只说明形成机制，不展开对策。",
            )
        ],
    )
    project.chapters[1] = chapter
    writer = ChapterWriterAgent(llm_client=object())
    previews = []

    long_quality_text = "　　高职学生时间被实训安排、兼职角色和通勤转场持续切割。" * 140
    monkeypatch.setattr(writer, "_get_rag_context", lambda query, **kwargs: "")
    monkeypatch.setattr(writer, "_generate_section_with_retries", lambda **kwargs: "　　初稿正文。" * 20)
    monkeypatch.setattr(writer, "_quality_gate_section_content", lambda **kwargs: long_quality_text)
    monkeypatch.setattr("libriscribe.agents.chapter_writer.finalize_academic_chapter", lambda text, target_words=0: (text, 50, "ok"))

    content = writer._write_academic_chapter(project, 1, chapter, content_callback=lambda text, *_: previews.append(text))

    assert chapter.sections[0].actual_word_count > int(430 * 1.20)
    assert writer._count_words(previews[-1]) == chapter.sections[0].actual_word_count
    assert previews[-1].startswith("　　")
    assert previews[-1].count("\n\n") == 0
    assert previews[-1][-1] in "。！？.!?"



def test_chapter_writer_final_formatting_does_not_clip_multiple_targets(monkeypatch) -> None:
    """最终格式化不是只针对 430 字，也不应按任意目标字数裁剪正文尾部。"""
    for target_words in (300, 430, 800, 1500, 3000):
        project = ProjectKnowledgeBase(project_name=f"final_limit_{target_words}", title="通用字数控制")
        chapter = Chapter(
            chapter_number=1,
            title="通用控制测试",
            word_count=target_words,
            sections=[ChapterSection(section_number="1.1", title=f"{target_words}字小节", level=1, word_count=target_words)],
        )
        project.chapters[1] = chapter
        writer = ChapterWriterAgent(llm_client=object())
        long_text = "　　这一句用于模拟模型明显超写但仍然包含有效正文内容。" * max(80, target_words // 4)

        monkeypatch.setattr(writer, "_get_rag_context", lambda query, **kwargs: "")
        monkeypatch.setattr(writer, "_generate_section_with_retries", lambda **kwargs: long_text)
        monkeypatch.setattr(writer, "_quality_gate_section_content", lambda **kwargs: kwargs["content"])
        monkeypatch.setattr("libriscribe.agents.chapter_writer.finalize_academic_chapter", lambda text, target_words=0: (text, 50, "ok"))

        writer._write_academic_chapter(project, 1, chapter)

        assert chapter.sections[0].actual_word_count > int(target_words * 1.20)



def test_chapter_writer_shapes_streaming_preview_paragraphs() -> None:
    """流式/中间预览也应合并碎段，不能等最终写入时才处理三四句话一段。"""
    writer = ChapterWriterAgent(llm_client=object())
    previews = []
    fragmented = "\n\n".join([
        "第一句。第二句。第三句。第四句。",
        "第五句。第六句。第七句。第八句。",
    ])

    writer._emit_content_callback(lambda text, *_: previews.append(text), fragmented, "（二） 移动媒介对阅读节奏的重塑", 430, 1, 1)

    assert previews
    assert previews[-1].count("\n\n") == 0
    assert "第四句。第五句。" in previews[-1]



def test_chapter_writer_finalizes_without_clipping_tail_and_keeps_indent() -> None:
    """专著正文不再按字数裁剪尾部；首段必须保留全角缩进。"""
    writer = ChapterWriterAgent(llm_client=object())
    long_sentence = "这种高频、低延迟的反馈模式会持续改变高职学生的阅读节奏与注意力组织方式。"
    content = ("第一句说明制度背景。第二句说明课程切换。第三句说明通勤压力。第四句说明兼职影响。第五句说明媒介介入。" + long_sentence) * 8

    finalized = writer._finalize_section_content(content, "（二） 移动媒介对阅读节奏的重塑", 120)

    assert finalized.startswith("　　")
    assert finalized[-1] in "。！？.!?"
    assert finalized.endswith(long_sentence)
    assert finalized.count(long_sentence) == 8
    assert "　　" in finalized



def test_chapter_writer_appends_tail_completion_without_clipping_original() -> None:
    """模型因输出预算在半句话处中断时，只追加补全，不裁剪已有正文。"""

    class TailCompletionLLM:
        def __init__(self) -> None:
            self.prompts = []

        def generate_content(self, prompt: str, max_tokens: int = 2000, temperature: float = 0.7) -> str:
            self.prompts.append((prompt, max_tokens, temperature))
            return "决定权完全掌握在学生自己手中。"

    writer = ChapterWriterAgent(llm_client=TailCompletionLLM())
    original = "　　这类自主性阅读之所以在育人层面"

    completed = writer._complete_truncated_tail(
        content=original,
        prompt="原始章节提示",
        section_title="（二） 兴趣与情感导向的自主性阅读",
        target_words=430,
    )

    assert completed.startswith(original)
    assert completed == original + "决定权完全掌握在学生自己手中。"
    assert completed.endswith("。")
    assert "不要复述、不要改写、不要删除已经生成的文字" in writer.llm_client.prompts[0][0]


def test_chapter_writer_skips_tail_completion_for_complete_sentence() -> None:
    """已完整闭合的句尾不应触发额外模型调用。"""

    class NoCallLLM:
        def generate_content(self, *args, **kwargs):
            raise AssertionError("complete sentence should not trigger tail completion")

    writer = ChapterWriterAgent(llm_client=NoCallLLM())

    assert writer._complete_truncated_tail("　　这句话已经完整。", "提示", "标题", 430) == "　　这句话已经完整。"


def test_chapter_writer_uses_larger_generation_budgets_for_long_sections(monkeypatch) -> None:
    """长小节不应再用过小输出预算导致模型自然断尾。"""
    project = ProjectKnowledgeBase(project_name="budget", title="预算测试")
    chapter = Chapter(
        chapter_number=1,
        title="预算章",
        word_count=3000,
        sections=[ChapterSection(section_number="1.1", title="预算小节", level=1, word_count=3000)],
    )
    project.chapters[1] = chapter
    writer = ChapterWriterAgent(llm_client=object())
    captured = {}

    monkeypatch.setattr(writer, "_get_rag_context", lambda query, **kwargs: "")

    def fake_generate(**kwargs):
        captured["max_tokens"] = kwargs["max_tokens"]
        return "　　完整正文。"

    monkeypatch.setattr(writer, "_generate_section_with_retries", fake_generate)
    monkeypatch.setattr(writer, "_quality_gate_section_content", lambda **kwargs: kwargs["content"])
    monkeypatch.setattr("libriscribe.agents.chapter_writer.finalize_academic_chapter", lambda text, target_words=0: (text, 50, "ok"))

    writer._write_academic_chapter(project, 1, chapter)

    assert captured["max_tokens"] >= 9000


def test_custom_llm_client_fallbacks_do_not_downshift_to_tiny_output_budgets() -> None:
    """OpenAI-compatible raw HTTP 重试不能再把章节输出预算降到 2500/1200，避免长文断尾。"""
    from libriscribe.utils.llm_client import LLMClient

    client = object.__new__(LLMClient)
    client.llm_provider = "custom"
    client.custom_api_base = "https://example.test/v1"
    client.custom_api_key = "key"
    client.model = "model"
    client.client = types.SimpleNamespace(responses=None)
    client.last_error = ""
    client.last_response_preview = ""
    payloads = []

    class FakeResponse:
        text = "{}"

        def raise_for_status(self) -> None:
            raise RuntimeError("stop after first raw attempt")

    def fake_post(url, headers, json, timeout):
        payloads.append(json)
        return FakeResponse()

    monkeypatch = None
    import requests
    original_post = requests.post
    try:
        requests.post = fake_post
        client.generate_content("提示", max_tokens=16000, temperature=0.4)
    finally:
        requests.post = original_post

    max_token_values = [payload.get("max_tokens") for payload in payloads if "max_tokens" in payload]
    assert max_token_values[:3] == [16000, 12000, 6000]
    assert 2500 not in max_token_values
    assert 1200 not in max_token_values


def test_chapter_writer_enforces_max_three_balanced_paragraphs() -> None:
    """无论模型输出多少碎段，最终每小节最多 3 段，且可切分时每段不少于 5 句。"""
    writer = ChapterWriterAgent(llm_client=object())
    fragmented = "\n\n".join(f"第{i}句说明一个连续论证环节。" for i in range(1, 19))

    shaped = writer._finalize_section_content(fragmented, "（三） 段落结构测试", 1500)
    paragraphs = [p for p in shaped.split("\n\n") if p.strip()]

    assert len(paragraphs) <= 3
    assert all(p.startswith("　　") for p in paragraphs)
    assert all("\n" not in p for p in paragraphs)
    assert all(len(re.findall(r"[。！？.!?]", p)) >= 5 for p in paragraphs)



def test_chapter_writer_prompt_prioritizes_section_summary_and_tight_word_limit() -> None:
    """提示词必须明确优先按小节写作思路写，且 430 字小节只写少量长段。"""
    project = ProjectKnowledgeBase(project_name="prompt_priority", title="高职阅读研究", target_audience="高校管理者")
    chapter = Chapter(chapter_number=1, title="阅读行为画像", summary="章摘要")
    section = ChapterSection(
        section_number="1.1",
        title="碎片化阅读时间的形成原因",
        level=1,
        word_count=430,
        summary="只分析时间碎片化的制度和场景原因，不写解决方案。",
    )
    writer = ChapterWriterAgent(llm_client=object())

    prompt = writer._build_academic_section_prompt(
        project=project,
        chapter=chapter,
        chapter_number=1,
        section=section,
        section_title="（一） 碎片化阅读时间的形成原因",
        target_words=430,
        outline_tree="- 第一节 高职学生的阅读行为画像",
        terminology="",
        previous_summaries="",
        rag_context="",
        generated_summaries="",
    )

    assert "写作思路（最高优先级" in prompt
    assert "只分析时间碎片化的制度和场景原因，不写解决方案" in prompt
    assert "不擅自扩展案例、背景、意义、对策" in prompt
    assert "建议范围 365—473 字" in prompt
    assert "只写 1 个自然段" in prompt
    assert "每个小节最多 3 个自然段" in prompt
    assert "不得使用任何形式的“不仅……而且……”" in prompt
    assert "不得使用“值得注意的是”“需要强调的是”“理应指出”" in prompt
    assert "“某种意义上”“在一定程度上”“大致而言”" in prompt
    assert "提供了有益的尝试" in prompt
    assert "定义必须带立场" in prompt
    assert "本书使用X这一概念，是在Y的意义上，区别于Z的用法" in prompt
    assert "用短句做判断，用长句做分析" in prompt
    assert "结论句必须短而明确" in prompt
    assert "取消空泛过渡段" in prompt
    assert "每一节的结尾必须成为下一节的新困难、新矛盾或新质疑" in prompt
    assert "每章至少安排三处明确批评" in prompt
    assert "禁止“综上所述”式总结" in prompt
    assert "无条件给出自己的判断" in prompt
    assert "允许展示推理的毛边" in prompt


def test_chapter_writer_compact_and_quality_prompts_include_anti_ai_style_rules() -> None:
    """精简重试和质量门禁重写也必须继承反 AI 腔、立场定义和反驳衔接规则。"""
    writer = ChapterWriterAgent(llm_client=object())

    compact = writer._build_compact_retry_prompt("上下文", "（一） 概念边界", 430)
    quality = writer._build_quality_rewrite_prompt(
        prompt="原始提示",
        section_title="（一） 概念边界",
        content="待改正文",
        target_words=430,
        issue_summary="问题",
    )

    for prompt in (compact, quality):
        assert "不仅……而且" in prompt
        assert "值得注意的是" in prompt
        assert "需要强调的是" in prompt
        assert "某种意义上" in prompt
        assert "在一定程度上" in prompt
        assert "提供了有益的尝试" in prompt
        assert "综上所述" in prompt
    assert "定义必须带立场" in compact
    assert "定义必须带立场" in quality
    assert "节尾用反驳、限制或矛盾" in compact
    assert "节尾用推论、限制或矛盾衔接" in quality


def test_chapter_writer_strips_plain_duplicate_heading() -> None:
    """模型把小节标题当正文第一行输出时，应清除，避免页面出现连续两个相同标题。"""
    writer = ChapterWriterAgent(llm_client=object())
    cleaned = writer._strip_duplicate_heading(
        "（三） 课表之外的隐性阅读空间\n\n　　这里是正文第一段。",
        "（三） 课表之外的隐性阅读空间",
    )
    cleaned_without_prefix = writer._strip_duplicate_heading(
        "（一）碎片化阅读时间的形成原因\n\n　　这里是正文第一段。",
        "（一） 碎片化阅读时间的形成原因",
    )

    assert cleaned == "这里是正文第一段。"
    assert cleaned_without_prefix == "这里是正文第一段。"


def test_chapter_writer_enforces_fewer_longer_paragraphs() -> None:
    """小节正文应合并碎段，430 字左右的小节默认不拆成很多短段。"""
    writer = ChapterWriterAgent(llm_client=object())
    text = "\n\n".join([
        "第一句。第二句。第三句。",
        "第四句。第五句。第六句。",
        "第七句。第八句。第九句。",
    ])

    shaped = writer._enforce_paragraph_shape(text, 430)

    assert shaped.count("\n\n") == 0
    assert "第一句。第二句。第三句。第四句。第五句。" in shaped


def test_section_heading_chain_includes_chapter_and_parent_sections() -> None:
    """单小节实时预览没有已有正文时，也应显示章标题和上级目录链。"""
    project = ProjectKnowledgeBase(project_name="heading_chain", title="高职阅读研究")
    project.chapters[1] = Chapter(
        chapter_number=1,
        title="高职院校阅读推广的现实图景与AI机遇",
        sections=[
            ChapterSection(section_number="1.1", title="高职学生的阅读行为画像", level=1),
            ChapterSection(section_number="1.1.1", title="阅读时间的碎片化：课表之外的阅读空间在哪里", level=2),
            ChapterSection(section_number="1.1.1.1", title="碎片化阅读时间的形成原因", level=3),
        ],
    )

    chain = app._section_heading_chain(project, 1, "1.1.1.1")

    assert "# 第一章 高职院校阅读推广的现实图景与AI机遇" in chain
    assert "## 第一节 高职学生的阅读行为画像" in chain
    assert "### 一、 阅读时间的碎片化：课表之外的阅读空间在哪里" in chain
    assert "#### （一） 碎片化阅读时间的形成原因" not in chain


def test_chapter_writer_quality_gate_keeps_clean_section_without_rewrite(monkeypatch) -> None:
    """小节正文通过质量门禁时，不应额外调用模型重写，避免拖慢正常生成。"""

    class NoRewriteLLM:
        llm_provider = "custom"

        def generate_content(self, prompt: str, max_tokens: int = 2000, temperature: float = 0.7) -> str:
            raise AssertionError("clean section should not trigger quality rewrite")

    project = ProjectKnowledgeBase(project_name="quality_gate_clean", title="智慧工地建设与工程现场数字化管理")
    chapter = Chapter(
        chapter_number=1,
        title="质量门禁测试",
        word_count=120,
        sections=[ChapterSection(section_number="1.1", title="干净小节", level=1, word_count=120)],
    )
    project.chapters[1] = chapter
    writer = ChapterWriterAgent(llm_client=NoRewriteLLM())
    clean = "　　本节围绕智慧工地建设的概念边界、运行机制、实施路径和风险治理展开分析，强调工程现场数字化管理需要在组织体系、数据治理、技术集成和价值评估之间形成稳定协同。"

    monkeypatch.setattr(writer, "_get_rag_context", lambda query, **kwargs: "")
    monkeypatch.setattr(writer, "_generate_section_with_retries", lambda **kwargs: clean)
    monkeypatch.setattr("libriscribe.agents.chapter_writer.finalize_academic_chapter", lambda text, target_words=0: (text, 50, "ok"))

    content = writer._write_academic_chapter(project, 1, chapter)

    assert "运行机制" in content
    assert "价值评估" in content


def test_chapter_label_surfaces_use_chinese_numerals() -> None:
    """章节生成、编辑器和导出兜底标题都应显示“第一章”，不能退回“第1章/第 1 章”。"""
    assert app._format_chapter_label(1, "智慧工地建设总论") == "第一章 智慧工地建设总论"
    assert app._format_chapter_label(12) == "第十二章"
    assert app.t("chapter_item", n=1) == "第一章"

    writer_source = inspect.getsource(ChapterWriterAgent._write_academic_chapter)
    editor_source = inspect.getsource(app.render_editor_page)
    bg_source = inspect.getsource(app._bg_write_chapter)

    assert 'f"# 第{chapter_number}章 {chapter.title}"' not in writer_source
    assert "format_chapter_label(chapter_number, chapter.title)" in writer_source
    assert 'f"第 {selected_ch_num} 章' not in editor_source
    assert "_format_chapter_label(selected_ch_num" in editor_source
    assert 'f"第 {chapter_num} 章' not in bg_source
    assert "_format_chapter_label(chapter_num)" in bg_source

    assert DocxExporter.__module__
    assert PdfExporter.__module__
    assert LatexExporter.__module__
    assert PptxExporter()._chapter_title({"number": 2, "title": "技术体系"}) == "第二章 技术体系"


def test_shared_chapter_heading_strip_handles_chinese_and_legacy_titles() -> None:
    """页面与导出器应共用章标题去重逻辑，兼容第一章、第 1 章和 Chapter 1。"""
    body = "\n\n## 第一节 背景\n正文"
    cases = [
        "# 第一章 智慧工地建设总论" + body,
        "# 第 1 章 智慧工地建设总论" + body,
        "# Chapter 1 智慧工地建设总论" + body,
    ]

    for content in cases:
        assert app._strip_export_chapter_heading(content, 1, "智慧工地建设总论").startswith("## 第一节")
        assert DocxExporter()._strip_leading_chapter_heading(content, 1, "智慧工地建设总论").startswith("## 第一节")
        assert PdfExporter()._strip_leading_chapter_heading(content, 1, "智慧工地建设总论").startswith("## 第一节")
        assert LatexExporter()._strip_leading_chapter_heading(content, 1, "智慧工地建设总论").startswith("## 第一节")


def test_collect_chapters_includes_preface_conclusion_and_references_in_order(tmp_path) -> None:
    project = ProjectKnowledgeBase(project_name="demo", title="测试专著", project_dir=tmp_path)
    project.chapters = {
        1: Chapter(chapter_number=1, title="绪论"),
        2: Chapter(chapter_number=2, title="主体分析"),
    }
    (tmp_path / "front_matter_preface.md").write_text("# 前言\n\n前言正文", encoding="utf-8")
    (tmp_path / "chapter_1.md").write_text("# 第一章 绪论\n\n第一章正文", encoding="utf-8")
    (tmp_path / "chapter_2.md").write_text("# 第二章 主体分析\n\n第二章正文", encoding="utf-8")
    (tmp_path / "back_matter_conclusion.md").write_text("# 结语\n\n结语正文", encoding="utf-8")
    (tmp_path / "back_matter_references.md").write_text("# 参考文献\n\n[1] 测试文献。", encoding="utf-8")

    collected = app._collect_chapters(project)

    assert [item["display_title"] for item in collected] == ["前言", "第一章 绪论", "第二章 主体分析", "结语", "参考文献"]
    assert collected[0]["kind"] == "front_matter"
    assert collected[-1]["part_key"] == "references"
    assert collected[1]["number"] == 1


def test_exporters_accept_non_numbered_manuscript_parts(tmp_path) -> None:
    chapters = [
        {"kind": "front_matter", "title": "前言", "display_title": "前言", "content": "# 前言\n\n前言正文"},
        {"number": 1, "chapter_number": 1, "title": "绪论", "display_title": "第一章 绪论", "content": "# 第一章 绪论\n\n章节正文"},
        {"kind": "back_matter", "title": "结语", "display_title": "结语", "content": "# 结语\n\n结语正文"},
    ]

    tex_path = tmp_path / "book.tex"
    LatexExporter().export(chapters, str(tex_path), title="测试专著", language="简体中文")
    tex = tex_path.read_text(encoding="utf-8")
    assert "\\chapter*{前言}" in tex
    assert "\\chapter*{结语}" in tex

    if DocxExporter()._docx_available:
        docx_path = tmp_path / "book.docx"
        DocxExporter().export(chapters, str(docx_path), title="测试专著", language="简体中文")
        assert docx_path.exists()


def test_editor_page_exposes_manuscript_part_generation_controls() -> None:
    source = inspect.getsource(app.render_editor_page)
    assert "专著前后内容与参考文献" in source
    assert "AI生成" in source
    assert "前言在第一章前" in source
    assert "参考文献在结语后" in source
    assert "生成要求" in source
    assert "前言预期字数" in source
    assert "结语预期字数" in source
    assert "引用文献起始年份" in source
    assert "引用格式" in source


def test_manuscript_part_prompts_use_user_requirements_and_specialized_templates(tmp_path) -> None:
    project = ProjectKnowledgeBase(project_name="demo", title="测试专著", genre="智慧工地", project_dir=tmp_path)
    project.chapters = {1: Chapter(chapter_number=1, title="绪论", summary="界定研究对象与核心问题。")}
    (tmp_path / "front_matter_preface.md").write_text("前言\n\n本书关注工程现场数字化治理。", encoding="utf-8")

    preface_prompt = app._build_manuscript_part_prompt(project, "preface", "突出行业痛点", {"forewordWordCount": 1800})
    conclusion_prompt = app._build_manuscript_part_prompt(project, "conclusion", "回应实践价值", {"conclusionWordCount": 1200})
    references_prompt = app._build_manuscript_part_prompt(
        project,
        "references",
        "优先中文核心期刊",
        {
            "refStartYear": 2020,
            "refEndYear": 2026,
            "refCount": 20,
            "languageDistribution": "中文为主",
            "citationStyle": "GB/T 7714-2015",
        },
    )

    assert "你是一名学术专著撰写专家" in preface_prompt
    assert "前言预期字数：1800 字；绝对允许范围：1656—1944 字" in preface_prompt
    assert "不得输出“前言”二字" in preface_prompt
    assert "突出行业痛点" in preface_prompt
    assert "最终输出绝对不能包含任何字数统计" in preface_prompt
    assert "结语预期字数：1200 字；绝对允许范围：1104—1296 字" in conclusion_prompt
    assert "不得输出“结语”二字" in conclusion_prompt
    assert "前言核心问题与主张" in conclusion_prompt
    assert "回应实践价值" in conclusion_prompt
    assert "你是一名学术参考文献整理专家" in references_prompt
    assert "引用文献时间范围：严格限制为 2020 年至 2026 年" in references_prompt
    assert "建议文献数量：约 20 条" in references_prompt
    assert "中文为主" in references_prompt
    assert "GB/T 7714-2015" in references_prompt
    assert "优先中文核心期刊" in references_prompt
    assert "不得输出“参考文献”四个字标题" in references_prompt
    assert "不得在文献末尾附加 DOI、URL、OpenAlex、网页链接或 `https://` 链接" in references_prompt


def test_manuscript_part_generation_options_read_latest_session_state(monkeypatch) -> None:
    """网页修改前言/结语字数后，AI 生成必须读取当前控件值，而不是默认 1500/1600。"""
    monkeypatch.setattr(
        app.st,
        "session_state",
        {
            "manuscript_part_preface_word_count": 900,
            "manuscript_part_conclusion_word_count": 900,
        },
    )

    preface_options = app._manuscript_part_generation_options_from_state("preface", {"forewordWordCount": 1500})
    conclusion_options = app._manuscript_part_generation_options_from_state("conclusion", {"conclusionWordCount": 1600})

    assert app._target_word_count_for_part("preface", preface_options) == 900
    assert app._target_word_count_for_part("conclusion", conclusion_options) == 900


def test_manuscript_part_truncation_hard_caps_overlong_model_output() -> None:
    """模型多次不听字数限制时，超长前言/结语最终仍要被程序硬截断。"""
    long_text = "。".join(["测试正文" * 120 for _ in range(10)])

    truncated = app._truncate_manuscript_part_to_max_words(long_text, 972)

    assert app._count_manuscript_words(truncated) <= 972
    assert truncated.endswith(("。", "！", "？", ".", "!", "?"))


def test_sidebar_exposes_formatted_word_export_and_structured_adapter(tmp_path) -> None:
    project = ProjectKnowledgeBase(project_name="demo", title="测试专著", genre="专著", project_dir=tmp_path)
    project.chapters = {1: Chapter(chapter_number=1, title="绪论")}
    (tmp_path / "front_matter_preface.md").write_text("# 前言\n\n前言正文", encoding="utf-8")
    (tmp_path / "chapter_1.md").write_text(
        "# 第一章 绪论\n\n"
        "## 第一节 背景\n\n"
        "章节正文\n\n"
        "### 一、现实背景\n\n"
        "三级正文\n\n"
        "#### （一）政策牵引\n\n"
        "四级正文一\n\n"
        "#### （二）技术基础\n\n"
        "四级正文二",
        encoding="utf-8",
    )
    (tmp_path / "back_matter_conclusion.md").write_text("# 结语\n\n结语正文", encoding="utf-8")
    (tmp_path / "back_matter_references.md").write_text("# 参考文献\n\n[1] 测试文献。", encoding="utf-8")

    sidebar_source = inspect.getsource(app.render_sidebar)
    export_source = inspect.getsource(app._export_formatted_word)
    structured = app._project_to_formatted_word_json(project)

    assert "Word（带格式）导出" in sidebar_source
    assert "export_json_data_to_docx" in export_source
    assert structured["preface"] == ["前言正文"]
    assert structured["chapters"][0]["heading"] == "第一章 绪论"
    assert structured["chapters"][0]["sections"][0]["heading"] == "第一节 背景"
    section = structured["chapters"][0]["sections"][0]
    assert section["level3"][0]["heading"] == "一、现实背景"
    assert section["subsections"][0] is section["level3"][0]
    assert section["level3"][0]["content"] == ["三级正文"]
    assert section["level3"][0]["level4"][0]["heading"] == "（一）政策牵引"
    assert section["level3"][0]["level4"][0]["content"] == ["四级正文一"]
    assert section["level3"][0]["level4"][1]["heading"] == "（二）技术基础"
    assert section["level3"][0]["level4"][1]["content"] == ["四级正文二"]
    assert structured["conclusion"] == ["结语正文"]
    assert structured["global_references"] == ["[1] 测试文献。"]


class _EmptyVectorStore(VectorStore):
    def __init__(self) -> None:
        self.embedding_provider = None

    @property
    def count(self) -> int:
        return 0

    def query(self, query_text: str, top_k: int = 5, filter_metadata: dict | None = None):
        raise AssertionError("空向量库不应执行 embedding query")

    def list_sources(self):
        return []


def test_retriever_skips_embedding_provider_when_vector_store_is_empty() -> None:
    """无资料索引时检索应快速返回，避免每小节反复加载本地 embedding 权重。"""
    retriever = Retriever(vector_store=_EmptyVectorStore(), embedding_provider=None)

    assert retriever.retrieve("智慧工地") == []
    assert retriever.embedding_provider is None


def test_generate_book_does_not_mutate_editor_selectbox_widget_state() -> None:
    """生成全书不能在编辑器 selectbox 实例化后写入同名 widget key。"""
    source = inspect.getsource(app._generate_book_with_ai)

    assert 'st.session_state["editor_selected_idx"]' not in source
    assert 'book_generation_current_chapter' in source


def test_parse_outline_ignores_prose_references_to_other_chapters() -> None:
    """正文说明里出现“第二章/第三章”时，不能被误识别为新章节。"""
    project = app.ProjectKnowledgeBase(project_name="cn_outline_prose", title="智慧工地建设与工程现场数字化管理")
    outline = """第一章 智慧工地建设的背景、内涵与价值定位（总字数 10000字）
第一节 智慧工地建设背景（约3000字）
一、工程现场数字化转型背景
写作思路：承接第二章技术体系，但本节只说明建设背景。资料依据可参考政策文件；证据边界在于不同地区监管要求不同。后续需补充地方政策案例。
第二节 智慧工地价值定位（约3000字）
第二章 数据治理与安全管理体系（总字数 12000字）
第一节 数据治理机制（约4000字）
一、数据标准与责任划分
第三章数据治理和安全管理形成衔接，但重点放在实施评价阶段如何识别和应对风险。资料依据可参考信息化项目风险管理方法、智慧工地运维问题记录、网络安全合规要求和项目复盘材料；证据边界在于风险清单具有情境性，需要结合项目规模、参建主体和地方监管要求进行修订。后续需补充风险分级表、整改闭环案例、数据异常样本和系统故障应急预案。
第四章物联网监测机制衔接，本处重在说明机械设备数据进入平台后的综合应用和管理联动。资料依据可来自特种设备安全管理规定、设备监测终端数据、维保台账和智慧工地平台案例。"""

    created = app._parse_outline_text(project, outline, persist=False, rerun=False, show_messages=False)

    assert created == 2
    assert sorted(project.chapters.keys()) == [1, 2]
    assert project.chapters[1].title == "智慧工地建设的背景、内涵与价值定位"
    assert project.chapters[2].title == "数据治理与安全管理体系"
    titles = [chapter.title for chapter in project.chapters.values()]
    assert all("资料依据" not in title for title in titles)
    assert all("证据边界" not in title for title in titles)
    assert all("后续需补充" not in title for title in titles)


def test_outline_target_settings_infer_monograph_chapters_when_default_is_one() -> None:
    """旧项目默认 1 章时，应按专著篇幅自动建议多章，而不是只生成第一章。"""
    project = app.ProjectKnowledgeBase(
        project_name="smart_site",
        title="智慧工地建设与工程现场数字化管理",
        description="围绕工程现场数字化、BIM、AIoT、数据治理、组织协同和监管评价展开系统论述。",
        book_length="12万字",
        num_chapters=1,
    )

    target_chapters, target_words, words_per_chapter = app._outline_target_settings(project)

    assert target_chapters == 10
    assert target_words == 120000
    assert words_per_chapter == 12000


def test_outline_target_settings_respect_user_custom_chapter_count() -> None:
    """用户手动指定章数时，生成逻辑应按用户目标章数调优。"""
    project = app.ProjectKnowledgeBase(
        project_name="custom_outline",
        title="智慧工地建设与工程现场数字化管理",
        book_length="12万字",
        num_chapters=7,
    )

    target_chapters, target_words, words_per_chapter = app._outline_target_settings(project)

    assert target_chapters == 7
    assert target_words == 120000
    assert words_per_chapter == 120000 // 7


def test_outline_brainstorm_is_persisted_and_injected_into_constraints() -> None:
    """第二步资料页沉淀的头脑风暴应进入后续大纲生成约束。"""
    project = app.ProjectKnowledgeBase(
        project_name="brainstorm_outline",
        title="智慧工地建设与工程现场数字化管理",
        description="围绕工程现场数字化管理展开。",
        outline_brainstorm="核心问题：数据治理如何支撑工程现场协同。推荐模块：理论基础、技术体系、应用场景、监管评价。证据边界：OpenAlex 候选需核验。",
        book_length="10万字",
        num_chapters=8,
    )

    constraints = app._outline_global_constraints(project, 8, 100000, 12500, include_preface=True)

    assert "大纲前资料头脑风暴" in constraints
    assert "数据治理如何支撑工程现场协同" in constraints
    assert "不得编造未核验文献" in constraints
    assert app._outline_brainstorm_context(project).startswith("核心问题")


def test_material_library_context_is_injected_into_outline_constraints() -> None:
    """用户上传/导入的资料库片段应进入大纲提示词，而不是只依赖向量索引。"""
    project = app.ProjectKnowledgeBase(
        project_name="material_outline",
        title="智慧工地建设与工程现场数字化管理",
        book_length="10万字",
    )
    project.add_source_document(SourceDocument(
        id="doc_user_report",
        title="项目访谈纪要",
        file_name="访谈纪要.md",
        source_type="markdown",
        status="library_only",
    ))
    project.add_evidence_chunk(EvidenceChunk(
        id="ev_user_report_1",
        document_id="doc_user_report",
        source="访谈纪要.md",
        text="施工现场管理人员提到，进度计划需要与楼栋、楼层、施工段和班组任务形成映射，才能支撑动态纠偏。",
    ))

    constraints = app._outline_global_constraints(project, 8, 100000, 12500, include_preface=True)
    formatted = app._format_outline_prompt(
        "书名：{book_title}\n资料：{outline_brainstorm}",
        project,
        target_chapters=8,
        target_words=100000,
        words_per_chapter=12500,
        include_preface=True,
    )

    assert "资料库用户上传/导入资料片段" in constraints
    assert "必须作为大纲内容和后续正文引用参考的重要来源" in constraints
    assert "进度计划需要与楼栋、楼层、施工段和班组任务形成映射" in constraints
    assert "访谈纪要.md" in formatted



def test_project_languages_default_to_simplified_chinese_without_duplicate() -> None:
    """Project language options default to Simplified Chinese and avoid duplicate Chinese labels."""
    assert app.PROJECT_LANGUAGES[0] == "简体中文"
    assert "中文" not in app.PROJECT_LANGUAGES
    assert len(app.PROJECT_LANGUAGES) == len(set(app.PROJECT_LANGUAGES))


def test_outline_page_exposes_editable_section_management() -> None:
    """大纲章节管理不再只 caption 展示小节，必须支持标题、写作目标和目标字数编辑。"""
    source = inspect.getsource(app.render_outline_page)

    assert "小节管理" in source
    assert "小节标题" in source
    assert "写作目标 / 写作思路（仅提交给 AI，不直接作为正文预览）" in source
    assert "目标字数" in source
    assert "ch.sections = edited_sections" in source
    assert 'st.caption(f"{indent}{_format_outline_section_label(sec.section_number, sec.title)}{wc_str}")' not in source


def test_model_profile_editor_binds_widgets_to_selected_profile() -> None:
    """模型档案切换后表单和字段 key 必须随档案变化，且不混入资料索引 API 字段。"""
    source = inspect.getsource(app.render_ai_config_page)

    assert 'key="model_profile_editor_select"' in source
    assert 'form_key = f"model_profile_form_{selected_id}"' in source
    assert 'key=f"profile_name_{selected_id}"' in source
    assert 'key=f"profile_provider_{selected_id}"' in source
    assert 'key=f"profile_model_{selected_id}"' in source
    assert 'key=f"profile_api_base_{selected_id}_{provider}"' in source
    assert 'key=f"profile_enabled_{selected_id}"' in source
    assert 'key=f"profile_embedding_api_base_{selected_id}"' not in source
    assert 'key=f"profile_embedding_api_key_{selected_id}"' not in source
    assert 'key=f"profile_embedding_model_{selected_id}"' not in source
    assert '"embedding_api_base": embedding_api_base.rstrip("/")' not in source
    assert '"embedding_api_key": effective_embedding_api_key' not in source
    assert '"embedding_model": embedding_model.strip()' not in source



def test_material_index_api_config_is_independent_from_model_profiles() -> None:
    """资料索引 API 必须是独立区域和独立配置文件，不写入上方模型档案。"""
    source = inspect.getsource(app.render_ai_config_page)
    load_source = inspect.getsource(app._load_material_index_config)
    save_source = inspect.getsource(app._save_material_index_config)

    assert "### 资料索引 API 配置" in source
    assert "material_index_api_config_form" in source
    assert "material_index_api_base" in source
    assert "material_index_api_key" in source
    assert "material_index_model" in source
    assert "不会影响上方模型档案" in source
    assert "MATERIAL_INDEX_CONFIG" in load_source
    assert "MATERIAL_INDEX_CONFIG" in save_source
    assert "MODEL_PROFILE_CONFIG" not in load_source
    assert "MODEL_PROFILE_CONFIG" not in save_source


def test_model_defaults_are_updated_for_latest_ai_profiles() -> None:
    """AI 配置默认模板应使用新的主流模型，并迁移旧官方空档案。"""
    assert app.DEFAULT_PROVIDER_MODELS["openai"] == "gpt-5.5"
    assert app.DEFAULT_PROVIDER_MODELS["deepseek"] == "deepseek-v4-pro"
    assert app.DEFAULT_PROVIDER_MODELS["openrouter"] == "openai/gpt-5.5"

    stale_profile = {
        "id": "openai_openai",
        "name": "OpenAI",
        "provider": "openai",
        "api_base": "",
        "api_key": "",
        "model": "gpt-4o-mini",
        "enabled": False,
        "source": "official",
        "updated_at": "",
    }

    normalized = app._dedupe_model_profiles([stale_profile])

    assert normalized[0]["model"] == "gpt-5.5"


def test_chapter_writer_prompts_include_de_ai_editorial_style_rules() -> None:
    """章节默认提示词和内置 YAML 都应强化去 AI 味与出版级中文表达。"""
    default_prompt = app.PromptService.load_builtin_template("chapter_writer")
    prompt_builder_source = inspect.getsource(ChapterWriterAgent._build_academic_section_prompt)

    assert "弱化 AI 痕迹" in default_prompt
    assert "首先、其次、最后" in default_prompt
    assert "成熟研究者或科技记者" in default_prompt
    assert "去 AI 痕迹与出版级表达" in prompt_builder_source
    assert "真实研究者或专业作者的自然表达" in prompt_builder_source
    assert "机械化总分总结构" in PROMPT_ANALYSIS_GUIDE


def test_chapter_writer_uses_project_material_context_without_vector_index() -> None:
    """章节写作在 Chroma/embedding 不可用时，应直接回退读取项目资料库片段。"""
    writer = ChapterWriterAgent(llm_client=None)
    project = ProjectKnowledgeBase(project_name="material_draft", title="智慧工地建设与工程现场数字化管理")
    project.add_source_document(SourceDocument(
        id="doc_progress_case",
        title="进度纠偏案例",
        file_name="进度纠偏案例.txt",
        source_type="txt",
        status="library_only",
    ))
    project.add_evidence_chunk(EvidenceChunk(
        id="ev_progress_case_1",
        document_id="doc_progress_case",
        source="进度纠偏案例.txt",
        text="进度动态纠偏需要将周计划、日计划、作业面任务单和班组反馈数据统一到平台中，形成可追溯闭环。",
    ))

    context = writer._get_project_material_context(project, query="进度 动态纠偏", max_chunks=3)

    assert "进度纠偏案例.txt" in context
    assert "作业面任务单和班组反馈数据" in context
    assert "evidence_id=ev_progress_case_1" in context



def test_rag_upload_accepts_copywriting_material_formats_and_library_fallback() -> None:
    """上传资料默认只入资料库，只有用户勾选时才初始化 embedding/向量索引。"""
    settings_source = inspect.getsource(app.render_settings_page)
    sources_source = inspect.getsource(app.render_sources_page)
    editor_source = inspect.getsource(app.render_editor_page)
    index_source = inspect.getsource(app._index_rag_documents)

    assert 'type=["pdf", "docx", "txt", "md", "markdown", "html", "htm", "xlsx", "xls"]' in settings_source
    assert "build_vector_index: bool = False" in index_source
    assert "不主动下载 HuggingFace embedding 模型" in settings_source
    assert "不主动下载 HuggingFace embedding 模型" in sources_source
    assert "不主动下载 HuggingFace embedding 模型" in editor_source
    assert 'st.button("导入资料库"' in settings_source
    assert 'st.button("导入资料库"' in sources_source
    assert "sources_build_vector_index" in sources_source
    assert "settings_build_vector_index" in settings_source
    assert "chapter_build_vector_index" in editor_source
    assert "未启用向量索引：资料已先以资料库模式导入" in index_source
    assert "if build_vector_index:" in index_source
    assert "_embedding_provider_from_material_index_config()" in index_source
    assert "使用独立资料索引 API 配置建立索引" in index_source
    assert 'vector_status = "indexed" if added > 0 and not indexing_error else "library_only"' in index_source
    assert '"can_use_for_outline": True' in index_source
    assert '"can_use_for_draft": True' in index_source
    assert '"can_use_for_reference": True' in index_source
    assert "_format_source_upload_feedback" in index_source
    assert "资料已入库" in inspect.getsource(app._format_source_upload_feedback)
    assert "last_source_upload_feedback" in index_source
    assert "最近一次资料上传入库证明" in sources_source



def test_editor_generation_shows_material_usage_feedback() -> None:
    """正文生成前后必须显示资料库调用证明，让用户知道 AI 参考了哪些上传资料。"""
    editor_source = inspect.getsource(app.render_editor_page)
    generation_source = inspect.getsource(app._run_live_chapter_generation)
    feedback_source = inspect.getsource(app._material_usage_feedback)

    assert "资料库可用性证明" in editor_source
    assert "正文生成资料库调用证明" in generation_source
    assert "生成完成资料引用证明" in generation_source
    assert "last_generation_material_feedback" in generation_source
    assert "evidence_id" in feedback_source
    assert "本次写作已调用资料库参考" in feedback_source



def test_embedding_provider_can_use_openai_compatible_api_without_local_fallback(monkeypatch) -> None:
    """向量索引底层支持 OpenAI-compatible embedding API，且失败时不再强制 HuggingFace。"""
    captured = {}

    class FakeOpenAI:
        def __init__(self, *, api_key: str, base_url: str = "") -> None:
            captured["api_key"] = api_key
            captured["base_url"] = str(base_url)
            self.embeddings = self

        def create(self, *, model: str, input: list[str]):
            captured["model"] = model
            captured["input"] = input

            class Item:
                embedding = [0.1, 0.2, 0.3]

            class Response:
                data = [Item() for _ in input]

            return Response()

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)

    provider = EmbeddingProvider(
        provider="custom_openai",
        model="text-embedding-3-small",
        api_base="https://example.com/v1",
        api_key="sk-test",
        allow_local_fallback=False,
    )
    embeddings = provider.embed_texts(["资料片段"])

    assert embeddings == [[0.1, 0.2, 0.3]]
    assert captured["api_key"] == "sk-test"
    assert captured["base_url"] == "https://example.com/v1"
    assert captured["model"] == "text-embedding-3-small"



def test_material_index_config_is_used_for_vector_index_embedding(monkeypatch) -> None:
    """向量索引只读取独立资料索引 API，不借用项目聊天模型档案。"""
    monkeypatch.setattr(
        app,
        "_load_material_index_config",
        lambda: {
            "enabled": True,
            "provider": "custom_openai",
            "api_base": "https://api.deepseek.com/v1",
            "api_key": "sk-embedding-test",
            "model": "DeepSeek-V4-Flash",
        },
    )

    provider = app._embedding_provider_from_material_index_config()

    assert provider.provider == "custom_openai"
    assert provider.model == "DeepSeek-V4-Flash"
    assert provider._api_base == "https://api.deepseek.com/v1"
    assert provider._api_key == "sk-embedding-test"
    assert provider._allow_local_fallback is False



def test_delete_source_document_removes_document_and_related_evidence_only() -> None:
    """删除资料时应移除来源文档及其证据片段，但保留其他资料。"""
    project = ProjectKnowledgeBase(project_name="delete_source", title="资料删除测试")
    project.source_documents = [
        SourceDocument(id="doc_keep", title="保留资料", file_name="keep.txt"),
        SourceDocument(id="doc_delete", title="删除资料", file_name="delete.txt"),
    ]
    project.evidence_chunks = [
        EvidenceChunk(id="ev_keep", document_id="doc_keep", text="保留片段"),
        EvidenceChunk(id="ev_delete_1", document_id="doc_delete", text="删除片段 1"),
        EvidenceChunk(id="ev_delete_2", document_id="doc_delete", text="删除片段 2"),
    ]

    deleted_docs, deleted_chunks = app._delete_source_document_from_project(project, "doc_delete")

    assert deleted_docs == 1
    assert deleted_chunks == 2
    assert [doc.id for doc in project.source_documents] == ["doc_keep"]
    assert [chunk.id for chunk in project.evidence_chunks] == ["ev_keep"]


def test_delete_evidence_chunk_removes_single_chunk_only() -> None:
    """删除证据片段时应仅移除指定 chunk，不影响同文档的其他片段。"""
    project = ProjectKnowledgeBase(project_name="delete_chunk", title="证据片段删除测试")
    project.evidence_chunks = [
        EvidenceChunk(id="chunk_keep", document_id="doc_a", text="保留片段"),
        EvidenceChunk(id="chunk_delete", document_id="doc_a", text="删除片段"),
        EvidenceChunk(id="chunk_other", document_id="doc_b", text="其他片段"),
    ]

    deleted = app._delete_evidence_chunk_from_project(project, "chunk_delete")

    assert deleted == 1
    assert len(project.evidence_chunks) == 2
    assert [chunk.id for chunk in project.evidence_chunks] == ["chunk_keep", "chunk_other"]


def test_sources_page_supports_viewing_and_deleting_materials() -> None:
    """资料页应支持查看来源详情、关联证据片段并删除资料。"""
    source = inspect.getsource(app.render_sources_page)
    delete_source = inspect.getsource(app._delete_source_document_from_project)

    assert "### 已索引资料" in source
    assert "删除资料" in source
    assert "查看资料详情与片段" in source
    assert "关联证据片段" in source
    assert "_delete_source_document_from_project(project, doc.id)" in source
    assert "不会删除已人工整理的引用记录" in source
    assert "project.source_documents" in delete_source
    assert "project.evidence_chunks" in delete_source
    assert "document_id" in delete_source


def test_delete_citation_from_project_removes_only_selected_reference() -> None:
    """引用删除 helper 只移除目标引用，不影响其他引用。"""
    project = ProjectKnowledgeBase(project_name="delete_citation", title="引用删除测试")
    project.citations = [
        Citation(id="ref_keep", formatted_ref="保留引用", status="verified"),
        Citation(id="ref_delete", formatted_ref="删除引用", status="verified"),
    ]

    deleted = app._delete_citation_from_project(project, "ref_delete")

    assert deleted == 1
    assert [citation.id for citation in project.citations] == ["ref_keep"]


def test_citations_page_supports_custom_manual_reference_addition() -> None:
    """引用页应支持用户自定义添加参考文献，并默认作为未核验引用进入核验流程。"""
    source = inspect.getsource(app.render_citations_page)

    assert "自定义添加一条引用文献" in source
    assert "custom_citation_add_form" in source
    assert "添加自定义引用" in source
    assert "GB/T 7714 格式参考文献" in source
    assert "manual_custom_citation" in source
    assert 'status="unverified"' in source
    assert "confidence=0.0" in source
    assert "project.add_citation(citation)" in source
    assert "已添加自定义引用，并标记为未核验" in source


def test_citations_page_supports_viewing_and_deleting_references() -> None:
    """引用页应像资料页一样提供查看、删除、添加的管理入口。"""
    source = inspect.getsource(app.render_citations_page)
    delete_source = inspect.getsource(app._delete_citation_from_project)

    assert "### 引用记录管理" in source
    assert "查看引用详情" in source
    assert "删除引用" in source
    assert "_delete_citation_from_project(project, citation_id)" in source
    assert "OpenAlex 导入记录默认显示为已核验" in source
    assert "project.citations" in delete_source
    assert "citation_id" in delete_source


def test_sources_page_major_material_sections_default_collapsed() -> None:
    """资料库主要分类默认折叠，且不再暴露独立 AI 文献核查闭环。"""
    source = inspect.getsource(app.render_sources_page)

    assert 'AI 资料助手：生成检索词 → 整理结果 → 缺口分析 → AI/Tavily/百度检索入库 → 全资料库头脑风暴", expanded=False' in source
    assert 'OpenAlex 学术文献自动检索与引用生成", expanded=False' in source
    assert 'AI 文献核查闭环：按大纲检索 / 二次审核真实性 / 加入资料库"' not in source
    assert '搜索 API 配置（Tavily 优先 / 百度网页搜索兜底，密钥仅保存在当前会话或 .env）"' not in source
    assert 'outline_tavily_search_btn' not in source
    assert 'expanded=True' not in source[source.index('AI 资料助手：'):source.index('OpenAlex 学术文献自动检索')]



def test_model_provider_guidance_explains_required_fields_and_links() -> None:
    """选择模型平台时应提示密钥、模型名、API Base 和注意事项。"""
    openai_guidance = app._model_provider_guidance("openai", "gpt-5.5")
    assert "API Key" in openai_guidance["required"]
    assert "platform.openai.com" in openai_guidance["key_url"]
    assert "gpt-5.5" in openai_guidance["current_model"]
    assert any("API Base" in note for note in openai_guidance["notes"])

    custom_guidance = app._model_provider_guidance("custom", "gpt-5.5")
    assert "API Base" in custom_guidance["required"]
    assert "chat/completions" in " ".join(custom_guidance["notes"])


def test_sources_ai_result_persists_as_internal_source_and_evidence() -> None:
    """资料助手输出应保存为内部资料和证据片段，供大纲/正文参考但不冒充真实引用。"""
    project = app.ProjectKnowledgeBase(
        project_name="sources_ai_persist",
        title="智慧工地建设与工程现场数字化管理",
        description="围绕工程现场数字化管理展开。",
    )

    document, chunk = app._persist_sources_ai_result(
        project,
        "生成检索词",
        "中文检索式：智慧工地 AND 数字化管理\n英文检索式：smart construction site digital management",
        "生成可执行检索词",
        "项目上下文",
    )

    assert document.id == "sources_ai_search_terms"
    assert chunk.id == "sources_ai_search_terms_chunk"
    assert document.source_type == "ai_assistant"
    assert document.metadata["verification_status"] == "ai_analysis_not_verified_citation"
    assert document.metadata["can_use_for_outline"] is True
    assert project.source_documents[0].id == document.id
    assert project.evidence_chunks[0].document_id == document.id
    assert "智慧工地" in project.evidence_chunks[0].text


def test_sources_ai_brainstorm_updates_outline_context_and_uses_compact_tokens() -> None:
    """大纲前头脑风暴既进入资料库，也同步为后续大纲生成依据，并降低长输出卡死风险。"""
    project = app.ProjectKnowledgeBase(
        project_name="sources_ai_brainstorm",
        title="智慧工地建设与工程现场数字化管理",
    )

    app._persist_sources_ai_result(project, "大纲前头脑风暴", "核心问题：数据治理如何支撑施工现场协同。")

    assert project.outline_brainstorm.startswith("核心问题")
    assert app._outline_brainstorm_context(project).startswith("核心问题")
    assert app._sources_ai_result_ids("大纲前头脑风暴") == ("sources_ai_outline_brainstorm", "sources_ai_outline_brainstorm_chunk")
    assert app._sources_ai_max_tokens("大纲前头脑风暴") < 7000


def test_sources_ai_workflow_keeps_records_visible_and_ordered() -> None:
    """资料助手应按大纲前资料流程保留全部步骤记录，而不是只显示当前任务。"""
    project = app.ProjectKnowledgeBase(
        project_name="sources_ai_workflow",
        title="智慧工地建设与工程现场数字化管理",
    )

    app._persist_sources_ai_result(project, "生成检索词", "中文检索式：智慧工地 数字化管理")
    app._persist_sources_ai_result(project, "分析资料缺口", "#### 资料状态\n- 可支撑：主题方向。\n- 不可直接支撑：政策演进和行业数据。")
    app._persist_sources_ai_result(project, "AI检索资料入库", "检索结果：应补充施工现场数据治理框架。")

    task_names = [step["task"] for step in app.SOURCES_AI_WORKFLOW_TASKS]
    workflow_context = app._sources_ai_workflow_context(project)

    assert task_names == ["生成检索词", "整理检索结果", "分析资料缺口", "AI检索资料入库", "资料库头脑风暴"]
    assert "根据上传资料写作" not in task_names
    assert "AI补充资料入库" not in task_names
    assert "【1. 生成检索词】" in workflow_context
    assert "【3. 结合检索结果与大纲分析资料缺口】" in workflow_context
    assert "【4. AI检索资料并保存到资料库】" in workflow_context
    assert app._sources_ai_result_ids("AI检索资料入库") == ("sources_ai_supplemental_sources", "sources_ai_supplemental_sources_chunk")


def test_sources_ai_search_fallback_fetches_and_ai_screens_before_import(monkeypatch) -> None:
    """百度/API 只返回标题链接时，应先打开网页并经 AI 筛选后再保存到资料库。"""
    project = app.ProjectKnowledgeBase(
        project_name="sources_ai_fallback",
        title="智慧工地建设与工程现场数字化管理",
        outline="第一章 智慧工地建设背景\n一、政策牵引",
    )

    class FakeLiteratureService:
        def outline_search_queries(self, project, max_queries=6):
            return ["智慧工地 政策依据"]

        def web_search(self, query, **kwargs):
            return {
                "items": [
                    {"title": "住房城乡建设领域数字化政策", "url": "https://example.com/policy", "page": 1, "provider": "baidu_search_api", "raw": {"source": "example"}}
                ],
                "pages": [{"page": 1, "code": 200, "msg": "", "count": 1}],
                "count": 1,
            }

        def fetch_web_page_text(self, url, **kwargs):
            return {
                "ok": True,
                "url": url,
                "final_url": "https://gov.example.com/policy",
                "status_code": 200,
                "content_type": "text/html; charset=utf-8",
                "text": "住房城乡建设领域数字化转型政策要求推动智慧工地建设，强化工程现场数据治理、质量安全监管和建筑业数字化协同。" * 5,
            }

    class FakeLLM:
        def generate_content(self, prompt, **kwargs):
            assert "已经打开链接后抽取的网页正文" in prompt
            assert "住房城乡建设领域数字化转型政策" in prompt
            return "保留：是\n可信度：中\n可支撑章节：第一章 政策牵引\n入库标题：住房城乡建设领域数字化政策\n摘要：该网页可支撑智慧工地政策背景。\n证据片段：推动智慧工地建设，强化工程现场数据治理。\n风险：需人工核验发布机构和发布时间。"

    message = app._run_sources_ai_gap_search(
        project,
        "下一步补检词：智慧工地 政策依据",
        literature_service=FakeLiteratureService(),
        web_search_id="10016362",
        web_search_key="secret",
        client=FakeLLM(),
    )

    assert "百度/API 1 组" in message
    assert "获得 1 条标题/链接候选" in message
    assert "最终保存 1 条资料来源" in message
    assert project.source_documents[0].source_type == "web_page_ai_screened"
    assert project.source_documents[0].metadata["origin"] == "sources_ai_search_screened"
    assert project.source_documents[0].metadata["verification_status"] == "ai_screened_web_page_pending_human_verification"
    assert project.source_documents[0].url == "https://gov.example.com/policy"
    assert project.evidence_chunks[0].document_id == project.source_documents[0].id
    assert "推动智慧工地建设" in project.evidence_chunks[0].text
    assert "AI筛选结果" in project.evidence_chunks[0].text


def test_sources_ai_search_prefers_tavily_and_screens_before_import() -> None:
    """配置 Tavily 后，资料助手应优先走 Tavily，并仍然执行打开网页 + AI筛选 + 入库。"""
    project = app.ProjectKnowledgeBase(
        project_name="sources_ai_tavily",
        title="智慧工地建设与工程现场数字化管理",
        outline="第一章 智慧工地建设背景\n一、行业数据",
    )

    class FakeLiteratureService:
        def outline_search_queries(self, project, max_queries=6):
            return ["智慧工地 行业数据"]

        def tavily_search(self, query, **kwargs):
            assert kwargs["api_key"] == "tvly-test"
            return {
                "items": [
                    {"title": "智慧工地行业发展报告", "url": "https://example.com/report", "page": 1, "provider": "tavily", "raw": {"score": 0.91}}
                ],
                "pages": [{"page": 1, "code": 200, "msg": "Tavily search completed", "count": 1}],
                "count": 1,
                "provider": "tavily",
            }

        def web_search(self, query, **kwargs):
            raise AssertionError("Tavily 有结果时不应调用百度兜底")

        def fetch_web_page_text(self, url, **kwargs):
            return {
                "ok": True,
                "url": url,
                "final_url": "https://industry.example.com/report",
                "status_code": 200,
                "content_type": "text/html; charset=utf-8",
                "text": "智慧工地行业发展报告显示，施工现场数字化、物联网感知、质量安全数据治理正在成为建筑业转型重点。" * 5,
            }

    class FakeLLM:
        def generate_content(self, prompt, **kwargs):
            assert "智慧工地行业发展报告" in prompt
            return "保留：是\n可信度：中\n可支撑章节：第一章 行业数据\n入库标题：智慧工地行业发展报告\n摘要：该报告可支撑行业发展与数据治理背景。\n证据片段：施工现场数字化、物联网感知、质量安全数据治理成为重点。\n风险：需人工核验发布机构。"

    message = app._run_sources_ai_gap_search(
        project,
        "下一步补检词：智慧工地 行业数据",
        literature_service=FakeLiteratureService(),
        tavily_api_key="tvly-test",
        web_search_id="10016362",
        web_search_key="secret",
        client=FakeLLM(),
    )

    assert "Tavily 1 组" in message
    assert "最终保存 1 条资料来源" in message
    assert project.source_documents[0].metadata["external_provider"] == "tavily"
    assert project.source_documents[0].url == "https://industry.example.com/report"
    assert "AI筛选结果" in project.evidence_chunks[0].text


def test_sources_ai_search_fallback_does_not_import_api_error_or_rejected_page() -> None:
    """搜索 API 失败或 AI 明确剔除时，不应把标题/URL 当成证据直接入库。"""
    project = app.ProjectKnowledgeBase(project_name="sources_ai_reject", title="接口盒子无关测试")

    class FakeLiteratureService:
        def outline_search_queries(self, project, max_queries=6):
            return ["接口盒子"]

        def web_search(self, query, **kwargs):
            return {
                "items": [
                    {"title": "hdmi接口盒批发", "url": "https://example.com/shop", "page": 1, "provider": "baidu_search_api", "raw": {}}
                ],
                "pages": [{"page": 1, "code": 400, "msg": "查询失败，请重试。", "count": 0}],
                "count": 1,
            }

        def fetch_web_page_text(self, url, **kwargs):
            return {"ok": True, "url": url, "final_url": url, "status_code": 200, "content_type": "text/html", "text": "HDMI接口盒商品批发促销价格产地货源" * 10}

    class RejectLLM:
        def generate_content(self, prompt, **kwargs):
            return "保留：否\n可信度：低\n可支撑章节：无\n摘要：商品页，与项目资料缺口无关。\n风险：广告页。"

    message = app._run_sources_ai_gap_search(
        project,
        "下一步补检词：接口盒子",
        literature_service=FakeLiteratureService(),
        web_search_id="10016362",
        web_search_key="secret",
        client=RejectLLM(),
    )

    assert "查询失败，请重试" in message
    assert "最终保存 0 条资料来源" in message
    assert project.source_documents == []
    assert project.evidence_chunks == []


def test_sources_ai_detects_model_search_unsupported_and_brainstorm_gap_markers() -> None:
    """资料助手需要识别模型无搜索能力，并在头脑风暴仍缺资料时触发补检。"""
    assert app._sources_ai_model_search_unsupported("当前模型不支持联网搜索，请提供资料。") is True
    assert app._sources_ai_model_search_unsupported("已搜索到政策文件和行业报告。") is False
    assert app._sources_ai_needs_more_sources("不可直接支撑：政策依据、发展历程、行业数据，需要补充资料。") is True
    assert app._sources_ai_result_ids("资料库头脑风暴") == ("sources_ai_outline_brainstorm", "sources_ai_outline_brainstorm_chunk")


# ── 资料页指标按钮可点击跳转 ──────────────────────────────────────────


def test_sources_page_metric_buttons_are_clickable_for_management() -> None:
    """资料页顶部的四个指标卡片应为按钮，点击后可跳转到对应管理区或引用页。"""
    source = inspect.getsource(app.render_sources_page)

    assert "metric_source_docs_btn" in source
    assert "metric_evidence_chunks_btn" in source
    assert "metric_citations_btn" in source
    assert "metric_unverified_btn" in source

    # "资料来源"按钮应设置 sources_focus_docs 标记（替代 broken JS scroll）
    assert "sources_focus_docs" in source

    # "证据片段"按钮应设置 sources_focus_evidence 标记
    assert "sources_focus_evidence" in source

    # "引用记录" / "未核验引用" 应跳转到 Citations 页面
    assert '"Citations"' in source

    # st.info callout 存在于对应区域（替代无效的 HTML anchor div）
    assert "sources_focus_docs_flag" in source or "sources_focus_docs" in source
    assert "sources_focus_evidence_flag" in source or "sources_focus_evidence" in source

    # 证据片段删除功能已接入
    assert "delete_evidence_chunk_" in source or "_delete_evidence_chunk_from_project" in source


# ── 项目导入/导出/删除 helper ──────────────────────────────────────────


def test_safe_project_import_name_normalizes_input() -> None:
    """导入项目名应清理为安全的目录名。"""
    assert app._safe_project_import_name("智慧工地 建设") == "智慧工地_建设"
    assert app._safe_project_import_name("  Test Project!!!  ") == "test_project"
    assert app._safe_project_import_name("") == "imported_project"
    assert app._safe_project_import_name(None) == "imported_project"
    assert app._safe_project_import_name("abc/../def") == "abcdef"


def test_unique_project_dir_avoids_collision(tmp_path) -> None:
    """当同名目录已存在时，应生成带后缀的唯一目录。"""
    desired = "智慧工地"
    base = tmp_path / "projects"
    base.mkdir()

    first = app._unique_project_dir(base, desired)
    assert first.name == "智慧工地"
    first.mkdir()

    second = app._unique_project_dir(base, desired)
    assert second.name == "智慧工地_2"
    second.mkdir()

    third = app._unique_project_dir(base, desired)
    assert third.name == "智慧工地_3"


def test_build_and_import_project_zip_roundtrip(tmp_path) -> None:
    """导出项目 zip 再导入应可恢复 knowledge_base.json。"""
    project_dir = tmp_path / "智慧工地"
    project_dir.mkdir()
    kb_path = project_dir / "knowledge_base.json"
    data = {
        "project_name": "智慧工地",
        "project_dir": str(project_dir),
        "title": "智慧工地建设",
        "category": "工程管理",
        "updated_at": datetime.now().isoformat(),
    }
    kb_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    # 导出
    export_bytes = app._build_project_export_zip(str(kb_path))
    assert len(export_bytes) > 0

    # 验证导出 zip 内容
    with zipfile.ZipFile(io.BytesIO(export_bytes)) as zf:
        names = zf.namelist()
        assert any(Path(name).name == "knowledge_base.json" for name in names)

    # 导入到另一个目录
    target_dir = tmp_path / "imported"
    target_dir.mkdir()
    ok, message = app._import_project_zip(io.BytesIO(export_bytes))
    assert ok, message
    assert "已导入项目" in message


def test_build_project_export_zip_raises_on_missing_file() -> None:
    """导出不存在的项目应抛出 FileNotFoundError。"""
    try:
        app._build_project_export_zip("/nonexistent/path/knowledge_base.json")
        assert False, "应该抛出异常"
    except FileNotFoundError:
        pass


def test_import_project_zip_rejects_without_knowledge_base(tmp_path) -> None:
    """不含 knowledge_base.json 的 zip 应被拒绝。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("some_file.txt", "hello")

    ok, message = app._import_project_zip(io.BytesIO(buf.getvalue()))
    assert not ok
    assert "knowledge_base.json" in message


def test_delete_project_by_path_removes_directory(tmp_path) -> None:
    """按路径删除应移除整个项目目录。"""
    project_dir = tmp_path / "test_delete"
    project_dir.mkdir()
    kb_path = project_dir / "knowledge_base.json"
    kb_path.write_text("{}", encoding="utf-8")

    assert project_dir.exists()
    result = app._delete_project_by_path(str(kb_path))
    assert result is True
    assert not project_dir.exists()


def test_delete_project_by_path_rejects_non_project_directory(tmp_path) -> None:
    """非项目目录不应被误删。"""
    project_dir = tmp_path / "not_a_project"
    project_dir.mkdir()
    (project_dir / "some_file.txt").write_text("hello")

    result = app._delete_project_by_path(str(project_dir / "some_file.txt"))
    assert result is False
    assert project_dir.exists()


def test_project_delete_password_constant_exists() -> None:
    """删除项目密码常量应为 hbj123。"""
    assert app.PROJECT_DELETE_PASSWORD == "hbj123"


def test_load_project_section_includes_import_export_delete() -> None:
    """加载已有项目页应包含导入/导出/删除入口。"""
    source = inspect.getsource(app._render_load_project_section)

    assert "### 导入项目" in source
    assert "project_import_zip" in source
    assert "导入项目" in source
    assert "st.download_button" in source
    assert "导出" in source
    assert "删除密码" in source
    assert "PROJECT_DELETE_PASSWORD" in source
    assert "_delete_project_by_path" in source
