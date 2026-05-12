from __future__ import annotations

# src/libriscribe/agents/chapter_writer.py

import logging
import re
from pathlib import Path
from typing import Optional, Dict, List, Sequence
from libriscribe.agents.agent_base import Agent
from libriscribe.utils import prompts_context as prompts
from libriscribe.utils.file_utils import read_markdown_file, read_json_file, write_markdown_file, extract_json_from_markdown
from libriscribe.knowledge_base import ProjectKnowledgeBase, Chapter, Scene, ChapterSection
from libriscribe.utils.llm_client import LLMClient
from libriscribe.utils.chinese_labels import format_chapter_label, format_outline_section_label as shared_outline_section_label
from libriscribe.utils.academic_prompt import (
    ACADEMIC_MONOGRAPH_SYSTEM_PROMPT,
    finalize_academic_chapter,
    ensure_fullwidth_indent,
)
from libriscribe.services.quality_service import QualityService

import json
from rich.console import Console

console = Console()

logger = logging.getLogger(__name__)

class ChapterWriterAgent(Agent):
    """Writes chapters."""

    def __init__(self, llm_client: LLMClient):
        super().__init__("ChapterWriterAgent", llm_client)


    def execute(
        self,
        project_knowledge_base: ProjectKnowledgeBase,
        chapter_number: int,
        output_path: Optional[str] = None,
        section_number: Optional[str] = None,
        progress_callback=None,
        content_callback=None,
        chapter_strength_prompt: str = "",
    ) -> None:
        """撰写章节。

        专著项目优先按 `Chapter.sections` 中的学术写作单元逐节生成；
        若旧项目没有 sections，则回退到原有 scene 逻辑以保持兼容。
        """
        try:
            chapter = project_knowledge_base.get_chapter(chapter_number)
            if not chapter:
                console.print(f"[red]ERROR: Chapter {chapter_number} not found in knowledge base.[/red]")
                chapter = Chapter(
                    chapter_number=chapter_number,
                    title=f"Chapter {chapter_number}",
                    summary="A new academic chapter."
                )
                project_knowledge_base.add_chapter(chapter)

            console.print("\n[cyan]Writing Chapter %d: %s[/cyan]" % (chapter_number, chapter.title or ""))

            if output_path is None:
                proj_dir = project_knowledge_base.project_dir
                if not proj_dir:
                    raise ValueError("project_dir is not set. Please save the project first.")
                output_path = str(Path(proj_dir) / f"chapter_{chapter_number}.md")

            if getattr(chapter, "sections", None):
                chapter_content = self._write_academic_chapter(
                    project_knowledge_base,
                    chapter_number,
                    chapter,
                    section_number=section_number,
                    progress_callback=progress_callback,
                    content_callback=content_callback,
                    chapter_strength_prompt=chapter_strength_prompt,
                )
            else:
                chapter_content = self._write_legacy_scene_chapter(project_knowledge_base, chapter_number, chapter)

            if not self._has_real_body_content(chapter_content):
                raise RuntimeError("模型没有返回可写入正文的有效内容，请检查模型配置、API Base 或网络状态。")

            write_markdown_file(output_path, chapter_content)
            chapter.actual_word_count = self._count_words(chapter_content)
            chapter.status = "completed"
            project_knowledge_base.chapters[chapter_number] = chapter
            console.print("[green]Chapter %d completed.[/green]" % chapter_number)

        except Exception as e:
            self.logger.exception(f"Error writing chapter {chapter_number}: {e}")
            console.print(f"[red]ERROR: Failed to write chapter {chapter_number}. See log for details.[/red]")
            raise

    @staticmethod
    def format_outline_section_label(section_number: str, title: str = "") -> str:
        """把内部 1.1/1.1.1/1.1.1.1 编号统一转换为中文大纲标题。"""
        return shared_outline_section_label(section_number, title)

    @staticmethod
    def section_heading_pattern(section_number: str, section_title: str = "") -> re.Pattern:
        """匹配同一写作单元的新旧 Markdown 标题，兼容旧数字标题和新中文标题。"""
        display_title = ChapterWriterAgent.format_outline_section_label(section_number, section_title)
        legacy_title = f"{section_number} {section_title}".strip()
        alternatives = {re.escape(section_number), re.escape(legacy_title), re.escape(display_title)}
        return re.compile(r"^(#{2,6})\s+(?:" + "|".join(sorted(alternatives, key=len, reverse=True)) + r")(?:\s|$)")

    @staticmethod
    def distribute_word_targets(section_titles: Sequence[str], total_words: int) -> List[int]:
        """按标题语义节奏分配目标字数，避免各小节机械平均。"""
        titles = [str(title or "") for title in section_titles]
        if not titles:
            return []
        total = max(0, int(total_words or 0))
        if total <= 0:
            return [0 for _ in titles]

        coefficient_groups = [
            (("小结", "结语", "总结", "启示", "展望"), 0.62),
            (("概念", "内涵", "界定", "含义", "概述", "定义"), 0.78),
            (("背景", "现状", "趋势", "基础", "特征"), 0.92),
            (("类型", "分类", "构成", "要素", "框架"), 1.05),
            (("问题", "困境", "矛盾", "风险", "挑战", "瓶颈", "原因"), 1.28),
            (("机制", "逻辑", "关系", "影响", "作用", "机理"), 1.38),
            (("路径", "策略", "优化", "模型", "实践", "治理", "建设", "应用", "方案", "转化"), 1.48),
        ]
        coefficients: List[float] = []
        for title in titles:
            coefficient = 1.0
            for keywords, value in coefficient_groups:
                if any(keyword in title for keyword in keywords):
                    coefficient = value
                    break
            coefficients.append(coefficient)

        coefficient_sum = sum(coefficients) or float(len(titles))
        raw_targets = [total * coefficient / coefficient_sum for coefficient in coefficients]
        targets = [max(1, int(round(value))) for value in raw_targets]
        delta = total - sum(targets)
        if delta:
            order = sorted(range(len(targets)), key=lambda idx: coefficients[idx], reverse=delta > 0)
            step = 1 if delta > 0 else -1
            for idx in order:
                if delta == 0:
                    break
                if step < 0 and targets[idx] <= 1:
                    continue
                targets[idx] += step
                delta -= step
        return targets

    def _write_academic_chapter(
        self,
        project_knowledge_base: ProjectKnowledgeBase,
        chapter_number: int,
        chapter: Chapter,
        section_number: Optional[str] = None,
        progress_callback=None,
        content_callback=None,
        chapter_strength_prompt: str = "",
    ) -> str:
        """按四级目录写作单元生成学术专著章节；传入 section_number 时仅生成指定小节。

        有子节的小节（如 1.1 有 1.1.1/1.1.2 子节）只输出标题作为结构标记，
        不单独生成内容；只有叶子节点（最深层无子节的小节）才调用 AI 生成正文。
        """
        all_sections = sorted(chapter.sections, key=lambda s: [int(p) if p.isdigit() else 0 for p in s.section_number.split('.')])

        # 判断哪些小节是叶子节点（没有子节的最深层小节）
        section_numbers = {sec.section_number for sec in all_sections}
        def _is_leaf(sec):
            """检查小节是否为叶子节点：没有其他小节的编号以它为前缀。"""
            sn = sec.section_number
            for other_sn in section_numbers:
                if other_sn != sn and other_sn.startswith(sn + "."):
                    return False
            return True

        leaf_sections = [sec for sec in all_sections if _is_leaf(sec)]

        # 指定小节生成时：只允许叶子节点
        if section_number:
            ordered_sections = [sec for sec in all_sections if sec.section_number == section_number]
            if not ordered_sections:
                raise ValueError(f"Section {section_number} not found in chapter {chapter_number}.")
            # 如果指定的是非叶子节点，自动改为生成其所有叶子子节
            if not _is_leaf(ordered_sections[0]):
                target_prefix = section_number + "."
                ordered_sections = [sec for sec in leaf_sections if sec.section_number.startswith(target_prefix)]
                if not ordered_sections:
                    # 没有叶子子节，只输出标题
                    ordered_sections = []
        else:
            # 全章生成：只生成叶子节点，非叶子节点只输出标题
            ordered_sections = leaf_sections

        terminology = project_knowledge_base.get_terminology_context()
        previous_summaries = project_knowledge_base.get_previous_summaries(chapter_number)
        outline_tree = "\n".join(
            f"{'  ' * (max(getattr(sec, 'level', 1) - 1, 0))}- {self.format_outline_section_label(sec.section_number, sec.title)}"
            for sec in all_sections
        )

        # 只把章标题写入正文。章摘要、大纲树和“写作思路”只作为模型写作计划上下文，
        # 不再以“本章导语”等形式直接拼进正文，避免预览/导出泄漏规划文本。
        content_parts = [f"# {format_chapter_label(chapter_number, chapter.title)}".strip(), ""]
        generated_summaries = []
        target_numbers = {sec.section_number for sec in ordered_sections}
        target_total_words = (
            int(getattr(chapter, "word_count", 0) or 0)
            or sum(int(getattr(sec, "word_count", 0) or 0) for sec in ordered_sections)
            or max(800 * max(len(ordered_sections), 1), 4000)
        )
        rhythm_targets = self.distribute_word_targets(
            [self.format_outline_section_label(sec.section_number, sec.title) for sec in ordered_sections],
            target_total_words,
        )
        rhythm_target_by_number = {sec.section_number: rhythm_targets[idx] for idx, sec in enumerate(ordered_sections) if idx < len(rhythm_targets)}
        generated_index = 0

        # 按目录顺序输出：结构标题 -> 其下叶子小节正文，避免把 1.1/1.2/1.3 标题集中堆在前面。
        for section in all_sections:
            level = max(1, min(getattr(section, "level", 1), 3))
            markdown_level = "#" * (level + 1)
            section_title = self.format_outline_section_label(section.section_number, section.title)

            if not _is_leaf(section):
                if not section_number or section.section_number == section_number or section.section_number.startswith((section_number or "") + ".") or (section_number and section_number.startswith(section.section_number + ".")):
                    content_parts.append(f"{markdown_level} {section_title}\n")
                continue

            if section.section_number not in target_numbers:
                continue

            generated_index += 1
            target_words = rhythm_target_by_number.get(section.section_number) or getattr(section, "word_count", 0) or max(800, int((getattr(chapter, "word_count", 0) or 4000) / max(len(ordered_sections), 1)))
            console.print("[cyan]Writing academic section %d/%d: %s[/cyan]" % (generated_index, len(ordered_sections), section_title))

            rag_context = self._get_rag_context(
                getattr(section, 'rag_query', '') or section.title or section_title,
                project=project_knowledge_base,
            )
            prompt = self._build_academic_section_prompt(
                project=project_knowledge_base,
                chapter=chapter,
                chapter_number=chapter_number,
                section=section,
                section_title=section_title,
                target_words=target_words,
                outline_tree=outline_tree,
                terminology=terminology,
                previous_summaries=previous_summaries,
                rag_context=rag_context,
                generated_summaries="\n".join(generated_summaries[-3:]),
                chapter_strength_prompt=chapter_strength_prompt,
            )
            if progress_callback:
                progress_callback(generated_index, len(ordered_sections), section_title, "start")

            target_min = max(1, int(target_words * 0.90))
            target_max = max(target_min + 1, int(target_words * 1.10))
            # 不再对已生成正文做强制裁剪；为避免“一写多”时因输出预算不足造成断尾，
            # 这里给足生成预算，长度只通过提示词引导，不通过删除正文来收口。
            max_tokens = max(1800, min(16000, int(target_words * 3.0)))
            section_content = self._generate_section_with_retries(
                prompt=prompt,
                section_title=section_title,
                target_words=target_words,
                max_tokens=max_tokens,
                content_callback=content_callback,
                progress_callback=progress_callback,
                generated_index=generated_index,
                total_sections=len(ordered_sections),
            )

            section_content = self._strip_duplicate_heading(self._sanitize_model_output(section_content, section_title), section_title)
            if not section_content:
                section.actual_word_count = 0
                section.status = "failed"
                if progress_callback:
                    progress_callback(generated_index, len(ordered_sections), section_title, "failed_final")
                raise RuntimeError(
                    f"小节 {section_title} 连续重试后仍未获得有效正文。"
                    "请检查当前模型是否拦截长提示、是否支持较大 max_tokens，或降低该小节目标字数后重试。"
                )

            section_content = self.check_and_rewrite_quotes(
                section_content,
                section_title=section_title,
                target_words=target_words,
                content_callback=content_callback,
                generated_index=generated_index,
                total_sections=len(ordered_sections),
            )
            section_content = self.check_and_rewrite_language_norms(
                section_content,
                section_title=section_title,
                target_words=target_words,
                content_callback=content_callback,
                generated_index=generated_index,
                total_sections=len(ordered_sections),
            )
            section_content = self._repair_word_count_loop(
                content=section_content,
                prompt=prompt,
                section_title=section_title,
                target_words=target_words,
                content_callback=content_callback,
                generated_index=generated_index,
                total_sections=len(ordered_sections),
            )
            section_content = self._quality_gate_section_content(
                project=project_knowledge_base,
                prompt=prompt,
                section_title=section_title,
                content=section_content,
                target_words=target_words,
                content_callback=content_callback,
                generated_index=generated_index,
                total_sections=len(ordered_sections),
            )
            section_content = self.check_and_rewrite_quotes(
                section_content,
                section_title=section_title,
                target_words=target_words,
                content_callback=content_callback,
                generated_index=generated_index,
                total_sections=len(ordered_sections),
            )
            section_content = self.check_and_rewrite_language_norms(
                section_content,
                section_title=section_title,
                target_words=target_words,
                content_callback=content_callback,
                generated_index=generated_index,
                total_sections=len(ordered_sections),
            )
            section_content = self._repair_word_count_loop(
                content=section_content,
                prompt=prompt,
                section_title=section_title,
                target_words=target_words,
                content_callback=content_callback,
                generated_index=generated_index,
                total_sections=len(ordered_sections),
            )
            section_content = self._complete_truncated_tail(
                content=section_content,
                prompt=prompt,
                section_title=section_title,
                target_words=target_words,
                content_callback=content_callback,
                generated_index=generated_index,
                total_sections=len(ordered_sections),
            )
            section_content = self._finalize_section_content(section_content, section_title, target_words)
            actual_words = self._count_words(section_content)
            section.actual_word_count = actual_words
            section.status = "completed"
            generated_summaries.append(f"{section_title}: {section_content[:240]}")
            content_parts.append(f"{markdown_level} {section_title}\n\n{section_content.strip()}\n")
            if content_callback:
                content_callback(section_content, section_title, generated_index, len(ordered_sections))
            if progress_callback:
                progress_callback(generated_index, len(ordered_sections), section_title, "completed")

        if not section_number:
            chapter.sections = all_sections
            content_parts.extend(["", self._build_chapter_back_matter(project_knowledge_base, chapter, chapter_number, content_parts, terminology)])
        else:
            updated = {sec.section_number: sec for sec in ordered_sections}
            chapter.sections = [updated.get(sec.section_number, sec) for sec in all_sections]
        chapter_text = "\n".join(content_parts).strip() + "\n"
        if not section_number:
            target_words = getattr(chapter, "word_count", 0) or sum(getattr(sec, "word_count", 0) or 0 for sec in getattr(chapter, "sections", []))
            chapter_text, score_total, verdict = finalize_academic_chapter(chapter_text, target_words=target_words)
            if score_total < 40:
                self.logger.warning("Chapter %s self-assessment below 80 (%s/50): %s. Applying deterministic formatting rewrite once.", chapter_number, score_total, verdict)
                chapter_text, _, _ = finalize_academic_chapter(ensure_fullwidth_indent(chapter_text), target_words=target_words)
        else:
            chapter_text = ensure_fullwidth_indent(chapter_text)
        return chapter_text

    def _build_academic_section_prompt(
        self,
        project: ProjectKnowledgeBase,
        chapter: Chapter,
        chapter_number: int,
        section,
        section_title: str,
        target_words: int,
        outline_tree: str,
        terminology: str,
        previous_summaries: str,
        rag_context: str,
        generated_summaries: str,
        chapter_strength_prompt: str = "",
    ) -> str:
        from libriscribe.services.prompt_service import PromptService

        template = PromptService.load_chapter_prompt()
        section_level = getattr(section, 'level', 1)
        section_goal = getattr(section, 'summary', '') or section_title
        paragraph_rule = (
            "分段必须服从语义转折，而不是服从字数平均；只有当论证从概念界定转入机制分析、"
            "从问题诊断转入路径讨论、从一般判断转入边界/风险时才分段。每个自然段至少包含5个完整句子；"
            "无法保证每段5句以上时宁可保留1段，不要为了形式整齐强行分段，也不要让各段长度看起来平均。"
        )
        strength_prompt = str(chapter_strength_prompt or "").strip()
        strength_rule = (
            "暂无。"
            if not strength_prompt
            else (
                "以下为用户对本章的自定义强化要求，写作时应优先体现在论证角度、材料取舍、表达风格和案例侧重中；"
                "但不得覆盖证据绑定规则、正文输出边界、语言规范、反幻觉规则和当前小节写作思路。\n"
                f"{strength_prompt}"
            )
        )
        section_details = (
            f"小节标题：{section_title}\n"
            f"目录层级：{section_level}\n"
            f"写作思路（最高优先级，只围绕它写，不自行扩展新分论点）：{section_goal}\n"
            f"本章强化提示词：{strength_rule}\n"
            f"系统篇幅目标：约 {target_words} 字（仅供创作方向参考；不要在正文中统计、说明或自评字数）\n"
            f"段落行为：{paragraph_rule}"
        )
        values = {
            "book_title": project.title,
            "genre": project.genre,
            "category": project.category,
            "language": project.language,
            "target_audience": project.target_audience,
            "description": project.description,
            "chapter_number": chapter_number,
            "chapter_title": chapter.title,
            "chapter_outline": chapter.summary,
            "section_title": section_title,
            "section_level": section_level,
            "section_goal": section_goal,
            "section_details": section_details,
            "target_words": target_words,
            "outline_tree": outline_tree,
            "previous_summaries": previous_summaries or '暂无',
            "generated_summaries": generated_summaries or '暂无',
            "terminology_context": terminology or '暂无',
            "rag_context": rag_context or '暂无可用参考资料。若无资料，请基于通用学术知识谨慎写作，不编造具体数据来源。',
        }
        chapter_strength_rules = f"""## 本章强化提示词（用户自定义，单章生成前填写）
{strength_rule}

强制边界：本章强化提示词只能强化当前章的写作重点、场景侧重、论证口径和表达风格；不得要求编造资料、扩大当前小节边界、输出过程说明、改变语言规范或违反正文纯输出边界。
"""
        evidence_rules = f"""## 证据绑定规则（专著强制）
1. 关键事实句必须优先依托“可用参考资料/RAG 上下文”中的 [来源: ...] 信息，包括年份、比例、标准编号、政策名称、机构报告、案例结论和技术指标。
2. 只有在上下文或项目引用中能找到依据时，才可写成确定性事实；建议在事实句后用“资料来源：...”或括号说明来源名称，不要编造 [数字] 引用。
3. 如果资料中没有依据，不得编造作者、年份、书名、论文名、报告名、法规标准编号、百分比、统计数据或参考文献条目。
4. 资料不足但必须讨论时，改写为审慎分析、条件判断或一般性机制阐释；禁止输出“【信息缺失】需要补充……”“待确认”“TODO”等内部补缺标记。
5. 不要把不存在于项目 citations 或 RAG 上下文中的文献写成参考文献；引用和资料来源必须可追溯。

## 正文输出边界（强制） / 正文纯输出边界（最高优先级）
1. 你的全部输出必须是且仅是当前写作单元正文；如果当前任务是整章生成，正文从章节标题开始，到该章最后一句话结束。
2. 禁止输出任何关于生成过程的说明，包括字数统计、目标字数、偏差率、自评结果、评分、打分表、质量检查、人工审核提示、重写说明、模型说明。
3. 禁止输出任何内部协作标记或占位符，包括“[此处需要补充]”“【信息缺失】”“待确认”“TODO”“FIXME”“后续补充建议”。
4. 禁止在正文之前、之后或中间插入前缀、后缀、分隔线、标记线、说明性括号、代码块围栏或任何非正文信息。
5. 除非当前标题明确要求，禁止输出“本章小结”之外的前情回顾或下章预告；不得写“以上讨论了……接下来……”。
6. 章摘要、全章目录树、写作目标、写作思路、资料依据、证据边界、后续补充建议都属于内部写作计划，只能用于理解任务，严禁原样输出到正文。
7. 只输出当前写作单元正文段落，不输出“本章导语：”“写作思路：”“资料依据：”“证据边界：”“后续需补充：”等规划标签。
8. 输出前必须自行检查并删除所有与正文无关的句子、数字、评分、标志和提示；宁可正文偏短，也不得添加任何非正文内容。
9. 写作必须优先服从“小节写作思路/写作目标”：只完成该思路要求的核心论证，不擅自扩展案例、背景、意义、对策或下一层分论点。
10. 篇幅目标只作为创作方向，不要求你自行统计字数；绝对不得把目标字数、实际字数、偏差、自评或过程说明写入正文。
11. 段落行为：{paragraph_rule} 不要刻意追求段落长度整齐，不要为了凑字数重复铺陈。
12. 段落内部不允许空行，只有段与段之间可以有一个空行；段首可使用“进一步看”“从实践层面”“然而”“因此”等逻辑词自然衔接。

## 去 AI 痕迹与出版级表达（强制）
1. 禁止 AI 学术膨胀词：不得使用任何形式的“不仅……而且……”，不得使用“值得注意的是”“需要强调的是”“理应指出”“某种意义上”“在一定程度上”“大致而言”“提供了有益的尝试”“进行了深入的探讨”。如果判断有边界，直接说明边界，不用模糊套语缓冲。
2. 少用双引号，普通判断句和概念直接陈述，不加引号。只在直接转述他人原话、术语首次界定或特殊含义临时用法时使用双引号。
3. 语言规范必须严格执行：表达拟定计划、办法、方案时使用“制订”，不使用“制定”；表达做出加名词结构时使用“做出”，不使用“作出”；描述水平、程度、质量的提高时使用“提高”，不使用“提升”；谨慎使用“而”“且”“并”“以及”等连接词，能用句号断开时不硬串长句；“应”“可”“需”必须区分义务、许可和必要条件，不混用、不堆砌。
4. 定义必须带立场：不要用通用释义替代论证起点，应说明本书采用某一概念的具体意义、边界及其区别对象。
5. 判断句要短而明确，分析句可以较长，但必须有因果递进，不堆砌平行概念。
6. 取消空泛过渡段：禁止写“以上讨论了A，接下来我们将转向B”。章节或小节衔接要使用问题递进、条件限制、实践矛盾或论证转折。
7. 对既有研究或常见观点的批评必须有实质理由，不用缓冲性套话替代判断；没有资料依据时，不要虚构具体研究者或文献。
8. 禁止“综上所述”式总结：章末或节末应基于前文提出推论、限制或下一层级问题，而不是缩编复述。
9. 语言接近真实研究者或专业作者的自然表达，避免“首先、其次、最后”“总之”“毫无疑问”“一般来说”等模板化连接；少写姿态化结论，多写具体对象、具体关系和具体作用路径。
10. 绝对禁止在输出正文中附带任何字数统计、自评、评分、检查过程或改写说明。"""
        try:
            user_prompt = template.format(**values)
        except KeyError as exc:
            missing = exc.args[0]
            raise ValueError(f"全局章节提示词缺少或写错变量：{{{missing}}}。请从左上角“好编辑”隐藏入口进入全局设置，恢复默认或修正提示词变量。") from exc
        return f"{ACADEMIC_MONOGRAPH_SYSTEM_PROMPT}\n\n{chapter_strength_rules}\n\n{evidence_rules}\n\n{user_prompt}"

    def _build_chapter_intro(self, project: ProjectKnowledgeBase, chapter: Chapter, chapter_number: int, outline_tree: str) -> str:
        """生成稳定的章首导语，避免额外 LLM 调用导致无反馈或污染正文。"""
        summary = (chapter.summary or "").strip()
        if summary:
            base = summary
        else:
            base = f"本章围绕{chapter.title}展开，依据章节目录依次讨论相关概念、技术脉络、应用场景与实践问题。"
        return (
            f"本章导语：{base} 本章按照{format_chapter_label(chapter_number)}的目录结构展开论述，先界定核心概念与问题边界，"
            "再结合相关研究资料、行业实践和技术演进进行分析。"
            "全文保持中立、客观、可出版的学术专著表达方式，避免主观化和口语化表述。"
        )

    def _build_chapter_back_matter(self, project: ProjectKnowledgeBase, chapter: Chapter, chapter_number: int, content_parts: List[str], terminology: str) -> str:
        """生成章末结构：普通章仅本章小结；末章追加全书参考文献与术语表附录。"""
        summary_block = (
            "## 本章小结\n\n"
            f"本章围绕{chapter.title}展开系统论述，按照既定目录完成了核心概念、关键问题、技术路径和应用价值的分析。"
            "本章内容在结构上紧扣当前章节主题，在材料使用上强调术语一致、证据审慎和观点中立。"
            "本章小结仅概括本章已经完成的论述内容，不对后续章节作预告。"
        )
        if not self._is_final_chapter(project, chapter_number):
            return summary_block

        refs = self._build_reference_list(project, chapter, include_all=True)
        reference_block = "## 全书参考文献\n\n" + ("\n".join(refs) if refs else "（全书暂无参考文献）")
        terms = self._extract_terms_for_glossary(chapter, terminology, project=project, include_all=True)
        glossary_lines = [f"- **{term}**：{definition}" for term, definition in terms]
        glossary_block = "## 附录A 术语表\n\n" + ("\n".join(glossary_lines) if glossary_lines else "（全书暂无术语表）")
        return summary_block + "\n\n" + reference_block + "\n\n" + glossary_block

    def _is_final_chapter(self, project: ProjectKnowledgeBase, chapter_number: int) -> bool:
        """根据当前项目实际章节号判定末章，允许用户后续调整总章数。"""
        try:
            chapter_numbers = [int(num) for num in project.chapters.keys()]
        except Exception:
            chapter_numbers = []
        return bool(chapter_numbers) and int(chapter_number) == max(chapter_numbers)

    def _extract_terms_for_glossary(self, chapter: Chapter, terminology: str, project: Optional[ProjectKnowledgeBase] = None, include_all: bool = False) -> List[tuple[str, str]]:
        term_map: Dict[str, str] = {}
        if project and include_all:
            for term, definition in getattr(project, "terminology", {}).items():
                clean_term = str(term).strip()
                clean_definition = str(definition).strip() or "全书统一术语，定义待在资料库中进一步完善。"
                if clean_term:
                    term_map[clean_term] = clean_definition
        if terminology:
            for line in terminology.splitlines():
                clean = re.sub(r"^[\-\*\d\.\s]+", "", line).strip()
                if not clean or clean.startswith("术语表"):
                    continue
                if ":" in clean or "：" in clean:
                    term, definition = re.split(r"[：:]", clean, maxsplit=1)
                    term = term.strip("*` ")
                    definition = definition.strip() or "项目术语表中的统一概念。"
                else:
                    term = re.split(r"[，,\s]", clean)[0].strip("*`")
                    definition = "项目术语表中的统一概念。"
                if term and term not in term_map:
                    term_map[term] = definition
        chapters = project.chapters.values() if project and include_all else [chapter]
        for ch in chapters:
            for sec in getattr(ch, "sections", []):
                title = (getattr(sec, "title", "") or "").strip()
                if title and title not in term_map:
                    term_map[title] = "本书目录中的关键议题或分析对象，用于保持全书概念和标题表述一致。"
        return list(term_map.items())[:30]

    def _build_reference_list(self, project: ProjectKnowledgeBase, chapter: Chapter, include_all: bool = False) -> List[str]:
        """只使用项目中真实存在的 citation 记录，禁止用模板伪造参考文献。"""
        refs = []
        try:
            citations = list(getattr(project, "citations", []) or []) if include_all else project.get_citations_for_chapter(getattr(chapter, "chapter_number", 0) or 0)
        except Exception:
            citations = []
        seen = set()
        for idx, citation in enumerate(citations, start=1):
            formatted = (getattr(citation, "formatted_ref", "") or "").strip()
            if formatted:
                ref_text = formatted
            else:
                source = (getattr(citation, "source", "") or "").strip()
                quote = (getattr(citation, "quote_original", "") or getattr(citation, "sentence", "") or "").strip()
                if not source and not quote:
                    continue
                ref_text = f"{source or '来源待核验'}：{quote or '原文摘录待核验'}"
            if ref_text in seen:
                continue
            seen.add(ref_text)
            refs.append(f"- [{len(refs) + 1}] {ref_text}")
        return refs

    def _get_rag_context(self, query: str, project: Optional[ProjectKnowledgeBase] = None) -> str:
        """获取章节写作参考资料。

        优先使用向量检索；如果 embedding/Chroma 不可用或无结果，则回退到项目资料库证据片段，
        确保用户上传的普通资料、文案、报告仍会进入章节提示词。
        """
        vector_context = ""
        try:
            import importlib.util
            if importlib.util.find_spec("chromadb") is None:
                self.logger.info("RAG retrieval skipped: chromadb is not installed.")
            else:
                from libriscribe.rag.retriever import Retriever
                vector_context = Retriever().get_context_for_prompt(query, top_k=4)
        except Exception as e:
            self.logger.warning("RAG retrieval skipped: %s", e)

        library_context = self._get_project_material_context(project, query=query, limit=5000, max_chunks=8)
        if vector_context and library_context:
            return f"{vector_context}\n\n## 资料库兜底片段\n{library_context}"
        return vector_context or library_context

    def _get_project_material_context(
        self,
        project: Optional[ProjectKnowledgeBase],
        query: str = "",
        limit: int = 5000,
        max_chunks: int = 8,
    ) -> str:
        """从 ProjectKnowledgeBase 中直接抽取资料库片段，作为无向量索引时的写作兜底。"""
        if project is None:
            return ""
        documents_by_id = {
            str(getattr(doc, "id", "")): doc
            for doc in (getattr(project, "source_documents", []) or [])
            if str(getattr(doc, "id", "")).strip()
        }
        query_terms = [term for term in re.split(r"[\s，,。；;：:、（）()]+", str(query or "")) if len(term) >= 2]
        scored_chunks = []
        for chunk in getattr(project, "evidence_chunks", []) or []:
            text = str(getattr(chunk, "text", "") or "").strip()
            if len(text) < 20:
                continue
            doc = documents_by_id.get(str(getattr(chunk, "document_id", "")))
            source_name = (
                getattr(doc, "file_name", "")
                or getattr(doc, "title", "")
                or getattr(chunk, "source", "")
                or "资料库片段"
            )
            score = 0
            for term in query_terms[:8]:
                if term and term in text:
                    score += 2
                if term and term in source_name:
                    score += 1
            scored_chunks.append((score, len(scored_chunks), source_name, doc, chunk, text))
        scored_chunks.sort(key=lambda item: (-item[0], item[1]))
        parts = []
        for _, _, source_name, doc, chunk, text in scored_chunks[:max_chunks]:
            source_type = getattr(doc, "source_type", "") if doc else ""
            status = getattr(doc, "status", "") if doc else ""
            parts.append(
                f"[来源: {source_name} | 类型: {source_type or 'material'} | 状态: {status or 'library'} | evidence_id={getattr(chunk, 'id', '')}]\n"
                f"{text[:1000]}"
            )
        return "\n\n".join(parts).strip()[:limit]

    def _generate_section_with_retries(
        self,
        prompt: str,
        section_title: str,
        target_words: int,
        max_tokens: int,
        content_callback=None,
        progress_callback=None,
        generated_index: int = 1,
        total_sections: int = 1,
    ) -> str:
        """小节生成的商用级容错入口：优先走稳定非流式，失败后缩短提示和 token 继续重试。"""
        attempts = []
        provider = getattr(self.llm_client, "llm_provider", "")

        # 自定义 OpenAI 兼容平台常被 SDK stream 请求头拦截；直接使用 generate_content，复用 raw HTTP 兜底。
        if provider != "custom" and hasattr(self.llm_client, "stream_content"):
            attempts.append(("stream", prompt, max_tokens, 0.65, "正在流式生成"))
        attempts.extend([
            ("generate", prompt, max_tokens, 0.60, "流式受阻，正在非流式重试"),
            ("generate", prompt, max(1800, min(max_tokens, 12000)), 0.45, "正在稳定 token 重试"),
            ("generate", self._build_compact_retry_prompt(prompt, section_title, target_words), max(1800, min(max_tokens, 10000)), 0.35, "正在使用精简提示重试"),
        ])

        last_error = ""
        for attempt_index, (mode, attempt_prompt, attempt_tokens, temperature, label) in enumerate(attempts, start=1):
            if progress_callback and attempt_index > 1:
                progress_callback(generated_index, total_sections, section_title, "retrying")
            self.logger.info(
                "Generating section %s attempt %s/%s via %s tokens=%s",
                section_title,
                attempt_index,
                len(attempts),
                mode,
                attempt_tokens,
            )
            try:
                if content_callback and attempt_index > 1:
                    content_callback(f"_{label}（第 {attempt_index}/{len(attempts)} 次）..._", section_title, generated_index, total_sections)

                if mode == "stream":
                    chunks = []
                    for chunk in self.llm_client.stream_content(attempt_prompt, max_tokens=attempt_tokens, temperature=temperature):
                        if not chunk:
                            continue
                        chunks.append(str(chunk))
                        self._emit_content_callback(
                            content_callback,
                            "".join(chunks),
                            section_title,
                            target_words,
                            generated_index,
                            total_sections,
                        )
                    content = "".join(chunks)
                else:
                    content = self.llm_client.generate_content(attempt_prompt, max_tokens=attempt_tokens, temperature=temperature)
                    if content:
                        self._emit_content_callback(
                            content_callback,
                            str(content),
                            section_title,
                            target_words,
                            generated_index,
                            total_sections,
                        )

                content = self._strip_duplicate_heading(self._sanitize_model_output(content, section_title), section_title)
                if self._has_real_body_content(content):
                    return content
                last_error = "模型返回为空或正文质量不足"
                self.logger.warning("Section %s attempt %s returned no valid body.", section_title, attempt_index)
            except Exception as e:
                last_error = str(e)
                self.logger.warning("Section %s attempt %s failed: %s", section_title, attempt_index, e)

        diagnostics = []
        if last_error:
            diagnostics.append(f"最后错误：{last_error}")
        client_error = getattr(self.llm_client, "last_error", "")
        if client_error and client_error not in last_error:
            diagnostics.append(f"客户端错误：{client_error}")
        preview = getattr(self.llm_client, "last_response_preview", "")
        if preview:
            diagnostics.append(f"响应预览：{preview[:300]}")
        self.logger.error("Section %s exhausted retries. %s", section_title, " | ".join(diagnostics))
        return ""

    def _build_compact_retry_prompt(self, original_prompt: str, section_title: str, target_words: int) -> str:
        """构造短提示，规避部分模型/中转站对超长提示或高 token 的拦截。"""
        compact_context = original_prompt[:3500]
        return f"""{ACADEMIC_MONOGRAPH_SYSTEM_PROMPT}

请为学术专著小节“{section_title}”撰写正文。篇幅目标由系统后续校验，正文中不得出现字数统计或过程说明。

可用上下文摘录：
{compact_context}

硬性要求：
1. 只输出该小节正文，不输出标题、代码块、HTML、JSON 或解释。
2. 学术专著语体，概念界定清楚，逻辑递进明确，避免编造具体数据、法规编号和虚假文献。
3. 关键事实句必须优先依托上下文中的 [来源: ...] 资料；可追溯时可用“资料来源：...”说明来源，不得编造 [数字] 引用。
4. 严禁编造作者、年份、书名、论文名、报告名、政策名称、标准编号、百分比和统计数据；没有真实来源时不得写参考文献式句子。
5. 每个自然段以两个全角空格开头；分段必须服从语义转折，每段至少5个完整句子；如果无法保证每段5句以上，宁可保留1段。不要追求段落长度整齐。
6. 少用双引号，普通判断句和概念直接陈述；禁用 AI 膨胀词：不得使用“不仅……而且……”“值得注意的是”“需要强调的是”“理应指出”“某种意义上”“在一定程度上”“大致而言”“提供了有益的尝试”“进行了深入的探讨”“综上所述”。
7. 定义必须带立场，判断句要短而明确；不要写空泛过渡段，节尾用问题递进、条件限制或实践矛盾形成自然衔接。
8. 如果资料不足，用“【信息缺失】需要您提供……”说明缺口，但仍需完成基于通用知识的审慎论述。
"""

    def _quality_gate_section_content(
        self,
        project: ProjectKnowledgeBase,
        prompt: str,
        section_title: str,
        content: str,
        target_words: int,
        content_callback=None,
        generated_index: int = 1,
        total_sections: int = 1,
    ) -> str:
        """小节写入前质量门禁：程序复评→结构化反馈给 AI→保留最高分版本。"""
        citations = getattr(project, "citations", [])
        best_content = content
        best_report = QualityService.section_quality_report(section_title, content, target_words=target_words, citations=citations)
        if bool(best_report.get("passed")):
            return content

        max_rounds = 2
        current_content = content
        for round_index in range(1, max_rounds + 1):
            issue_lines = [f"- {item}" for item in best_report.get("revision_instructions", [])[:8]]
            issue_summary = "\n".join(issue_lines) or "正文质量不足，请按证据绑定、反幻觉和出版级表达规则修订。"
            rewrite_prompt = self._build_quality_rewrite_prompt(
                prompt=prompt,
                section_title=section_title,
                content=current_content,
                target_words=target_words,
                issue_summary=issue_summary,
            )
            if content_callback:
                content_callback(f"_质量门禁发现风险，正在第 {round_index}/{max_rounds} 次定向修订并保留最佳版本..._", section_title, generated_index, total_sections)
            try:
                rewritten = self.llm_client.generate_content(
                    rewrite_prompt,
                    max_tokens=max(1800, min(14000, int(max(target_words, 600) * 3.0))),
                    temperature=0.32,
                )
                rewritten = self._strip_duplicate_heading(self._sanitize_model_output(rewritten, section_title), section_title)
                if not self._has_real_body_content(rewritten):
                    self.logger.warning("Quality rewrite round %s for section %s returned no valid body.", round_index, section_title)
                    break

                candidate_report = QualityService.section_quality_report(section_title, rewritten, target_words=target_words, citations=citations)
                if self._quality_report_rank(candidate_report) > self._quality_report_rank(best_report):
                    best_content = rewritten
                    best_report = candidate_report
                    self._emit_content_callback(content_callback, best_content, section_title, target_words, generated_index, total_sections)
                else:
                    self.logger.warning("Quality rewrite round %s for section %s did not improve report; keeping current best.", round_index, section_title)
                    break

                if bool(best_report.get("passed")):
                    break
                current_content = best_content
            except Exception as e:
                self.logger.warning("Quality gate rewrite round %s failed for section %s: %s", round_index, section_title, e)
                break
        return best_content

    @staticmethod
    def _quality_report_rank(report: Dict[str, object]) -> tuple[int, int, int, int]:
        """质量报告排序：先减少硬伤，再提高得分，再减少软警告，最后看字数接近度。"""
        hard = len(report.get("hard_failures", []) or [])
        soft = len(report.get("soft_warnings", []) or [])
        score = int(report.get("quality_score", 0) or 0)
        deviation = abs(float(report.get("word_deviation", 0.0) or 0.0))
        return (-hard, score, -soft, -int(deviation * 1000))

    def _build_quality_rewrite_prompt(
        self,
        prompt: str,
        section_title: str,
        content: str,
        target_words: int,
        issue_summary: str,
    ) -> str:
        """构造小节质量门禁的定向重写提示。"""
        return f"""{prompt}

## 质量门禁发现的问题
{issue_summary}

## 待重写正文
{content}

## 定向重写要求
请重写学术专著小节“{section_title}”。篇幅目标由系统后续校验，正文中不得出现字数统计或过程说明。
1. 只输出该小节正文，不输出标题、说明、评分、JSON、HTML、Markdown 代码块、质量报告或修订过程。
2. 必须继续遵守原始提示词中的“证据绑定规则（专著强制）”“正文输出边界（强制）”“去 AI 痕迹与出版级表达”，不得因为重写而放松原有限定。
3. 关键事实句必须依托提示词中已有的 [来源: ...]、项目 citation 或明确资料来源；没有资料依据时不得写成确定性事实。
4. 删除无法绑定真实来源的 [数字] 引用、作者年份、报告名、法规编号、政策名称、百分比和具体数据；没有证据时改写为审慎分析，或标记“【信息缺失】需要补充来源”。
5. 避免“已有研究表明”“数据显示”“政策明确提出”“标准规定”等无来源事实句，除非正文同时给出真实来源或“资料来源：...”。
6. 补足概念界定、机制分析、实施路径、风险边界和价值评估，避免短句堆叠。
7. 禁止“不仅……而且……”“值得注意的是”“需要强调的是”“理应指出”“某种意义上”“在一定程度上”“大致而言”“提供了有益的尝试”“进行了深入的探讨”“综上所述”。定义必须带立场，批评必须直接，节尾用推论、限制或矛盾衔接。
8. 使用第三人称、客观、可出版的学术专著语体；每段以两个全角空格开头；可按论证自然转向分为2~3段，也可在短文本或单一论证单元中保留1段，不要追求段落长度整齐。
9. 少用双引号，普通判断句和概念直接陈述；只保留直接引语、术语首次界定或特殊含义临时用法。
"""

    def _compress_to_target_words(
        self,
        content: str,
        prompt: str,
        section_title: str,
        target_words: int,
        current_words: int,
        content_callback=None,
        generated_index: int = 1,
        total_sections: int = 1,
    ) -> str:
        """模型初稿明显超出目标字数时，先让模型保留论证骨架进行压缩。"""
        if current_words <= max(1, int(target_words * 1.10)):
            return content
        compress_prompt = f"""{prompt}

## 已生成正文（明显超字数）
{content}

## 压缩任务
当前正文约 {current_words} 字，需要删减约 {max(1, current_words - target_words)} 字。请在不新增事实、不新增引用、不输出标题的前提下精简冗余表述；不得截断半句话。
要求：
1. 保留核心概念、论证链条、实施路径、风险边界和已有可追溯来源。
2. 删除重复铺陈、空泛过渡、规划说明和“写作思路/资料依据/证据边界/后续补充”等非正文内容。
3. 少用双引号，普通判断句和概念直接陈述。
4. 只输出压缩后的正文段落，每段以两个全角空格开头；可按论证自然转向分段，不要追求段落长度整齐。"""
        if content_callback:
            content_callback("_字数超出目标范围，正在压缩正文..._", section_title, generated_index, total_sections)
        try:
            compressed = self.llm_client.generate_content(
                compress_prompt,
                max_tokens=max(700, min(5000, int(target_words * 1.25))),
                temperature=0.25,
            )
            compressed = self._strip_duplicate_heading(self._sanitize_model_output(compressed, section_title), section_title)
            compressed_words = self._count_words(compressed)
            if self._has_real_body_content(compressed):
                self._emit_content_callback(content_callback, compressed, section_title, target_words, generated_index, total_sections)
                return compressed
            self.logger.warning(
                "Compression for section %s returned no valid body: before=%s after=%s target=%s; using deterministic trim.",
                section_title,
                current_words,
                compressed_words,
                target_words,
            )
        except Exception as e:
            self.logger.warning("Failed to compress section %s to target words: %s", section_title, e)
        return content

    def _expand_to_target_words(
        self,
        base_content: str,
        prompt: str,
        section_title: str,
        target_words: int,
        current_words: int,
        content_callback=None,
        generated_index: int = 1,
        total_sections: int = 1,
    ) -> str:
        """模型初稿明显短于大纲字数时，自动续写补足。"""
        need_words = max(200, target_words - current_words)
        expand_prompt = f"""{prompt}

## 已生成正文
{base_content}

## 续写任务
当前正文约 {current_words} 字，需要补充约 {need_words} 字。
请在不重复已有内容、不输出标题的前提下，扩展论证的概念边界、机制分析、适用场景或风险条件。
只输出需要追加的正文段落；不要输出字数统计、自评或过程说明；少用双引号。"""
        try:
            addition_chunks = []
            if hasattr(self.llm_client, "stream_content"):
                for chunk in self.llm_client.stream_content(expand_prompt, max_tokens=max(1800, min(12000, int(need_words * 4.0))), temperature=0.6):
                    if chunk:
                        addition_chunks.append(str(chunk))
                        self._emit_content_callback(
                            content_callback,
                            base_content + "\n\n" + "".join(addition_chunks),
                            section_title,
                            target_words,
                            generated_index,
                            total_sections,
                        )
                addition = "".join(addition_chunks)
            else:
                addition = self.llm_client.generate_content(expand_prompt, max_tokens=max(1800, min(12000, int(need_words * 4.0))), temperature=0.6)
            addition = self._strip_duplicate_heading(self._sanitize_model_output(addition, section_title), section_title)
            if addition:
                return (base_content.rstrip() + "\n\n" + addition.strip()).strip()
        except Exception as e:
            self.logger.warning("Failed to expand section %s to target words: %s", section_title, e)
        return base_content

    def _ends_with_sentence_terminal(self, content: str) -> bool:
        """判断正文是否以完整句末结束；不完整时只追加续写，不裁剪原文。"""
        text = re.sub(r"[\s　]+$", "", str(content or ""))
        if not text:
            return True
        return bool(re.search(r"[。！？.!?;；][\)）\]】》”’\"']*$", text))

    def _complete_truncated_tail(
        self,
        content: str,
        prompt: str,
        section_title: str,
        target_words: int,
        content_callback=None,
        generated_index: int = 1,
        total_sections: int = 1,
    ) -> str:
        """检测模型因输出预算中断的半句话；只向后续写补全，不删除、不改写已有正文。"""
        if self._ends_with_sentence_terminal(content):
            return content
        tail = str(content or "")[-300:]
        completion_prompt = f"""{prompt}

## 已生成正文尾部（疑似被模型输出预算截断）
{tail}

## 续写补全任务
上面的正文最后一句没有结束。请只从断点之后继续写，补完这个句子，并在必要时再补一两句收束当前小节。
硬性要求：
1. 不要复述、不要改写、不要删除已经生成的文字。
2. 不要输出标题、说明、评分、JSON、HTML 或代码块。
3. 只输出断点之后应该追加的文字；第一字必须能直接接在原文末尾。
4. 以完整句号、问号或感叹号结束。"""
        if content_callback:
            content_callback("_检测到正文尾句未闭合，正在只追加续写补全..._", section_title, generated_index, total_sections)
        try:
            addition = self.llm_client.generate_content(
                completion_prompt,
                max_tokens=max(1200, min(4000, int(max(target_words, 400) * 1.5))),
                temperature=0.35,
            )
            addition = self._strip_duplicate_heading(self._sanitize_model_output(addition, section_title), section_title)
            if addition:
                completed = str(content or "").rstrip() + str(addition).lstrip()
                self._emit_content_callback(content_callback, completed, section_title, target_words, generated_index, total_sections)
                return completed
        except Exception as e:
            self.logger.warning("Failed to complete truncated tail for section %s: %s", section_title, e)
        return content

    def _sanitize_model_output(self, content: str, section_title: str) -> str:
        """清理模型异常输出，避免把供应商错误页/HTML 写进章节。"""
        if not content:
            return ""
        text = str(content).strip()
        html_signals = ["<!doctype html", "<html", "</html>", "<head", "<body", "<title>", "<script", "<iframe", "HubLinuxDO"]
        lowered = text.lower()
        if any(signal.lower() in lowered for signal in html_signals):
            self.logger.warning("Invalid HTML/error-page response while writing %s", section_title)
            return ""
        text = re.sub(r"```(?:html|xml|javascript|js)?\s*.*?</(?:html|body|script|iframe)>\s*```", "", text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"(?im)^\s*Section\s+\d+\s*:\s*Write\s+this\s+chapter.*$", "", text)
        text = re.sub(r"(?is)<script.*?</script>|<iframe.*?</iframe>", "", text)
        # 部分 OpenAI-compatible 中转会把 chat role 串入正文开头或行首，例如
        # “assistantassistant 正文”“assistant: 正文”。这些不是正文内容，必须在所有
        # 初稿、续写、重写、压缩和最终格式化阶段统一剥离。
        text = re.sub(r"(?im)^\s*(?:assistant\s*){1,4}[:：\-—\s]*", "", text)
        text = re.sub(r"(?im)^\s*(?:user|system)\s*[:：\-—]\s*", "", text)
        text = re.sub(r"(?i)(?<=\n)(?:assistant\s*){2,}(?=\S)", "", text)
        text = re.sub(r"(?i)^(?:assistant\s*){2,}(?=\S)", "", text)
        return text.strip()

    def _strip_duplicate_heading(self, content: str, section_title: str) -> str:
        lines = content.strip().splitlines()
        normalized_title = re.sub(r"[\s　]+", "", section_title or "")
        title_without_prefix = re.sub(r"^（[一二三四五六七八九十百]+）", "", normalized_title)
        while lines:
            first = lines[0].strip()
            heading = first.lstrip("#").strip() if first.startswith("#") else first
            normalized_heading = re.sub(r"[\s　]+", "", heading)
            heading_without_prefix = re.sub(r"^（[一二三四五六七八九十百]+）", "", normalized_heading)
            same_title = bool(
                normalized_title
                and (
                    normalized_title in normalized_heading
                    or normalized_heading in normalized_title
                    or (title_without_prefix and title_without_prefix == heading_without_prefix)
                )
            )
            if same_title:
                lines = lines[1:]
                while lines and not lines[0].strip():
                    lines = lines[1:]
                continue
            break
        return "\n".join(lines).strip()

    def _language_norm_issues(self, text: str) -> List[str]:
        """检测用户指定的正文语言规范问题。"""
        content = str(text or "")
        issues: List[str] = []
        if "制定" in content:
            issues.append("表达拟定计划、办法、方案时应使用“制订”，不得使用“制定”。")
        if "作出" in content:
            issues.append("“做出 + 名词”结构应使用“做出”，不得使用“作出”。")
        if "提升" in content:
            issues.append("描述水平、程度、质量变化时应使用“提高”，不得使用“提升”。")
        sentences = [s for s in re.split(r"(?<=[。！？；.!?;])", content) if s.strip()]
        for sentence in sentences:
            connector_hits = sum(sentence.count(token) for token in ("而", "且", "并", "以及"))
            if connector_hits >= 4 or len(sentence) > 95 and connector_hits >= 3:
                issues.append("连接词使用偏密，应减少“而”“且”“并”“以及”，能断句时用句号断开。")
                break
        if re.search(r"[应可需]{2,}|应当可以|可以需要|需要可以|应需|需应|可应", content):
            issues.append("“应”“可”“需”等情态词存在混用或堆砌风险，应区分义务、许可和必要条件。")
        return issues

    def check_and_rewrite_language_norms(
        self,
        text: str,
        section_title: str = "",
        target_words: int = 0,
        content_callback=None,
        generated_index: int = 1,
        total_sections: int = 1,
    ) -> str:
        """按用户指定语言规范做确定性替换；复杂句法问题触发一次定向改写。"""
        content = str(text or "").strip()
        if not content:
            return ""
        normalized = content.replace("制定", "制订").replace("作出", "做出").replace("提升", "提高")
        issues = self._language_norm_issues(normalized)
        if not issues:
            return normalized

        rewrite_prompt = f"""以下学术文本存在语言规范问题。请保留原意和事实边界，只修正语言表达。必须遵守：
1. 表达拟定计划、办法、方案时，一律使用“制订”，不使用“制定”。
2. 表达“做出 + 名词”结构时，统一使用“做出”，不使用“作出”。
3. 描述水平、程度、质量的提高时，使用“提高”，不使用“提升”。
4. 谨慎使用连接词，减少“而”“且”“并”“以及”等造成的拖沓；能用句号断开就断开，不硬串长句。
5. “应”表义务或推荐，“可”表可能性或许可，“需”表必要条件，不混用、不堆砌。
6. 直接输出改写后的全文，不要解释，不要输出检查清单。

## 发现的问题
{chr(10).join('- ' + issue for issue in issues)}

## 待改写文本
{normalized}"""
        if content_callback:
            content_callback("_检测到语言规范问题，正在定向改写一次..._", section_title, generated_index, total_sections)
        try:
            rewritten = self.llm_client.generate_content(
                rewrite_prompt,
                max_tokens=max(1200, min(12000, int(max(target_words, self._count_words(normalized), 400) * 2.5))),
                temperature=0.2,
            )
            rewritten = self._strip_duplicate_heading(self._sanitize_model_output(rewritten, section_title), section_title)
            if self._has_real_body_content(rewritten):
                rewritten = rewritten.replace("制定", "制订").replace("作出", "做出").replace("提升", "提高")
                self._emit_content_callback(content_callback, rewritten, section_title, target_words or self._count_words(rewritten), generated_index, total_sections)
                return rewritten
        except Exception as e:
            self.logger.warning("Failed to rewrite language norms for section %s: %s", section_title, e)
        return normalized

    def check_and_rewrite_quotes(
        self,
        text: str,
        section_title: str = "",
        target_words: int = 0,
        content_callback=None,
        generated_index: int = 1,
        total_sections: int = 1,
    ) -> str:
        """检测双引号密度；超过阈值时只调用模型做一次定向去引号改写。"""
        content = str(text or "").strip()
        if not content:
            return ""
        quote_pairs = min(content.count("“"), content.count("”"))
        if quote_pairs <= 0:
            return content
        char_count = max(1, self._count_words(content))
        if quote_pairs / char_count * 1000 <= 2:
            return content

        rewrite_prompt = f"""以下学术文本使用了过多双引号。请保留原意，将普通判断句、概念句改为无引号转述。只保留三种情况可加引号：①直接转述他人原话；②术语首次出现需要括注界定；③有特殊含意的临时用法。直接输出改写后的全文，不要做任何解释。

## 待改写文本
{content}"""
        if content_callback:
            content_callback("_检测到双引号过多，正在定向改写一次..._", section_title, generated_index, total_sections)
        try:
            rewritten = self.llm_client.generate_content(
                rewrite_prompt,
                max_tokens=max(1200, min(12000, int(max(target_words, char_count) * 2.5))),
                temperature=0.25,
            )
            rewritten = self._strip_duplicate_heading(self._sanitize_model_output(rewritten, section_title), section_title)
            if self._has_real_body_content(rewritten):
                self._emit_content_callback(content_callback, rewritten, section_title, target_words or char_count, generated_index, total_sections)
                return rewritten
        except Exception as e:
            self.logger.warning("Failed to rewrite quotes for section %s: %s", section_title, e)
        return content

    def _repair_word_count_loop(
        self,
        content: str,
        prompt: str,
        section_title: str,
        target_words: int,
        content_callback=None,
        generated_index: int = 1,
        total_sections: int = 1,
    ) -> str:
        """系统统计中文字数，并在 ±10% 外最多执行 2 次补写或压缩。"""
        if not content or not target_words:
            return content or ""
        repaired = str(content).strip()
        lower_bound = max(1, int(target_words * 0.90))
        upper_bound = max(lower_bound + 1, int(target_words * 1.10))
        for _ in range(2):
            current_words = self._count_words(repaired)
            if lower_bound <= current_words <= upper_bound:
                break
            if current_words < lower_bound:
                next_text = self._expand_to_target_words(
                    base_content=repaired,
                    prompt=prompt,
                    section_title=section_title,
                    target_words=target_words,
                    current_words=current_words,
                    content_callback=content_callback,
                    generated_index=generated_index,
                    total_sections=total_sections,
                )
            else:
                next_text = self._compress_to_target_words(
                    content=repaired,
                    prompt=prompt,
                    section_title=section_title,
                    target_words=target_words,
                    current_words=current_words,
                    content_callback=content_callback,
                    generated_index=generated_index,
                    total_sections=total_sections,
                )
            next_text = self._strip_duplicate_heading(self._sanitize_model_output(next_text, section_title), section_title)
            if not self._has_real_body_content(next_text) or next_text.strip() == repaired.strip():
                break
            repaired = next_text.strip()
        return repaired

    def _split_sentences(self, text: str) -> List[str]:
        """按完整句切分；只作为段落安全重组依据，不在句中截断。"""
        clean = re.sub(r"\s*\n\s*", "", str(text or "").strip())
        if not clean:
            return []
        return [s.strip() for s in re.split(r"(?<=[。！？；.!?;])", clean) if s.strip()]

    def enforce_paragraph_shape(self, text: str) -> str:
        """语义安全分段：每段至少五句，不按字数均分正文。"""
        content = self._strip_duplicate_heading(text, "")
        content = re.sub(r"\n{3,}", "\n\n", str(content or "").strip())
        if not content:
            return ""

        min_sentences_per_paragraph = 5
        raw_paragraphs = [p.strip() for p in re.split(r"\n\s*\n", content) if p.strip()]
        if 2 <= len(raw_paragraphs) <= 3 and all(len(self._split_sentences(p)) >= min_sentences_per_paragraph for p in raw_paragraphs):
            return "\n\n".join(raw_paragraphs).strip()

        sentences = self._split_sentences(content)
        if len(sentences) < min_sentences_per_paragraph * 2:
            return "".join(sentences).strip() if sentences else content

        transition_words = (
            "与此同时", "进一步看", "不过", "因此", "然而", "从实践层面", "从技术层面",
            "从制度层面", "相较而言", "由此", "换言之", "另一方面", "更重要的是",
            "在这一背景下", "基于此", "反过来看", "具体而言", "与此不同", "在风险层面",
            "从治理角度", "从应用场景看", "问题在于", "这种变化意味着"
        )
        candidates: list[int] = []
        for idx in range(min_sentences_per_paragraph, len(sentences) - min_sentences_per_paragraph + 1):
            probe = sentences[idx].lstrip("　 ，,；;。") if idx < len(sentences) else ""
            previous = sentences[idx - 1] if idx > 0 else ""
            if any(probe.startswith(word) or word in probe[:20] for word in transition_words):
                candidates.append(idx)
            elif any(mark in previous for mark in ("。然而", "。但是", "。不过", "。因此", "。由此")):
                candidates.append(idx)

        if not candidates:
            return "".join(sentences).strip()

        # 选择最靠近语义转折的自然切点，同时避免精确二等分带来的机械平均感。
        preferred = len(sentences) * 0.58
        split_at = min(candidates, key=lambda value: abs(value - preferred))
        first = "".join(sentences[:split_at]).strip()
        second = "".join(sentences[split_at:]).strip()
        if (
            len(self._split_sentences(first)) < min_sentences_per_paragraph
            or len(self._split_sentences(second)) < min_sentences_per_paragraph
        ):
            return "".join(sentences).strip()
        return f"{first}\n\n{second}".strip()

    def _enforce_paragraph_shape(self, content: str, target_words: int = 0) -> str:
        """兼容旧调用名，实际使用安全分段策略。"""
        return self.enforce_paragraph_shape(content)

    def _shape_preview_content(self, content: str, section_title: str, target_words: int) -> str:
        """实时预览也做段落整形，避免流式输出阶段显示三四句话一段。"""
        text = self._sanitize_model_output(content, section_title)
        text = self._strip_duplicate_heading(text, section_title) if text else ""
        return self._enforce_paragraph_shape(text, target_words)

    def _emit_content_callback(
        self,
        content_callback,
        content: str,
        section_title: str,
        target_words: int,
        generated_index: int,
        total_sections: int,
    ) -> None:
        if not content_callback:
            return
        text = str(content or "")
        if text.lstrip().startswith("_"):
            content_callback(text, section_title, generated_index, total_sections)
            return
        text = self.check_and_rewrite_language_norms(text, section_title=section_title, target_words=target_words)
        content_callback(self._shape_preview_content(text, section_title, target_words), section_title, generated_index, total_sections)

    def _ensure_fullwidth_paragraph_indent(self, content: str) -> str:
        """保证每个正文自然段首行两个全角空格，不处理 Markdown 标题。"""
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", str(content or "").strip()) if p.strip()]
        formatted: list[str] = []
        for paragraph in paragraphs:
            if paragraph.startswith("#") or paragraph.lstrip().startswith("_"):
                formatted.append(paragraph)
            else:
                formatted.append("　　" + paragraph.lstrip("　 "))
        # 不能使用 str.strip()：Python 会把全角空格也当作空白剥离，导致首段缩进丢失。
        return "\n\n".join(formatted).strip("\r\n ")

    def _finalize_section_content(self, content: str, section_title: str, target_words: int) -> str:
        """小节写入/预览前只做格式规范：去标题、合段、保留首行缩进；不按字数裁剪正文。"""
        text = self._sanitize_model_output(content, section_title)
        text = self._strip_duplicate_heading(text, section_title) if text else ""
        text = self.check_and_rewrite_language_norms(text, section_title=section_title, target_words=target_words)
        text = self._enforce_paragraph_shape(text, target_words)
        return self._ensure_fullwidth_paragraph_indent(text)

    def _count_words(self, text: str) -> int:
        """正文篇幅校验只统计汉字，避免标点、空格和英文编号干扰。"""
        return len(re.findall(r"[\u4e00-\u9fff]", text or ""))

    def _has_real_body_content(self, content: str) -> bool:
        """判断生成结果中是否有真实正文，避免只写入标题或错误占位。"""
        if not content or not str(content).strip():
            return False
        body_lines = [line.strip() for line in str(content).splitlines() if line.strip() and not line.strip().startswith("#")]
        body = "\n".join(body_lines).strip()
        if not body:
            return False
        lowered = body.lower()
        invalid_signals = ["<!doctype html", "<html", "</html>", "traceback", "error:", "生成失败"]
        return not any(signal in lowered for signal in invalid_signals)

    def _write_legacy_scene_chapter(self, project_knowledge_base: ProjectKnowledgeBase, chapter_number: int, chapter: Chapter) -> str:
        """旧版小说场景写作逻辑：仅在没有 academic sections 时启用。"""
        if not chapter.scenes:
            console.print(f"[yellow]No sections/scenes found for Chapter {chapter_number}. Creating a fallback writing unit.[/yellow]")
            default_scene = Scene(
                scene_number=1,
                summary=chapter.summary or "Write this chapter as an academic chapter.",
                characters=[],
                setting="",
                goal="Complete the chapter",
                emotional_beat=""
            )
            chapter.scenes.append(default_scene)

        ordered_scenes = sorted(chapter.scenes, key=lambda s: s.scene_number)
        scene_contents = []
        for scene in ordered_scenes:
            console.print("[cyan]Creating fallback section %d of %d...[/cyan]" % (scene.scene_number, len(ordered_scenes)))
            scene_title = f"Section {scene.scene_number}: {scene.summary[:30]}..." if len(scene.summary) > 30 else f"Section {scene.scene_number}: {scene.summary}"
            scene_prompt = prompts.SCENE_PROMPT.format(
                chapter_number=chapter_number,
                chapter_title=chapter.title,
                book_title=project_knowledge_base.title,
                genre=project_knowledge_base.genre,
                category=project_knowledge_base.category,
                language=project_knowledge_base.language,
                chapter_summary=chapter.summary,
                scene_number=scene.scene_number,
                scene_summary=scene.summary,
                characters=", ".join(scene.characters) if scene.characters else "None specified",
                setting=scene.setting if scene.setting else "None specified",
                goal=scene.goal if scene.goal else "None specified",
                emotional_beat=scene.emotional_beat if scene.emotional_beat else "None specified",
                total_scenes=len(ordered_scenes)
            )
            scene_prompt = f"{ACADEMIC_MONOGRAPH_SYSTEM_PROMPT}\n\n{scene_prompt}\n\n请按学术专著强制规范生成本写作单元正文。每个自然段必须以两个全角空格开头，不输出HTML/XML/JS/代码/注释/指令残留；不得编造数据、案例、文献、法规、标准编号、人名、机构名、时间、地点；不得输出‘请搜索’‘请查询’‘详见某网页’等虚假操作表述；信息不足时必须明确写出‘【信息缺失】需要您提供……’。"
            scene_content = self.llm_client.generate_content(scene_prompt, max_tokens=3000)
            if not scene_content:
                scene_content = f"[{scene_title} content unavailable]"
            if not scene_content.startswith(f"**{scene_title}**") and not scene_content.startswith(f"# {scene_title}"):
                scene_content = f"**{scene_title}**\n\n{scene_content}"
            scene_contents.append(scene_content)

        legacy_text = f"# {format_chapter_label(chapter_number, chapter.title)}\n\n" + "\n\n".join(scene_contents) + "\n"
        legacy_text, _, _ = finalize_academic_chapter(legacy_text, target_words=getattr(chapter, "word_count", 0) or 0)
        return legacy_text