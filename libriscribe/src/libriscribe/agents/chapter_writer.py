from __future__ import annotations

# src/libriscribe/agents/chapter_writer.py

import logging
import re
from pathlib import Path
from typing import Optional, Dict, List, Sequence, Tuple
from libriscribe.agents.agent_base import Agent
from libriscribe.utils import prompts_context as prompts
from libriscribe.utils.file_utils import (
    read_markdown_file,
    read_json_file,
    write_markdown_file,
    extract_json_from_markdown,
)
from libriscribe.knowledge_base import ProjectKnowledgeBase, Chapter, Scene, ChapterSection
from libriscribe.utils.llm_client import LLMClient
from libriscribe.utils.chinese_labels import (
    format_chapter_label,
    format_outline_section_label as shared_outline_section_label,
)
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
        writing_skill_id: str = "",  # 保留但忽略
    ) -> None:
        try:
            chapter = project_knowledge_base.get_chapter(chapter_number)
            if not chapter:
                console.print(f"[red]ERROR: Chapter {chapter_number} not found in knowledge base.[/red]")
                chapter = Chapter(
                    chapter_number=chapter_number,
                    title=f"Chapter {chapter_number}",
                    summary="A new academic chapter.",
                )
                project_knowledge_base.add_chapter(chapter)

            console.print(f"\n[cyan]Writing Chapter {chapter_number}: {chapter.title or ''}[/cyan]")

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
                chapter_content = self._write_legacy_scene_chapter(
                    project_knowledge_base, chapter_number, chapter
                )

            if not self._has_real_body_content(chapter_content):
                raise RuntimeError(
                    "模型没有返回可写入正文的有效内容，请检查模型配置、API Base 或网络状态。"
                )

            write_markdown_file(output_path, chapter_content)
            chapter.actual_word_count = self._count_words(chapter_content)
            chapter.status = "completed"
            project_knowledge_base.chapters[chapter_number] = chapter
            console.print(f"[green]Chapter {chapter_number} completed.[/green]")

        except Exception as e:
            self.logger.exception(f"Error writing chapter {chapter_number}: {e}")
            console.print(
                f"[red]ERROR: Failed to write chapter {chapter_number}. See log for details.[/red]"
            )
            raise

    @staticmethod
    def format_outline_section_label(section_number: str, title: str = "") -> str:
        return shared_outline_section_label(section_number, title)

    @staticmethod
    def section_heading_pattern(section_number: str, section_title: str = "") -> re.Pattern:
        display_title = ChapterWriterAgent.format_outline_section_label(
            section_number, section_title
        )
        legacy_title = f"{section_number} {section_title}".strip()
        alternatives = {
            re.escape(section_number),
            re.escape(legacy_title),
            re.escape(display_title),
        }
        return re.compile(
            r"^(#{2,6})\s+(?:"
            + "|".join(sorted(alternatives, key=len, reverse=True))
            + r")(?:\s|$)"
        )

    @staticmethod
    def _word_count_delta_score(words: int, target_words: int) -> int:
        return abs(int(words or 0) - int(target_words or 0))

    @staticmethod
    def distribute_word_targets(section_titles: Sequence[str], total_words: int) -> List[int]:
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
            (
                (
                    "路径",
                    "策略",
                    "优化",
                    "模型",
                    "实践",
                    "治理",
                    "建设",
                    "应用",
                    "方案",
                    "转化",
                ),
                1.48,
            ),
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
        raw_targets = [total * c / coefficient_sum for c in coefficients]
        targets = [max(1, int(round(v))) for v in raw_targets]
        delta = total - sum(targets)
        if delta:
            order = sorted(
                range(len(targets)), key=lambda idx: coefficients[idx], reverse=delta > 0
            )
            step = 1 if delta > 0 else -1
            for idx in order:
                if delta == 0:
                    break
                if step < 0 and targets[idx] <= 1:
                    continue
                targets[idx] += step
                delta -= step
        return targets

    # ---------- 倒计时标记（内置篇幅尺） ----------
    def _build_countdown_markers(self, target_words: int, chunk_size: int = 100) -> str:
        target = max(1, int(target_words or 0))
        chunk = max(25, int(chunk_size or 100))
        values = list(range(target, 0, -chunk))
        values.append(0)
        return " ".join(f"[{value}/{target}]" for value in values)

    def _countdown_marker_prompt(
        self, target_words: int, chunk_size: int = 100, mode: str = "draft"
    ) -> str:
        markers = self._build_countdown_markers(target_words, chunk_size=chunk_size)
        if mode == "compress":
            task = "请按目标字数重写完整正文，优先删除重复解释、空泛过渡、套话和跑题内容。"
        elif mode == "expand":
            task = "请按目标字数重写完整正文，把补充内容融合进原有论证结构，不要简单追加尾巴。"
        else:
            task = "请按目标字数撰写当前小节正文，围绕写作思路充分展开。"

        # 提前 20% 收束的硬提示
        wrap_up_threshold = int(target_words * 0.2)
        return f"""## 内部倒计时长度锚点（禁止输出）
目标正文约 {int(target_words or 0)} 字。下面标记只用于你内部控制篇幅，绝对服从用标记规则，禁止出现在最终正文中：
{markers}

使用规则：
1. 每推进一个标记，约完成 {chunk_size} 个中文字符的有效正文。
2. 标记不是标题、编号、脚注或正文内容，最终输出中不得出现任何类似 [800/800]、[700/800] 的标记。
3. {task}
4. 不得为了消耗标记灌水，不得编造新事实、新数据、新文献。
5. 当标记推进到剩余约 {wrap_up_threshold} 字（即出现 [{wrap_up_threshold}/{target_words}] 附近标记）时，表示已接近字数上限，必须立即转向总结收束，只写核心判断或结论，不再新增任何分论点或展开分析。
6. 接近最后两个标记时自然收束，确保正文在标记归零前完整结束。
"""

    def _strip_countdown_markers(self, text: str) -> str:
        return re.sub(r"\[\s*\d+\s*/\s*\d+\s*\]", "", str(text or "")).strip()

    # ---------- Token 预估与历史 ----------
    def _estimate_token_cap(
        self, target_words: int, history: List[Tuple[int, int]], safety_factor: float = 0.9
    ) -> int:
        ratios = [cw / tk for tk, cw in history if tk > 0 and cw > 0]
        avg_ratio = sum(ratios) / len(ratios) if ratios else 0.6
        avg_ratio = max(0.3, min(avg_ratio, 1.2))
        estimated = int((max(1, target_words) / avg_ratio) * safety_factor)
        return max(300, min(6000, estimated))

    def _estimate_output_tokens(self, text: str) -> int:
        value = str(text or "")
        if not value:
            return 0
        try:
            import tiktoken

            encoding = tiktoken.get_encoding("cl100k_base")
            return len(encoding.encode(value))
        except Exception:
            chinese = self._count_words(value)
            ascii_chars = len(re.findall(r"[A-Za-z0-9]", value))
            other_chars = max(0, len(value) - chinese - ascii_chars)
            return max(1, int(chinese / 0.6) + int(ascii_chars / 4) + int(other_chars / 2))

    def _last_completion_token_count(self, text: str) -> int:
        completion_tokens = int(getattr(self.llm_client, "last_completion_tokens", 0) or 0)
        total_tokens = int(getattr(self.llm_client, "last_total_tokens", 0) or 0)
        if completion_tokens > 0:
            return completion_tokens
        if total_tokens > 0:
            return total_tokens
        return self._estimate_output_tokens(text)

    def _record_generation_history(self, history: List[Tuple[int, int]], text: str) -> None:
        words = self._count_words(text)
        tokens = self._last_completion_token_count(text)
        if tokens > 0 and words > 0:
            history.append((tokens, words))

    def _word_count_pressure_text(self, pressure_level: int, mode: str) -> str:
        return "按系统统计结果修正正文篇幅，禁止把修订过程写进正文。"

    # ---------- 核心章节生成方法 ----------
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
        all_sections = sorted(
            chapter.sections,
            key=lambda s: [int(p) if p.isdigit() else 0 for p in s.section_number.split(".")]
        )

        section_numbers = {sec.section_number for sec in all_sections}

        def _is_leaf(sec):
            sn = sec.section_number
            for other_sn in section_numbers:
                if other_sn != sn and other_sn.startswith(sn + "."):
                    return False
            return True

        leaf_sections = [sec for sec in all_sections if _is_leaf(sec)]

        if section_number:
            ordered_sections = [sec for sec in all_sections if sec.section_number == section_number]
            if not ordered_sections:
                raise ValueError(f"Section {section_number} not found in chapter {chapter_number}.")
            if not _is_leaf(ordered_sections[0]):
                target_prefix = section_number + "."
                ordered_sections = [sec for sec in leaf_sections if sec.section_number.startswith(target_prefix)]
                if not ordered_sections:
                    ordered_sections = []  # 没有叶子子节，只输出标题
        else:
            ordered_sections = leaf_sections

        terminology = project_knowledge_base.get_terminology_context()
        previous_summaries = project_knowledge_base.get_previous_summaries(chapter_number)
        outline_tree = "\n".join(
            f"{'  ' * (max(getattr(sec, 'level', 1) - 1, 0))}- {self.format_outline_section_label(sec.section_number, sec.title)}"
            for sec in all_sections
        )

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
        rhythm_target_by_number = {
            sec.section_number: rhythm_targets[idx]
            for idx, sec in enumerate(ordered_sections)
            if idx < len(rhythm_targets)
        }
        generated_index = 0
        generated_actual_total = 0
        generated_target_total = 0

        # 按目录顺序输出：结构标题 -> 其下叶子小节正文
        for section in all_sections:
            level = max(1, min(getattr(section, "level", 1), 3))
            markdown_level = "#" * (level + 1)
            section_title = self.format_outline_section_label(section.section_number, section.title)

            if not _is_leaf(section):
                if (
                    not section_number
                    or section.section_number == section_number
                    or section.section_number.startswith((section_number or "") + ".")
                    or (section_number and section_number.startswith(section.section_number + "."))
                ):
                    content_parts.append(f"{markdown_level} {section_title}\n")
                continue

            if section.section_number not in target_numbers:
                continue

            generated_index += 1
            base_target_words = rhythm_target_by_number.get(
                section.section_number
            ) or getattr(section, "word_count", 0) or max(800, int((getattr(chapter, "word_count", 0) or 4000) / max(len(ordered_sections), 1)))
            target_words = base_target_words

            # 动态平衡字数（不再依赖 Skill）
            if not section_number:
                remaining_sections = ordered_sections[generated_index - 1:]
                remaining_words = max(1, int(target_total_words or 0) - int(generated_actual_total or 0))
                remaining_titles = [
                    self.format_outline_section_label(sec.section_number, sec.title)
                    for sec in remaining_sections
                ]
                dynamic_targets = self.distribute_word_targets(remaining_titles, remaining_words)
                target_words = dynamic_targets[0] if dynamic_targets else base_target_words
                original_remaining_target = max(1, int(target_total_words or 0) - int(generated_target_total or 0))
                if generated_actual_total > generated_target_total:
                    self.logger.info(
                        "Word rebalance before section %s: planned_so_far=%s actual_so_far=%s current_base=%s adjusted=%s remaining_words=%s",
                        section_title,
                        generated_target_total,
                        generated_actual_total,
                        base_target_words,
                        target_words,
                        remaining_words,
                    )
                target_words = max(1, min(int(target_words), original_remaining_target))

            console.print(
                f"[cyan]Writing academic section {generated_index}/{len(ordered_sections)}: {section_title}[/cyan]"
            )

            rag_context = self._get_rag_context(
                getattr(section, "rag_query", "") or section.title or section_title,
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

            section_content = self._strip_duplicate_heading(
                self._sanitize_model_output(section_content, section_title), section_title
            )
            if not section_content:
                section.actual_word_count = 0
                section.status = "failed"
                if progress_callback:
                    progress_callback(generated_index, len(ordered_sections), section_title, "failed_final")
                raise RuntimeError(
                    f"小节 {section_title} 连续重试后仍未获得有效正文。"
                    "请检查当前模型是否拦截长提示、是否支持较大 max_tokens，或降低该小节目标字数后重试。"
                )

            # 引号密度控制
            section_content = self.check_and_rewrite_quotes(
                section_content,
                section_title=section_title,
                target_words=target_words,
                content_callback=content_callback,
                generated_index=generated_index,
                total_sections=len(ordered_sections),
            )
            # 语言规范修正
            section_content = self.check_and_rewrite_language_norms(
                section_content,
                section_title=section_title,
                target_words=target_words,
                content_callback=content_callback,
                generated_index=generated_index,
                total_sections=len(ordered_sections),
            )
            # 质量门禁（已移除 Skill，直接返回原内容）
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
            # 尾句补全
            section_content = self._complete_truncated_tail(
                content=section_content,
                prompt=prompt,
                section_title=section_title,
                target_words=target_words,
                content_callback=content_callback,
                generated_index=generated_index,
                total_sections=len(ordered_sections),
            )
            # 字数闭环修复
            section_content = self._repair_word_count_loop(
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
            section.word_count_target = int(target_words or 0)
            section.word_count_actual = actual_words
            generated_actual_total += int(actual_words or 0)
            generated_target_total += int(target_words or 0)

            # 字数状态标记
            strict_lower = int(round(target_words * 0.95))
            strict_upper = int(round(target_words * 1.05))
            if not (strict_lower <= actual_words <= strict_upper):
                section.status = "word_count_soft_fail"
                section.word_count_status = "word_count_soft_fail"
                section.word_count_note = (
                    f"目标 {target_words} 字，当前约 {actual_words} 字；已进行多轮补写/压缩，"
                    "仍未进入硬红线。正文已保留最佳版本并建议人工复核。"
                )
                self.logger.warning(
                    "Section %s marked word_count_soft_fail: target=%s actual=%s",
                    section_title,
                    target_words,
                    actual_words,
                )
            else:
                section.status = "completed"
                section.word_count_status = "ok"
                section.word_count_note = ""

            generated_summaries.append(f"{section_title}: {section_content[:240]}")
            content_parts.append(f"{markdown_level} {section_title}\n\n{section_content.strip()}\n")

            if content_callback:
                content_callback(section_content, section_title, generated_index, len(ordered_sections))
            if progress_callback:
                progress_callback(generated_index, len(ordered_sections), section_title, "completed")

        if not section_number:
            chapter.sections = all_sections
            content_parts.extend(
                [
                    "",
                    self._build_chapter_back_matter(
                        project_knowledge_base, chapter, chapter_number, content_parts, terminology
                    ),
                ]
            )
        else:
            updated = {sec.section_number: sec for sec in ordered_sections}
            chapter.sections = [updated.get(sec.section_number, sec) for sec in all_sections]

        chapter_text = "\n".join(content_parts).strip() + "\n"
        if not section_number:
            target_words = getattr(chapter, "word_count", 0) or sum(
                getattr(sec, "word_count", 0) or 0 for sec in getattr(chapter, "sections", [])
            )
            chapter_text, score_total, verdict = finalize_academic_chapter(chapter_text, target_words=target_words)
            if score_total < 40:
                self.logger.warning(
                    "Chapter %s self-assessment below 80 (%s/50): %s. Applying deterministic formatting rewrite once.",
                    chapter_number,
                    score_total,
                    verdict,
                )
                chapter_text, _, _ = finalize_academic_chapter(
                    ensure_fullwidth_indent(chapter_text), target_words=target_words
                )
        else:
            chapter_text = ensure_fullwidth_indent(chapter_text)
        return chapter_text

    # ---------- 提示词构建 ----------
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
        section_level = getattr(section, "level", 1)
        section_goal = getattr(section, "summary", "") or section_title
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
        countdown_prompt = (
            self._countdown_marker_prompt(target_words, chunk_size=100, mode="draft")
            if target_words
            else ""
        )
        section_details = (
            f"小节标题：{section_title}\n"
            f"目录层级：{section_level}\n"
            f"写作思路（最高优先级，只围绕它写，不自行扩展新分论点）：{section_goal}\n"
            f"本章强化提示词：{strength_rule}\n"
            f"篇幅行为：正文应围绕写作思路充分展开，避免明显短促或重复灌水；具体字数由系统代码统计和修正，AI 不得自行计数、说明或自评字数。\n"
            f"段落行为：{paragraph_rule}\n"
            f"内部长度控制：{countdown_prompt}\n"
            f"已选择写作 Skill：未选择；不得加载或套用任何 Skill 专属设置。"
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
            "previous_summaries": previous_summaries or "暂无",
            "generated_summaries": generated_summaries or "暂无",
            "terminology_context": terminology or "暂无",
            "rag_context": rag_context or "暂无可用参考资料。若无资料，请基于通用学术知识谨慎写作，不编造具体数据来源。",
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
            raise ValueError(
                f"全局章节提示词缺少或写错变量：{{{missing}}}。请从左上角“好编辑”隐藏入口进入全局设置，恢复默认或修正提示词变量。"
            ) from exc
        return f"{ACADEMIC_MONOGRAPH_SYSTEM_PROMPT}\n\n{chapter_strength_rules}\n\n{evidence_rules}\n\n{user_prompt}"

    def _build_chapter_intro(
        self,
        project: ProjectKnowledgeBase,
        chapter: Chapter,
        chapter_number: int,
        outline_tree: str,
    ) -> str:
        summary = (chapter.summary or "").strip()
        if summary:
            base = summary
        else:
            base = (
                f"本章围绕{chapter.title}展开，依据章节目录依次讨论相关概念、技术脉络、应用场景与实践问题。"
            )
        return (
            f"本章导语：{base} 本章按照{format_chapter_label(chapter_number)}的目录结构展开论述，"
            "先界定核心概念与问题边界，再结合相关研究资料、行业实践和技术演进进行分析。"
            "全文保持中立、客观、可出版的学术专著表达方式，避免主观化和口语化表述。"
        )

    def _build_chapter_back_matter(
        self,
        project: ProjectKnowledgeBase,
        chapter: Chapter,
        chapter_number: int,
        content_parts: List[str],
        terminology: str,
    ) -> str:
        summary_block = (
            "## 本章小结\n\n"
            f"本章围绕{chapter.title}展开系统论述，按照既定目录完成了核心概念、关键问题、技术路径和应用价值的分析。"
            "本章内容在结构上紧扣当前章节主题，在材料使用上强调术语一致、证据审慎和观点中立。"
            "本章小结仅概括本章已经完成的论述内容，不对后续章节作预告。"
        )
        if not self._is_final_chapter(project, chapter_number):
            return summary_block

        refs = self._build_reference_list(project, chapter, include_all=True)
        reference_block = "## 全书参考文献\n\n" + (
            "\n".join(refs) if refs else "（全书暂无参考文献）"
        )
        terms = self._extract_terms_for_glossary(
            chapter, terminology, project=project, include_all=True
        )
        glossary_lines = [f"- **{term}**：{definition}" for term, definition in terms]
        glossary_block = "## 附录A 术语表\n\n" + (
            "\n".join(glossary_lines) if glossary_lines else "（全书暂无术语表）"
        )
        return summary_block + "\n\n" + reference_block + "\n\n" + glossary_block

    def _is_final_chapter(self, project: ProjectKnowledgeBase, chapter_number: int) -> bool:
        try:
            chapter_numbers = [int(num) for num in project.chapters.keys()]
        except Exception:
            chapter_numbers = []
        return bool(chapter_numbers) and int(chapter_number) == max(chapter_numbers)

    def _extract_terms_for_glossary(
        self,
        chapter: Chapter,
        terminology: str,
        project: Optional[ProjectKnowledgeBase] = None,
        include_all: bool = False,
    ) -> List[tuple[str, str]]:
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

    def _build_reference_list(
        self,
        project: ProjectKnowledgeBase,
        chapter: Chapter,
        include_all: bool = False,
    ) -> List[str]:
        refs = []
        try:
            citations = (
                list(getattr(project, "citations", []) or [])
                if include_all
                else project.get_citations_for_chapter(
                    getattr(chapter, "chapter_number", 0) or 0
                )
            )
        except Exception:
            citations = []
        seen = set()
        for citation in citations:
            formatted = (getattr(citation, "formatted_ref", "") or "").strip()
            if formatted:
                ref_text = formatted
            else:
                source = (getattr(citation, "source", "") or "").strip()
                quote = (
                    getattr(citation, "quote_original", "")
                    or getattr(citation, "sentence", "")
                    or ""
                ).strip()
                if not source and not quote:
                    continue
                ref_text = f"{source or '来源待核验'}：{quote or '原文摘录待核验'}"
            if ref_text in seen:
                continue
            seen.add(ref_text)
            refs.append(f"- [{len(refs) + 1}] {ref_text}")
        return refs

    def _get_rag_context(
        self, query: str, project: Optional[ProjectKnowledgeBase] = None
    ) -> str:
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

        library_context = self._get_project_material_context(
            project, query=query, limit=5000, max_chunks=8
        )
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
        if project is None:
            return ""
        documents_by_id = {
            str(getattr(doc, "id", "")): doc
            for doc in (getattr(project, "source_documents", []) or [])
            if str(getattr(doc, "id", "")).strip()
        }
        query_terms = [
            term
            for term in re.split(r"[\s，,。；;：:、（）()]+", str(query or ""))
            if len(term) >= 2
        ]
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

    # ---------- 生成与重试 ----------
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
        attempts = []
        provider = getattr(self.llm_client, "llm_provider", "")
        if provider != "custom" and hasattr(self.llm_client, "stream_content"):
            attempts.append(("stream", prompt, max_tokens, 0.65, "正在流式生成"))
        attempts.extend([
            ("generate", prompt, max_tokens, 0.60, "流式受阻，正在非流式重试"),
            (
                "generate",
                prompt,
                max(1800, min(max_tokens, 12000)),
                0.45,
                "正在稳定 token 重试",
            ),
            (
                "generate",
                self._build_compact_retry_prompt(prompt, section_title, target_words),
                max(1800, min(max_tokens, 10000)),
                0.35,
                "正在使用精简提示重试",
            ),
        ])

        last_error = ""
        for attempt_index, (mode, attempt_prompt, attempt_tokens, temperature, label) in enumerate(
            attempts, start=1
        ):
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
                    content_callback(
                        f"_{label}（第 {attempt_index}/{len(attempts)} 次）..._",
                        section_title,
                        generated_index,
                        total_sections,
                    )

                if mode == "stream":
                    chunks = []
                    for chunk in self.llm_client.stream_content(
                        attempt_prompt, max_tokens=attempt_tokens, temperature=temperature
                    ):
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
                    content = self.llm_client.generate_content(
                        attempt_prompt, max_tokens=attempt_tokens, temperature=temperature
                    )
                    if content:
                        self._emit_content_callback(
                            content_callback,
                            str(content),
                            section_title,
                            target_words,
                            generated_index,
                            total_sections,
                        )

                content = self._strip_duplicate_heading(
                    self._sanitize_model_output(content, section_title), section_title
                )
                if self._has_real_body_content(content):
                    return content
                last_error = "模型返回为空或正文质量不足"
                self.logger.warning(
                    "Section %s attempt %s returned no valid body.", section_title, attempt_index
                )
            except Exception as e:
                last_error = str(e)
                self.logger.warning(
                    "Section %s attempt %s failed: %s", section_title, attempt_index, e
                )

        diagnostics = []
        if last_error:
            diagnostics.append(f"最后错误：{last_error}")
        client_error = getattr(self.llm_client, "last_error", "")
        if client_error and client_error not in last_error:
            diagnostics.append(f"客户端错误：{client_error}")
        preview = getattr(self.llm_client, "last_response_preview", "")
        if preview:
            diagnostics.append(f"响应预览：{preview[:300]}")
        self.logger.error(
            "Section %s exhausted retries. %s", section_title, " | ".join(diagnostics)
        )
        return ""

    def _build_compact_retry_prompt(
        self, original_prompt: str, section_title: str, target_words: int
    ) -> str:
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

    # ---------- 质量门禁（已移除 Skill，直接返回原内容） ----------
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
        # 无 Skill 时直接返回原内容
        return content

    @staticmethod
    def _quality_report_rank(report: Dict[str, object]) -> tuple[int, int, int, int]:
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

    # ---------- 字数压缩 / 补写（硬编码 ±5%） ----------
    def _build_word_count_compress_prompt(
        self,
        content: str,
        prompt: str,
        target_words: int,
        current_words: int,
        pressure_level: int = 1,
    ) -> str:
        delete_words = max(1, current_words - target_words)
        strict_upper = int(round(target_words * 1.05))
        hard_upper = strict_upper
        pressure_text = self._word_count_pressure_text(pressure_level, "compress")
        countdown_prompt = self._countdown_marker_prompt(
            target_words, chunk_size=50, mode="compress"
        )
        return f"""{prompt}

## 已生成正文（系统统计后超出目标范围）
{content}

## 系统字数裁判结果
目标约 {target_words} 字；系统统计当前约 {current_words} 字；需要删约 {delete_words} 字。
目标合格带：不高于 {strict_upper} 字；硬红线：不高于 {hard_upper} 字。

## 压缩指令（只给你内部执行，禁止写进正文）
{pressure_text}

{countdown_prompt}

## 压缩任务
请返回压缩后的完整正文，不要只返回删减说明。请在不新增事实、不新增引用、不输出标题的前提下精简冗余表述；不得截断半句话。
要求：
1. 保留核心概念、论证链条、实施路径、风险边界和已有可追溯来源。
2. 删除重复铺陈、空泛过渡、规划说明和“写作思路/资料依据/证据边界/后续补充”等非正文内容。
3. 少用双引号，普通判断句和概念直接陈述。
4. 只输出压缩后的完整正文段落，每段以两个全角空格开头；可按论证自然转向分段，不要追求段落长度整齐。
5. 不要输出字数统计、偏差率、自评、评分、修改说明或过程说明。
6. 压缩后字数必须 ≤ {hard_upper} 字，否则任务直接失败。当标记进入最后20%区间时必须立即收束，只输出结论性语句，不得再展开任何新论点或举例。。
"""

    def generate_with_token_cap(
        self,
        prompt: str,
        target_words: int,
        history: List[Tuple[int, int]],
        section_title: str = "",
    ) -> str:
        max_tokens = self._estimate_token_cap(target_words, history, safety_factor=0.9)
        self.logger.info(
            "Token-capped word repair for section %s: target=%s max_tokens=%s history=%s",
            section_title,
            target_words,
            max_tokens,
            history,
        )
        return self.llm_client.generate_content(
            prompt,
            max_tokens=max_tokens,
            temperature=0.5,
            raw_attempt_limit=1,
        )

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
        pressure_level: int = 1,
    ) -> str:
        strict_upper = int(round(target_words * 1.05))
        if current_words <= strict_upper:
            return content
        compress_prompt = self._build_word_count_compress_prompt(
            content, prompt, target_words, current_words, pressure_level=pressure_level
        )
        if content_callback:
            content_callback(
                "_字数超出目标范围，正在压缩正文..._",
                section_title,
                generated_index,
                total_sections,
            )
        try:
            compressed = self.llm_client.generate_content(
                compress_prompt,
                max_tokens=max(700, min(5000, int(target_words * 1.25))),
                temperature=0.25,
            )
            compressed = self._strip_duplicate_heading(
                self._sanitize_model_output(compressed, section_title), section_title
            )
            compressed_words = self._count_words(compressed)
            if (
                self._has_real_body_content(compressed)
                and self._word_count_delta_score(compressed_words, target_words)
                < self._word_count_delta_score(current_words, target_words)
            ):
                self._emit_content_callback(
                    content_callback,
                    compressed,
                    section_title,
                    target_words,
                    generated_index,
                    total_sections,
                )
                return compressed
        except Exception as e:
            self.logger.warning(
                "Failed to compress section %s to target words: %s", section_title, e
            )
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
        pressure_level: int = 1,
    ) -> str:
        need_words = max(1, target_words - current_words)
        strict_lower = int(round(target_words * 0.95))
        hard_lower = strict_lower
        pressure_text = self._word_count_pressure_text(pressure_level, "expand")
        countdown_prompt = self._countdown_marker_prompt(
            target_words, chunk_size=50, mode="expand"
        )
        expand_prompt = f"""{prompt}

## 已生成正文（系统统计后低于目标范围）
{base_content}

## 系统字数裁判结果
目标约 {target_words} 字；系统统计当前约 {current_words} 字；需要补约 {need_words} 字。
目标合格带：不低于 {strict_lower} 字；硬红线：不低于 {hard_lower} 字。

## 补写指令（只给你内部执行，禁止写进正文）
{pressure_text}

{countdown_prompt}

## 补写任务
请返回补写后的完整正文，不要只返回追加段落。请在不重复已有内容、不输出标题的前提下，扩展论证的概念边界、机制分析、适用场景或风险条件。
要求：
1. 保留原文核心内容和事实边界，不编造新来源、新数据或新引用。
2. 只围绕当前小节写作思路补强论证，不新增无关分论点。
3. 每段以两个全角空格开头；可按论证自然转向分段，不要追求段落长度整齐。
4. 不要输出字数统计、偏差率、自评、评分、修改说明或过程说明。
5. 只输出补写后的完整正文。
6. 必须补到目标字数 ±5% 以内，不允许低于 {hard_lower} 字硬红线。
"""
        try:
            rewrite_chunks = []
            if hasattr(self.llm_client, "stream_content"):
                for chunk in self.llm_client.stream_content(
                    expand_prompt,
                    max_tokens=max(1800, min(12000, int(max(need_words, target_words) * 4.0))),
                    temperature=0.6,
                ):
                    if chunk:
                        rewrite_chunks.append(str(chunk))
                        self._emit_content_callback(
                            content_callback,
                            "".join(rewrite_chunks),
                            section_title,
                            target_words,
                            generated_index,
                            total_sections,
                        )
                rewritten = "".join(rewrite_chunks)
            else:
                rewritten = self.llm_client.generate_content(
                    expand_prompt,
                    max_tokens=max(1800, min(12000, int(max(need_words, target_words) * 4.0))),
                    temperature=0.6,
                )
            rewritten = self._strip_duplicate_heading(
                self._sanitize_model_output(rewritten, section_title), section_title
            )
            rewritten_words = self._count_words(rewritten)
            if (
                self._has_real_body_content(rewritten)
                and self._word_count_delta_score(rewritten_words, target_words)
                < self._word_count_delta_score(current_words, target_words)
            ):
                return rewritten.strip()
        except Exception as e:
            self.logger.warning(
                "Failed to expand section %s to target words: %s", section_title, e
            )
        return base_content

    # ---------- 尾句补全 ----------
    def _ends_with_sentence_terminal(self, content: str) -> bool:
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
            content_callback(
                "_检测到正文尾句未闭合，正在只追加续写补全..._",
                section_title,
                generated_index,
                total_sections,
            )
        try:
            addition = self.llm_client.generate_content(
                completion_prompt,
                max_tokens=max(1200, min(4000, int(max(target_words, 400) * 1.5))),
                temperature=0.35,
            )
            addition = self._strip_duplicate_heading(
                self._sanitize_model_output(addition, section_title), section_title
            )
            if addition:
                completed = str(content or "").rstrip() + str(addition).lstrip()
                self._emit_content_callback(
                    content_callback,
                    completed,
                    section_title,
                    target_words,
                    generated_index,
                    total_sections,
                )
                return completed
        except Exception as e:
            self.logger.warning(
                "Failed to complete truncated tail for section %s: %s", section_title, e
            )
        return content

    # ---------- 输出净化 ----------
    def _sanitize_model_output(self, content: str, section_title: str) -> str:
        if not content:
            return ""
        text = str(content).strip()
        html_signals = [
            "<!doctype html", "<html", "</html>", "<head", "<body", "<title>",
            "<script", "<iframe", "HubLinuxDO",
        ]
        lowered = text.lower()
        if any(signal.lower() in lowered for signal in html_signals):
            self.logger.warning("Invalid HTML/error-page response while writing %s", section_title)
            return ""
        text = re.sub(
            r"```(?:html|xml|javascript|js)?\s*.*?</(?:html|body|script|iframe)>\s*```",
            "",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        text = re.sub(r"(?im)^\s*Section\s+\d+\s*:\s*Write\s+this\s+chapter.*$", "", text)
        text = re.sub(r"(?is)<script.*?</script>|<iframe.*?</iframe>", "", text)
        text = re.sub(r"(?im)^\s*(?:assistant\s*){1,4}[:：\-—\s]*", "", text)
        text = re.sub(r"(?im)^\s*(?:user|system)\s*[:：\-—]\s*", "", text)
        text = re.sub(r"(?i)(?<=\n)(?:assistant\s*){2,}(?=\S)", "", text)
        text = re.sub(r"(?i)^(?:assistant\s*){2,}(?=\S)", "", text)
        # 预览阶段不删除倒计时标记，留给 _emit_content_callback 中可见
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

    # ---------- 语言规范修正 ----------
    def _language_norm_issues(self, text: str) -> List[str]:
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
            content_callback(
                "_检测到语言规范问题，正在定向改写一次..._",
                section_title,
                generated_index,
                total_sections,
            )
        try:
            rewritten = self.llm_client.generate_content(
                rewrite_prompt,
                max_tokens=max(
                    1200,
                    min(12000, int(max(target_words, self._count_words(normalized), 400) * 2.5)),
                ),
                temperature=0.2,
            )
            rewritten = self._strip_duplicate_heading(
                self._sanitize_model_output(rewritten, section_title), section_title
            )
            if self._has_real_body_content(rewritten):
                rewritten = rewritten.replace("制定", "制订").replace("作出", "做出").replace("提升", "提高")
                self._emit_content_callback(
                    content_callback,
                    rewritten,
                    section_title,
                    target_words or self._count_words(rewritten),
                    generated_index,
                    total_sections,
                )
                return rewritten
        except Exception as e:
            self.logger.warning(
                "Failed to rewrite language norms for section %s: %s", section_title, e
            )
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
            content_callback(
                "_检测到双引号过多，正在定向改写一次..._",
                section_title,
                generated_index,
                total_sections,
            )
        try:
            rewritten = self.llm_client.generate_content(
                rewrite_prompt,
                max_tokens=max(1200, min(12000, int(max(target_words, char_count) * 2.5))),
                temperature=0.25,
            )
            rewritten = self._strip_duplicate_heading(
                self._sanitize_model_output(rewritten, section_title), section_title
            )
            if self._has_real_body_content(rewritten):
                self._emit_content_callback(
                    content_callback,
                    rewritten,
                    section_title,
                    target_words or char_count,
                    generated_index,
                    total_sections,
                )
                return rewritten
        except Exception as e:
            self.logger.warning(
                "Failed to rewrite quotes for section %s: %s", section_title, e
            )
        return content

    # ---------- 字数闭环修复 ----------
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
        if not content or not target_words:
            return content or ""
        repaired = str(content).strip()
        history: List[Tuple[int, int]] = []
        self._record_generation_history(history, repaired)

        strict_lower = int(round(target_words * 0.95))
        strict_upper = int(round(target_words * 1.05))
        hard_lower = strict_lower
        hard_upper = strict_upper
        max_rounds = 2

        last_compress_prompt = ""
        best_text = repaired
        best_score = self._word_count_delta_score(self._count_words(repaired), target_words)

        for round_index in range(max_rounds):
            current_words = self._count_words(repaired)
            if strict_lower <= current_words <= strict_upper:
                break
            if current_words < strict_lower:
                next_text = self._expand_to_target_words(
                    base_content=repaired,
                    prompt=prompt,
                    section_title=section_title,
                    target_words=target_words,
                    current_words=current_words,
                    content_callback=content_callback,
                    generated_index=generated_index,
                    total_sections=total_sections,
                    pressure_level=round_index + 1,
                )
            else:
                last_compress_prompt = self._build_word_count_compress_prompt(
                    content=repaired,
                    prompt=prompt,
                    target_words=target_words,
                    current_words=current_words,
                    pressure_level=round_index + 1,
                )
                next_text = self._compress_to_target_words(
                    content=repaired,
                    prompt=prompt,
                    section_title=section_title,
                    target_words=target_words,
                    current_words=current_words,
                    content_callback=content_callback,
                    generated_index=generated_index,
                    total_sections=total_sections,
                    pressure_level=round_index + 1,
                )
            next_text = self._strip_duplicate_heading(
                self._sanitize_model_output(next_text, section_title), section_title
            )
            if self._has_real_body_content(next_text):
                self._record_generation_history(history, next_text)
            if not self._has_real_body_content(next_text) or next_text.strip() == repaired.strip():
                break
            repaired = next_text.strip()
            repaired_words = self._count_words(repaired)
            repaired_score = self._word_count_delta_score(repaired_words, target_words)
            if repaired_score < best_score:
                best_text = repaired
                best_score = repaired_score
            if strict_lower <= repaired_words <= strict_upper:
                break

        if self._word_count_delta_score(self._count_words(repaired), target_words) > best_score:
            repaired = best_text
        final_words = self._count_words(repaired)

        # 最终仍低于硬红线：再强制扩展一次
        if final_words < hard_lower:
            intensified = self._expand_to_target_words(
                base_content=repaired,
                prompt=prompt,
                section_title=section_title,
                target_words=target_words,
                current_words=final_words,
                content_callback=content_callback,
                generated_index=generated_index,
                total_sections=total_sections,
                pressure_level=max_rounds,
            )
            intensified = self._strip_duplicate_heading(
                self._sanitize_model_output(intensified, section_title), section_title
            )
            intensified_words = self._count_words(intensified)
            if (
                self._has_real_body_content(intensified)
                and self._word_count_delta_score(intensified_words, target_words)
                < self._word_count_delta_score(final_words, target_words)
            ):
                repaired = intensified.strip()
                final_words = intensified_words
                self._emit_content_callback(
                    content_callback,
                    repaired,
                    section_title,
                    target_words,
                    generated_index,
                    total_sections,
                )
        # 最终仍高于硬红线：用 token 硬限制压缩
        if final_words > hard_upper:
            token_prompt = last_compress_prompt or self._build_word_count_compress_prompt(
                content=repaired,
                prompt=prompt,
                target_words=target_words,
                current_words=final_words,
                pressure_level=max_rounds,
            )
            capped = self.generate_with_token_cap(
                token_prompt, target_words, history, section_title=section_title
            )
            capped = self._strip_duplicate_heading(
                self._sanitize_model_output(capped, section_title), section_title
            )
            capped_words = self._count_words(capped)
            if (
                self._has_real_body_content(capped)
                and self._word_count_delta_score(capped_words, target_words)
                < self._word_count_delta_score(final_words, target_words)
            ):
                self._record_generation_history(history, capped)
                repaired = capped.strip()
                final_words = capped_words
                self._emit_content_callback(
                    content_callback,
                    repaired,
                    section_title,
                    target_words,
                    generated_index,
                    total_sections,
                )

        # 软失败标记（不阻塞）
        if not (hard_lower <= final_words <= hard_upper):
            self.logger.warning(
                "Word count repair still outside hard range for section %s: final=%s target=%s",
                section_title,
                final_words,
                target_words,
            )
        return repaired

    # ---------- 段落整形 ----------
    def _split_sentences(self, text: str) -> List[str]:
        clean = re.sub(r"\s*\n\s*", "", str(text or "").strip())
        if not clean:
            return []
        return [s.strip() for s in re.split(r"(?<=[。！？；.!?;])", clean) if s.strip()]

    def enforce_paragraph_shape(self, text: str) -> str:
        content = self._strip_duplicate_heading(text, "")
        content = re.sub(r"\n{3,}", "\n\n", str(content or "").strip())
        if not content:
            return ""

        min_sentences_per_paragraph = 5
        raw_paragraphs = [p.strip() for p in re.split(r"\n\s*\n", content) if p.strip()]
        if (
            2 <= len(raw_paragraphs) <= 3
            and all(len(self._split_sentences(p)) >= min_sentences_per_paragraph for p in raw_paragraphs)
        ):
            return "\n\n".join(raw_paragraphs).strip()

        sentences = self._split_sentences(content)
        if len(sentences) < min_sentences_per_paragraph * 2:
            return "".join(sentences).strip() if sentences else content

        transition_words = (
            "与此同时", "进一步看", "不过", "因此", "然而", "从实践层面", "从技术层面",
            "从制度层面", "相较而言", "由此", "换言之", "另一方面", "更重要的是",
            "在这一背景下", "基于此", "反过来看", "具体而言", "与此不同", "在风险层面",
            "从治理角度", "从应用场景看", "问题在于", "这种变化意味着",
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
        return self.enforce_paragraph_shape(content)

    def _shape_preview_content(self, content: str, section_title: str, target_words: int) -> str:
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
        # 预览阶段保留倒计时标记，不做删除
        text = self.check_and_rewrite_language_norms(
            text, section_title=section_title, target_words=target_words
        )
        content_callback(
            self._shape_preview_content(text, section_title, target_words),
            section_title,
            generated_index,
            total_sections,
        )

    def _ensure_fullwidth_paragraph_indent(self, content: str) -> str:
        paragraphs = [
            p.strip() for p in re.split(r"\n\s*\n", str(content or "").strip()) if p.strip()
        ]
        formatted: list[str] = []
        for paragraph in paragraphs:
            if paragraph.startswith("#") or paragraph.lstrip().startswith("_"):
                formatted.append(paragraph)
            else:
                formatted.append("　　" + paragraph.lstrip("　 "))
        return "\n\n".join(formatted).strip("\r\n ")

    def _finalize_section_content(
        self, content: str, section_title: str, target_words: int
    ) -> str:
        text = self._sanitize_model_output(content, section_title)
        text = self._strip_duplicate_heading(text, section_title) if text else ""
        text = self.check_and_rewrite_language_norms(
            text, section_title=section_title, target_words=target_words
        )
        text = self._enforce_paragraph_shape(text, target_words)
        # 最终写入正文前清除倒计时标记
        text = self._strip_countdown_markers(text)
        return self._ensure_fullwidth_paragraph_indent(text)

    def _count_words(self, text: str) -> int:
        return len(re.findall(r"[\u4e00-\u9fff]", text or ""))

    def _has_real_body_content(self, content: str) -> bool:
        if not content or not str(content).strip():
            return False
        body_lines = [
            line.strip()
            for line in str(content).splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        body = "\n".join(body_lines).strip()
        if not body:
            return False
        lowered = body.lower()
        invalid_signals = ["<!doctype html", "<html", "</html>", "traceback", "error:", "生成失败"]
        return not any(signal in lowered for signal in invalid_signals)

    # ---------- 旧版场景写作兼容 ----------
    def _write_legacy_scene_chapter(
        self,
        project_knowledge_base: ProjectKnowledgeBase,
        chapter_number: int,
        chapter: Chapter,
    ) -> str:
        if not chapter.scenes:
            console.print(
                f"[yellow]No sections/scenes found for Chapter {chapter_number}. Creating a fallback writing unit.[/yellow]"
            )
            default_scene = Scene(
                scene_number=1,
                summary=chapter.summary or "Write this chapter as an academic chapter.",
                characters=[],
                setting="",
                goal="Complete the chapter",
                emotional_beat="",
            )
            chapter.scenes.append(default_scene)

        ordered_scenes = sorted(chapter.scenes, key=lambda s: s.scene_number)
        scene_contents = []
        for scene in ordered_scenes:
            console.print(
                f"[cyan]Creating fallback section {scene.scene_number} of {len(ordered_scenes)}...[/cyan]"
            )
            scene_title = (
                f"Section {scene.scene_number}: {scene.summary[:30]}..."
                if len(scene.summary) > 30
                else f"Section {scene.scene_number}: {scene.summary}"
            )
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
                total_scenes=len(ordered_scenes),
            )
            scene_prompt = (
                f"{ACADEMIC_MONOGRAPH_SYSTEM_PROMPT}\n\n{scene_prompt}\n\n"
                "请按学术专著强制规范生成本写作单元正文。每个自然段必须以两个全角空格开头，"
                "不输出HTML/XML/JS/代码/注释/指令残留；不得编造数据、案例、文献、法规、标准编号、人名、机构名、时间、地点；"
                "不得输出‘请搜索’‘请查询’‘详见某网页’等虚假操作表述；信息不足时必须明确写出‘【信息缺失】需要您提供……’。"
            )
            scene_content = self.llm_client.generate_content(scene_prompt, max_tokens=3000)
            if not scene_content:
                scene_content = f"[{scene_title} content unavailable]"
            if not scene_content.startswith(f"**{scene_title}**") and not scene_content.startswith(
                f"# {scene_title}"
            ):
                scene_content = f"**{scene_title}**\n\n{scene_content}"
            scene_contents.append(scene_content)

        legacy_text = (
            f"# {format_chapter_label(chapter_number, chapter.title)}\n\n"
            + "\n\n".join(scene_contents)
            + "\n"
        )
        legacy_text, _, _ = finalize_academic_chapter(
            legacy_text, target_words=getattr(chapter, "word_count", 0) or 0
        )
        return legacy_text
