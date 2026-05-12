# src/libriscribe/agents/critic_agent.py
"""
CriticAgent - 质量评审代理

对章节内容进行多维度评分和详细反馈，支持迭代改进循环。
评估维度包括：情节一致性、角色一致性、写作质量、节奏把控、术语使用、事实准确性和风格遵循度。
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from libriscribe.agents.agent_base import Agent
from libriscribe.knowledge_base import ChapterReview, ProjectKnowledgeBase
from libriscribe.utils.llm_client import LLMClient


class CriticAgent(Agent):
    """质量评审代理：对章节内容进行评分并提供详细改进建议。"""

    def __init__(self, llm_client: LLMClient):
        super().__init__(name="CriticAgent", llm_client=llm_client)

    def execute(
        self,
        project_knowledge_base: ProjectKnowledgeBase,
        chapter_number: int,
        chapter_content: str,
    ) -> ChapterReview:
        """
        评审指定章节内容，返回结构化的评审结果。

        Args:
            project_knowledge_base: 项目知识库，包含风格指南、角色、世界观等信息。
            chapter_number: 当前评审的章节编号。
            chapter_content: 待评审的章节正文内容。

        Returns:
            ChapterReview 对象，包含评分、一致性问题、术语问题和改进建议。
        """
        self.logger.info(f"开始评审第 {chapter_number} 章...")

        try:
            # 构建评审提示词
            prompt = self._build_review_prompt(
                project_knowledge_base, chapter_number, chapter_content
            )

            # 调用 LLM 进行评审
            response = self.llm_client.generate_content(prompt, max_tokens=3000)

            # 解析 LLM 返回的 JSON
            review_data = self._parse_review_response(response)

            # 计算当前迭代次数
            existing_reviews = project_knowledge_base.chapter_reviews.get(
                chapter_number, []
            )
            iteration = len(existing_reviews) + 1

            # 构建 ChapterReview 对象
            review = ChapterReview(
                iteration=iteration,
                score=float(review_data.get("score", 0.0)),
                consistency_issues=review_data.get("consistency_issues", []),
                terminology_issues=review_data.get("terminology_issues", []),
                suggestions=review_data.get("suggestions", []),
                reviewed_at=datetime.now().isoformat(),
            )

            # 将评审结果存入知识库
            if chapter_number not in project_knowledge_base.chapter_reviews:
                project_knowledge_base.chapter_reviews[chapter_number] = []
            project_knowledge_base.chapter_reviews[chapter_number].append(review)

            self.logger.info(
                f"第 {chapter_number} 章评审完成 — "
                f"迭代 {iteration}, 评分 {review.score:.1f}/10, "
                f"一致性问题 {len(review.consistency_issues)} 个, "
                f"术语问题 {len(review.terminology_issues)} 个, "
                f"建议 {len(review.suggestions)} 条"
            )

            return review

        except Exception as e:
            self.logger.exception(f"评审第 {chapter_number} 章时发生错误: {e}")
            # 返回一个默认的低分评审，避免流程中断
            return ChapterReview(
                iteration=len(
                    project_knowledge_base.chapter_reviews.get(chapter_number, [])
                )
                + 1,
                score=0.0,
                consistency_issues=[],
                terminology_issues=[],
                suggestions=[f"评审过程出错: {str(e)}"],
                reviewed_at=datetime.now().isoformat(),
            )

    def _build_review_prompt(
        self,
        project_knowledge_base: ProjectKnowledgeBase,
        chapter_number: int,
        content: str,
    ) -> str:
        """
        构建全面的评审提示词，包含项目上下文信息以支持多维度评估。

        Args:
            project_knowledge_base: 项目知识库。
            chapter_number: 章节编号。
            content: 章节正文。

        Returns:
            完整的评审提示词字符串。
        """
        sections: List[str] = []

        # ── 项目基本信息 ──
        sections.append(f"## 项目信息\n"
                        f"- 标题: {project_knowledge_base.title}\n"
                        f"- 类型: {project_knowledge_base.genre}\n"
                        f"- 语言: {project_knowledge_base.language}\n"
                        f"- 目标读者: {project_knowledge_base.target_audience}\n"
                        f"- 基调: {project_knowledge_base.tone}")

        # ── 风格指南 ──
        if project_knowledge_base.style_guide:
            sections.append(f"## 风格指南\n{project_knowledge_base.style_guide}")

        # ── 角色信息 ──
        if project_knowledge_base.characters:
            char_lines: List[str] = []
            for name, char in project_knowledge_base.characters.items():
                parts = [f"### {name}"]
                if char.role:
                    parts.append(f"- 角色定位: {char.role}")
                if char.personality_traits:
                    parts.append(f"- 性格特征: {char.personality_traits}")
                if char.background:
                    parts.append(f"- 背景: {char.background}")
                if char.motivations:
                    parts.append(f"- 动机: {char.motivations}")
                if char.relationships:
                    rels = "; ".join(
                        f"{r_name}: {r_desc}"
                        for r_name, r_desc in char.relationships.items()
                    )
                    parts.append(f"- 人际关系: {rels}")
                if char.character_arc:
                    parts.append(f"- 角色弧线: {char.character_arc}")
                char_lines.append("\n".join(parts))
            sections.append("## 角色档案\n" + "\n\n".join(char_lines))

        # ── 世界观设定 ──
        if project_knowledge_base.worldbuilding:
            wb = project_knowledge_base.worldbuilding
            wb_parts: List[str] = []
            for field_name in [
                "geography", "culture_and_society", "history",
                "rules_and_laws", "technology_level", "magic_system",
                "key_locations", "important_organizations",
                "setting_context", "key_figures", "major_events",
            ]:
                value = getattr(wb, field_name, "")
                if value:
                    wb_parts.append(f"- {field_name}: {value}")
            if wb_parts:
                sections.append("## 世界观设定\n" + "\n".join(wb_parts))

        # ── 前序章节摘要 ──
        if project_knowledge_base.chapter_summaries:
            summary_lines: List[str] = []
            for ch_num in sorted(project_knowledge_base.chapter_summaries.keys()):
                if ch_num < chapter_number:
                    summary_lines.append(
                        f"- 第 {ch_num} 章: {project_knowledge_base.chapter_summaries[ch_num]}"
                    )
            if summary_lines:
                sections.append(
                    "## 前序章节摘要（用于叙事连续性检查）\n"
                    + "\n".join(summary_lines)
                )

        # ── 术语表 ──
        if project_knowledge_base.terminology:
            term_lines = [
                f"- {term}: {definition}"
                for term, definition in project_knowledge_base.terminology.items()
            ]
            sections.append("## 术语表\n" + "\n".join(term_lines))

        # ── 大纲（当前章节） ──
        if project_knowledge_base.chapters.get(chapter_number):
            ch = project_knowledge_base.chapters[chapter_number]
            outline_parts = [f"## 当前章节大纲（第 {chapter_number} 章）"]
            if ch.title:
                outline_parts.append(f"- 标题: {ch.title}")
            if ch.summary:
                outline_parts.append(f"- 摘要: {ch.summary}")
            if ch.scenes:
                for scene in ch.scenes:
                    scene_desc = f"  - 场景 {scene.scene_number}: {scene.summary}"
                    if scene.characters:
                        scene_desc += f" [角色: {', '.join(scene.characters)}]"
                    if scene.setting:
                        scene_desc += f" [场景: {scene.setting}]"
                    outline_parts.append(scene_desc)
            sections.append("\n".join(outline_parts))

        # ── 组装最终提示词 ──
        context_block = "\n\n".join(sections)

        prompt = f"""你是一位资深的文学编辑和质量评审专家。请对以下章节内容进行全面、严格的评审。

{context_block}

---

## 待评审章节内容（第 {chapter_number} 章）

{content}

---

## 评审要求

请从以下 **七个维度** 逐一评估，并给出 0-10 分的综合评分：

1. **情节一致性 (Plot Consistency)** — 本章情节是否与前序章节和整体大纲一致？是否有逻辑矛盾或未解释的突变？
2. **角色一致性 (Character Consistency)** — 角色的行为、对话、动机是否与其性格档案和角色弧线一致？是否有角色"走形"？
3. **写作质量 (Writing Quality)** — 语言表达是否流畅、准确？是否有语法错误、用词不当或表达冗余？
4. **节奏把控 (Pacing)** — 章节的节奏是否合理？是否有拖沓或过于仓促的部分？场景转换是否自然？
5. **术语使用 (Terminology Usage)** — 专有名词、术语的使用是否与术语表一致？是否有前后不一致的用法？
6. **事实准确性 (Factual Accuracy)** — 涉及世界观设定、历史背景、技术细节等内容是否准确？
7. **风格遵循度 (Style Adherence)** — 是否遵循了项目的风格指南和整体基调？

## 输出格式

请 **严格** 以 JSON 格式输出评审结果，不要包含任何其他文本：

```json
{{
  "score": <0-10 的浮点数，综合评分>,
  "consistency_issues": [
    "<一致性问题 1，具体描述>",
    "<一致性问题 2>"
  ],
  "terminology_issues": [
    "<术语问题 1，具体描述>",
    "<术语问题 2>"
  ],
  "suggestions": [
    "<改进建议 1，具体且可操作>",
    "<改进建议 2>"
  ]
}}
```

注意事项：
- 如果某个维度没有发现问题，对应的列表可以为空 `[]`。
- `score` 应反映整体质量：9-10 优秀，7-8 良好，5-6 及格，3-4 较差，1-2 很差。
- 建议应具体、可操作，避免泛泛而谈。
"""

        return prompt

    def _parse_review_response(self, response: str) -> dict:
        """
        解析 LLM 返回的 JSON 评审结果。

        支持从可能包含额外文本（如 markdown 代码块）的响应中提取 JSON。

        Args:
            response: LLM 的原始响应文本。

        Returns:
            解析后的字典，包含 score、consistency_issues、terminology_issues、suggestions。
        """
        default_result = {
            "score": 0.0,
            "consistency_issues": [],
            "terminology_issues": [],
            "suggestions": ["无法解析 LLM 评审响应，请检查日志。"],
        }

        try:
            # 尝试直接解析
            return json.loads(response)
        except json.JSONDecodeError:
            pass

        try:
            # 尝试从 markdown 代码块中提取 JSON
            if "```json" in response:
                json_start = response.index("```json") + len("```json")
                json_end = response.index("```", json_start)
                json_str = response[json_start:json_end].strip()
                return json.loads(json_str)
            elif "```" in response:
                json_start = response.index("```") + len("```")
                json_end = response.index("```", json_start)
                json_str = response[json_start:json_end].strip()
                return json.loads(json_str)
        except (json.JSONDecodeError, ValueError):
            pass

        try:
            # 尝试找到第一个 { 和最后一个 } 之间的内容
            first_brace = response.index("{")
            last_brace = response.rindex("}") + 1
            json_str = response[first_brace:last_brace]
            return json.loads(json_str)
        except (json.JSONDecodeError, ValueError):
            pass

        self.logger.warning(
            f"无法解析 LLM 评审响应，将返回默认结果。响应前 500 字符: {response[:500]}"
        )
        return default_result

    def get_score(
        self,
        project_knowledge_base: ProjectKnowledgeBase,
        chapter_number: int,
    ) -> float:
        """
        便捷方法：仅返回章节的评审评分。

        Args:
            project_knowledge_base: 项目知识库。
            chapter_number: 章节编号。

        Returns:
            0-10 的浮点评分。如果该章节尚未评审过，返回 0.0。
        """
        reviews = project_knowledge_base.chapter_reviews.get(chapter_number, [])
        if not reviews:
            self.logger.warning(
                f"第 {chapter_number} 章尚无评审记录，返回默认评分 0.0"
            )
            return 0.0
        # 返回最新一次评审的评分
        return reviews[-1].score
