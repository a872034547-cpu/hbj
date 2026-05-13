"""Project quality summary service.

This module provides a small, side-effect-free service for aggregating
project-level quality indicators from the in-memory knowledge base.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from libriscribe.knowledge_base import Chapter, ProjectKnowledgeBase


class QualityService:
    """Aggregate project quality metrics from a ProjectKnowledgeBase."""

    @staticmethod
    def summarize_project_quality(project: ProjectKnowledgeBase) -> Dict[str, Any]:
        """Return project-level quality counters and normalized scores.

        Scores use a 0-100 scale:
        - coverage_score: evidence chunks per writing unit, capped at 100.
        - citation_score: citations per writing unit, capped at 100.
        - completion_score: completed writing units divided by total writing units.

        A writing unit is a chapter section when sections exist. For legacy
        projects without sections, each chapter is treated as one writing unit.
        """
        chapters = project.chapters or {}
        chapter_count = len(chapters)
        writing_unit_count = QualityService._count_writing_units(chapters)
        completed_unit_count = QualityService._count_completed_units(chapters)

        source_count = len(project.source_documents or [])
        evidence_chunk_count = len(project.evidence_chunks or [])
        citation_count = len(project.citations or [])

        coverage_score = QualityService._score_ratio(
            evidence_chunk_count,
            writing_unit_count,
            target_per_unit=2,
        )
        citation_score = QualityService._score_ratio(
            citation_count,
            writing_unit_count,
            target_per_unit=1,
        )
        completion_score = QualityService._score_ratio(
            completed_unit_count,
            writing_unit_count,
            target_per_unit=1,
        )

        return {
            # 稳定商业化指标键：供 Web 页面、测试与未来 API 使用。
            "chapters": chapter_count,
            "writing_units": writing_unit_count,
            "completed_units": completed_unit_count,
            "sources": source_count,
            "evidence_chunks": evidence_chunk_count,
            "citations": citation_count,
            "coverage_score": coverage_score,
            "citation_score": citation_score,
            "completion_score": completion_score,
            # 兼容内部描述性字段：避免后续服务调用迁移时破坏旧代码。
            "chapter_count": chapter_count,
            "writing_unit_count": writing_unit_count,
            "completed_unit_count": completed_unit_count,
            "source_count": source_count,
            "evidence_chunk_count": evidence_chunk_count,
            "citation_count": citation_count,
        }

    @staticmethod
    def export_readiness_report(chapters: List[Dict[str, Any]]) -> Dict[str, Any]:
        """导出前质量体检：检查最终交付稿是否仍残留过程信息、标题异常或基础内容缺口。

        该方法只做静态检查，不修改正文，可用于审校页、导出页和测试。
        """
        warnings: List[Dict[str, Any]] = []
        chapter_count = len(chapters or [])
        total_words = 0
        duplicate_heading_count = 0
        process_artifact_count = 0
        markdown_artifact_count = 0
        empty_chapter_count = 0

        for index, chapter in enumerate(chapters or [], start=1):
            number = chapter.get("number") or chapter.get("chapter_number") or index
            title = str(chapter.get("display_title") or chapter.get("title") or f"第{number}章")
            content = str(chapter.get("content") or "")
            word_count = QualityService._count_manuscript_words(content)
            total_words += word_count

            if not content.strip() or word_count < 300:
                empty_chapter_count += 1
                warnings.append({"级别": "严重", "章节": title, "问题": "章节正文为空或明显偏短", "建议": "返回写章节页重新生成或补写。"})

            if QualityService._has_duplicate_chapter_heading(content, number, title):
                duplicate_heading_count += 1
                warnings.append({"级别": "高", "章节": title, "问题": "正文中疑似残留重复章标题", "建议": "导出前应只保留导出器插入的章标题。"})

            artifact_hits = QualityService._process_artifact_hits(content)
            if artifact_hits:
                process_artifact_count += len(artifact_hits)
                warnings.append({"级别": "高", "章节": title, "问题": f"残留过程/评分信息：{', '.join(artifact_hits[:3])}", "建议": "导出前清理 AI 自评、评分表、生成日志和元数据。"})

            markdown_hits = QualityService._markdown_artifact_hits(content)
            if markdown_hits:
                markdown_artifact_count += len(markdown_hits)
                warnings.append({"级别": "中", "章节": title, "问题": f"残留 Markdown/代码标记：{', '.join(markdown_hits[:3])}", "建议": "确认 DOCX/PDF 导出器能正确转换或先清理。"})

        severe = sum(1 for item in warnings if item.get("级别") == "严重")
        high = sum(1 for item in warnings if item.get("级别") == "高")
        medium = sum(1 for item in warnings if item.get("级别") == "中")
        penalty = severe * 30 + high * 18 + medium * 8
        readiness_score = max(0, min(100, 100 - penalty))
        status = "通过" if readiness_score >= 85 and not severe and not high else "建议复核" if readiness_score >= 60 else "不建议导出"

        return {
            "status": status,
            "readiness_score": readiness_score,
            "chapter_count": chapter_count,
            "total_words": total_words,
            "warnings": warnings,
            "warning_count": len(warnings),
            "severe_warnings": severe,
            "high_warnings": high,
            "medium_warnings": medium,
            "duplicate_heading_count": duplicate_heading_count,
            "process_artifact_count": process_artifact_count,
            "markdown_artifact_count": markdown_artifact_count,
            "empty_chapter_count": empty_chapter_count,
        }

    @staticmethod
    def manuscript_quality_report(chapters: List[Dict[str, Any]], *, citations: List[Any] | None = None) -> Dict[str, Any]:
        """专著正文质量静态体检：面向生成质量，不改变正文。

        重点检查内容深度、疑似伪引用、无来源事实句、禁用语体和结构标题密度。
        """
        issues: List[Dict[str, Any]] = []
        total_words = 0
        citation_count = len(citations or [])
        has_verified_citation = any(str(getattr(c, "status", "") or "") == "verified" for c in (citations or []))
        content_depth_flags = 0
        pseudo_citation_flags = 0
        unsupported_claim_flags = 0
        style_flags = 0
        structure_flags = 0

        for index, chapter in enumerate(chapters or [], start=1):
            title = str(chapter.get("display_title") or chapter.get("title") or f"第{index}章")
            content = str(chapter.get("content") or "")
            words = QualityService._count_manuscript_words(content)
            total_words += words
            paragraphs = QualityService._body_paragraphs(content)
            headings = [line.strip() for line in content.splitlines() if line.strip().startswith("#")]

            if paragraphs and words / max(len(paragraphs), 1) < 45:
                content_depth_flags += 1
                issues.append({"级别": "中", "章节": title, "问题": "段落平均信息量偏低，疑似短句堆叠", "建议": "按概念界定、机制分析、实践路径、边界风险补充论证。"})

            depth_keywords = ["概念", "机制", "路径", "问题", "风险", "边界", "实践", "体系", "方法", "价值"]
            if words >= 800 and sum(1 for keyword in depth_keywords if keyword in content) < 3:
                content_depth_flags += 1
                issues.append({"级别": "中", "章节": title, "问题": "专著论证维度不足", "建议": "补充概念、机制、路径、风险、价值等专著分析维度。"})

            if len(headings) <= 1 and words >= 1200:
                structure_flags += 1
                issues.append({"级别": "中", "章节": title, "问题": "长章节缺少小节标题结构", "建议": "确认是否丢失节、三级或四级目录标题。"})

            pseudo_hits = QualityService._pseudo_citation_hits(content, citation_count)
            if pseudo_hits:
                pseudo_citation_flags += len(pseudo_hits)
                issues.append({"级别": "高", "章节": title, "问题": f"疑似伪引用或无绑定引用：{', '.join(pseudo_hits[:3])}", "建议": "删除伪引用，或在资料库中绑定真实证据与引用。"})

            unsupported_hits = QualityService._unsupported_claim_hits(content, has_verified_citation)
            if unsupported_hits:
                unsupported_claim_flags += len(unsupported_hits)
                issues.append({"级别": "高", "章节": title, "问题": f"疑似无来源事实句：{', '.join(unsupported_hits[:3])}", "建议": "补充来源、改写为审慎分析，或标记【信息缺失】。"})

            style_hits = QualityService._academic_style_hits(content)
            if style_hits:
                style_flags += len(style_hits)
                issues.append({"级别": "中", "章节": title, "问题": f"专著语体风险：{', '.join(style_hits[:3])}", "建议": "改为第三人称、客观、证据导向的学术表达。"})

        high = sum(1 for item in issues if item.get("级别") == "高")
        medium = sum(1 for item in issues if item.get("级别") == "中")
        score = max(0, min(100, 100 - high * 16 - medium * 7))
        status = "通过" if score >= 85 and high == 0 else "建议复核" if score >= 60 else "不建议进入最终导出"
        return {
            "status": status,
            "quality_score": score,
            "total_words": total_words,
            "issues": issues,
            "issue_count": len(issues),
            "high_issues": high,
            "medium_issues": medium,
            "content_depth_flags": content_depth_flags,
            "pseudo_citation_flags": pseudo_citation_flags,
            "unsupported_claim_flags": unsupported_claim_flags,
            "style_flags": style_flags,
            "structure_flags": structure_flags,
        }

    @staticmethod
    def section_quality_report(
        section_title: str,
        content: str,
        *,
        target_words: int = 0,
        citations: List[Any] | None = None,
    ) -> Dict[str, Any]:
        """小节级结构化质量复评：只体检不改文，供 AI 修订闭环选择最佳版本。"""
        text = str(content or "")
        target = int(target_words or 0)
        citation_count = len(citations or [])
        has_verified_citation = any(str(getattr(c, "status", "") or "") == "verified" for c in (citations or []))
        words = QualityService._count_manuscript_words(text)
        paragraphs = QualityService._body_paragraphs(text)

        pseudo_hits = QualityService._pseudo_citation_hits(text, citation_count)
        unsupported_hits = QualityService._unsupported_claim_hits(text, has_verified_citation)
        style_hits = QualityService._academic_style_hits(text)
        process_hits = QualityService._process_artifact_hits(text)
        markdown_hits = QualityService._markdown_artifact_hits(text)
        depth_keywords = ["概念", "机制", "路径", "问题", "风险", "边界", "实践", "体系", "方法", "价值", "治理", "评价"]
        depth_hits = [keyword for keyword in depth_keywords if keyword in text]

        hard_failures: List[str] = []
        soft_warnings: List[str] = []
        if pseudo_hits:
            hard_failures.append(f"疑似伪引用或无绑定引用：{', '.join(pseudo_hits[:4])}")
        if unsupported_hits:
            hard_failures.append(f"疑似无来源事实句：{', '.join(unsupported_hits[:4])}")
        if process_hits:
            hard_failures.append(f"残留过程/评分信息：{', '.join(process_hits[:4])}")
        if markdown_hits:
            hard_failures.append(f"残留 Markdown/HTML/JSON 标记：{', '.join(markdown_hits[:4])}")
        if words < 80:
            hard_failures.append("正文有效字数过短，缺少可出版论证内容")

        word_deviation = 0.0
        if target > 0:
            word_deviation = round((words - target) / max(target, 1), 4)
            if words < target * 0.62:
                soft_warnings.append("实际字数明显低于目标，论证可能偏薄")
            elif words > target * 1.85:
                soft_warnings.append("实际字数明显高于目标，可能影响章节节奏")
        if paragraphs and words / max(len(paragraphs), 1) < 45:
            soft_warnings.append("段落平均信息量偏低，疑似短句堆叠")
        if words >= 500 and len(depth_hits) < 3:
            soft_warnings.append("专著论证维度不足，应补足概念、机制、路径、风险、价值等层次")
        if style_hits:
            soft_warnings.append(f"专著语体风险：{', '.join(style_hits[:4])}")

        penalty = len(hard_failures) * 22 + len(soft_warnings) * 7
        if target > 0 and abs(word_deviation) > 0.55:
            penalty += 6
        quality_score = max(0, min(100, 100 - penalty))
        passed = not hard_failures and quality_score >= 78
        revision_instructions: List[str] = []
        revision_instructions.extend(hard_failures)
        revision_instructions.extend(soft_warnings[:6])
        if not revision_instructions:
            revision_instructions.append("正文通过程序体检，保持证据绑定、段落规范和学术专著语体。")

        return {
            "section_title": section_title,
            "passed": passed,
            "quality_score": quality_score,
            "word_count": words,
            "target_words": target,
            "word_deviation": word_deviation,
            "hard_failures": hard_failures,
            "soft_warnings": soft_warnings,
            "revision_instructions": revision_instructions,
            "metrics": {
                "pseudo_citation_hits": pseudo_hits,
                "unsupported_claim_hits": unsupported_hits,
                "style_hits": style_hits,
                "process_artifact_hits": process_hits,
                "markdown_artifact_hits": markdown_hits,
                "depth_hits": depth_hits,
                "paragraph_count": len(paragraphs),
            },
        }

    @staticmethod
    def _count_writing_units(chapters: Dict[int, Chapter]) -> int:
        section_count = sum(len(chapter.sections or []) for chapter in chapters.values())
        return section_count if section_count > 0 else len(chapters)

    @staticmethod
    def _count_completed_units(chapters: Dict[int, Chapter]) -> int:
        section_count = sum(len(chapter.sections or []) for chapter in chapters.values())

        if section_count > 0:
            return sum(
                1
                for chapter in chapters.values()
                for section in (chapter.sections or [])
                if QualityService._is_completed_status(section.status)
            )

        return sum(
            1
            for chapter in chapters.values()
            if QualityService._is_completed_status(chapter.status)
        )

    @staticmethod
    def _is_completed_status(status: str) -> bool:
        return (status or "").strip().lower() in {"completed", "reviewed", "word_count_soft_fail"}

    @staticmethod
    def _score_ratio(value: int, unit_count: int, target_per_unit: int) -> float:
        if unit_count <= 0 or target_per_unit <= 0:
            return 0.0

        score = value / (unit_count * target_per_unit) * 100
        return round(min(score, 100.0), 2)

    @staticmethod
    def _count_manuscript_words(text: str) -> int:
        chinese_chars = re.findall(r"[\u4e00-\u9fff]", text or "")
        english_words = re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)?", text or "")
        return len(chinese_chars) + len(english_words)

    @staticmethod
    def _has_duplicate_chapter_heading(content: str, number: Any, title: str) -> bool:
        lines = [line.strip() for line in (content or "").splitlines() if line.strip()]
        if not lines:
            return False
        chapter_heading_re = re.compile(r"^#\s*(?:第\s*[0-9一二三四五六七八九十百千]+\s*章|Chapter\s*\d+)", re.IGNORECASE)
        return any(chapter_heading_re.match(line) for line in lines[:3])

    @staticmethod
    def _process_artifact_hits(content: str) -> List[str]:
        patterns = {
            "自评结果": r"【自评结果】|【自评打分】",
            "评分/得分": r"(?:AI\s*)?评分\s*[：:]|得分\s*[：:]|总分\s*[：:]",
            "字数偏差": r"本章实际字数|目标字数.*偏差",
            "过程元数据": r"过程元数据|生成过程|响应预览|客户端错误",
            "质量自检表": r"评分表|质量自检|审核结果|评审结果",
        }
        return [label for label, pattern in patterns.items() if re.search(pattern, content or "", re.IGNORECASE)]

    @staticmethod
    def _markdown_artifact_hits(content: str) -> List[str]:
        hits: List[str] = []
        text = content or ""
        if "```" in text:
            hits.append("代码块")
        if re.search(r"<\/?(?:html|script|iframe|body|div)\b", text, re.IGNORECASE):
            hits.append("HTML标签")
        if re.search(r"\{\s*\"(?:score|metadata|prompt|response)\"\s*:", text, re.IGNORECASE):
            hits.append("JSON调试片段")
        return hits

    @staticmethod
    def _body_paragraphs(content: str) -> List[str]:
        return [
            line.strip()
            for line in (content or "").splitlines()
            if line.strip()
            and not line.strip().startswith(("#", "- ", "* ", "|", "【"))
            and not re.match(r"^\d+(?:\.\d+){0,3}\s+", line.strip())
        ]

    @staticmethod
    def _pseudo_citation_hits(content: str, citation_count: int) -> List[str]:
        hits: List[str] = []
        bracket_refs = sorted(set(re.findall(r"\[(\d+)\]", content or "")))
        for ref in bracket_refs[:5]:
            try:
                if int(ref) > citation_count:
                    hits.append(f"[{ref}]")
            except ValueError:
                continue
        if citation_count == 0 and re.search(r"\[\d+\]", content or ""):
            hits.append("正文出现[数字]引用但项目无引用记录")
        fake_reference_phrases = ["已有研究表明", "相关研究指出", "某报告指出", "数据显示", "标准规定", "政策明确提出"]
        for phrase in fake_reference_phrases:
            if phrase in (content or "") and not re.search(r"资料来源：|【信息缺失】|\[\d+\]", content or ""):
                hits.append(phrase)
        return list(dict.fromkeys(hits))

    @staticmethod
    def _unsupported_claim_hits(content: str, has_verified_citation: bool) -> List[str]:
        if has_verified_citation:
            return []
        patterns = {
            "具体年份断言": r"(?:19|20)\d{2}年.{0,18}(?:发布|出台|实施|增长|达到|超过|提出)",
            "百分比/数据断言": r"\d+(?:\.\d+)?%|增长率|占比|达到\d+",
            "法规标准断言": r"(?:GB|JGJ|DB|ISO|IEC|T/\w+)[\w\-/\.]*|《[^》]*(?:标准|规范|条例|办法|规定)[^》]*》",
            "机构报告断言": r"(?:住建部|国务院|国家发改委|统计局|行业协会).{0,20}(?:指出|发布|要求|提出)",
        }
        hits = [label for label, pattern in patterns.items() if re.search(pattern, content or "")]
        return hits

    @staticmethod
    def _academic_style_hits(content: str) -> List[str]:
        patterns = {
            "第一人称": r"\b我们\b|笔者|本人|我认为",
            "营销化表达": r"颠覆性|革命性|遥遥领先|震撼|极致|爆款|快速上手",
            "过度主观": r"显然|毫无疑问|毋庸置疑|令人惊讶的是",
            "占位残留": r"TODO|待补充|此处省略|请自行|略",
        }
        return [label for label, pattern in patterns.items() if re.search(pattern, content or "", re.IGNORECASE)]
