# src/libriscribe/agents/citation_agent.py
"""
CitationAgent - 引用溯源代理

识别章节内容中需要引用的事实性陈述、统计数据、直接引语和转述观点，
提取引用候选并使用 GB/T 7714 标准格式化参考文献。
"""

import json
import logging
from typing import Any, Dict, List, Optional

from libriscribe.agents.agent_base import Agent
from libriscribe.knowledge_base import ProjectKnowledgeBase, Citation
from libriscribe.utils.llm_client import LLMClient
from libriscribe.utils.file_utils import extract_json_from_markdown

logger = logging.getLogger(__name__)


class CitationAgent(Agent):
    """代理：从章节内容中提取需要引用的句子，并生成 GB/T 7714 格式的参考文献。"""

    def __init__(self, llm_client: LLMClient):
        super().__init__(name="CitationAgent", llm_client=llm_client)

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def execute(
        self,
        project_knowledge_base: ProjectKnowledgeBase,
        chapter_number: int,
        chapter_content: str,
    ) -> List[Citation]:
        """
        分析章节内容，识别需要引用的句子，返回 Citation 列表。

        Args:
            project_knowledge_base: 项目知识库（可用于获取书名、类型等上下文）。
            chapter_number: 当前章节编号。
            chapter_content: 章节正文内容。

        Returns:
            List[Citation]: 提取到的引用列表。
        """
        if not chapter_content or not chapter_content.strip():
            self.logger.warning("章节 %d 内容为空，跳过引用提取。", chapter_number)
            return []

        self.logger.info("开始为第 %d 章提取引用候选……", chapter_number)

        try:
            # 1. 使用 LLM 识别需要引用的句子
            candidates = self._extract_citation_candidates(chapter_content)

            if not candidates:
                self.logger.info("第 %d 章未发现需要引用的句子。", chapter_number)
                return []

            self.logger.info(
                "第 %d 章共识别到 %d 条引用候选。", chapter_number, len(candidates)
            )

            # 2. 为每条候选生成 GB/T 7714 格式引用
            citations: List[Citation] = []
            for candidate in candidates:
                try:
                    formatted_ref = self._format_reference_gbt7714(candidate)

                    citation = Citation(
                        sentence=candidate.get("sentence", ""),
                        source=candidate.get("source_type", "unknown"),
                        page=None,  # 页码需手动补充
                        quote_original=candidate.get("original_text", candidate.get("sentence", "")),
                        formatted_ref=formatted_ref,
                        confidence=float(candidate.get("confidence", 0.5)),
                    )
                    citations.append(citation)
                except Exception as e:
                    self.logger.warning(
                        "格式化引用失败（句子: %s）: %s",
                        candidate.get("sentence", "")[:60],
                        e,
                    )
                    # 仍然添加一条基本引用，避免丢失信息
                    citations.append(
                        Citation(
                            sentence=candidate.get("sentence", ""),
                            source=candidate.get("source_type", "unknown"),
                            page=None,
                            quote_original=candidate.get("original_text", ""),
                            formatted_ref="[格式化失败，请手动补充]",
                            confidence=float(candidate.get("confidence", 0.3)),
                        )
                    )

            self.logger.info(
                "第 %d 章引用提取完成，共 %d 条。", chapter_number, len(citations)
            )
            return citations

        except Exception as e:
            self.logger.exception("第 %d 章引用提取过程发生异常: %s", chapter_number, e)
            return []

    # ------------------------------------------------------------------
    # 私有方法
    # ------------------------------------------------------------------

    def _extract_citation_candidates(self, content: str) -> List[dict]:
        """
        使用 LLM 识别章节中需要引用的句子。

        Returns:
            List[dict]: 每个元素包含 sentence, source_type, original_text, confidence,
                        以及可选的 author, title, year, publisher, url 等元数据。
        """
        prompt = self._build_extraction_prompt(content)

        try:
            response_text = self.llm_client.generate_content_with_json_repair(
                original_prompt=prompt, max_tokens=4000, temperature=0.3
            )

            if not response_text:
                self.logger.warning("LLM 返回为空，无法提取引用候选。")
                return []

            data = extract_json_from_markdown(response_text)
            if data is None:
                self.logger.warning("无法从 LLM 响应中解析 JSON。原始响应: %s", response_text[:200])
                return []

            # 兼容两种返回格式：直接返回列表，或包裹在 {"citations": [...]} 中
            if isinstance(data, dict) and "citations" in data:
                candidates = data["citations"]
            elif isinstance(data, list):
                candidates = data
            else:
                self.logger.warning("LLM 返回的 JSON 结构不符合预期: %s", str(data)[:200])
                return []

            # 验证每条候选的基本结构
            valid_candidates = []
            for item in candidates:
                if isinstance(item, dict) and "sentence" in item:
                    # 确保 confidence 在合理范围内
                    conf = item.get("confidence", 0.5)
                    try:
                        conf = max(0.0, min(1.0, float(conf)))
                    except (ValueError, TypeError):
                        conf = 0.5
                    item["confidence"] = conf
                    valid_candidates.append(item)
                else:
                    self.logger.debug("跳过无效候选项: %s", str(item)[:100])

            return valid_candidates

        except Exception as e:
            self.logger.exception("提取引用候选时发生异常: %s", e)
            return []

    def _format_reference_gbt7714(self, candidate: dict) -> str:
        """
        根据候选引用的元数据，使用 LLM 生成 GB/T 7714 格式的参考文献。

        GB/T 7714-2015 示例格式：
          - 专著: 作者. 书名[M]. 出版地: 出版社, 年份.
          - 期刊: 作者. 文章标题[J]. 期刊名, 年份, 卷(期): 页码.
          - 网页: 作者. 标题[EB/OL]. (发布日期)[引用日期]. URL.
          - 学位论文: 作者. 论文题目[D]. 城市: 学校, 年份.

        Args:
            candidate: 包含引用元数据的字典。

        Returns:
            str: GB/T 7714 格式的参考文献字符串。
        """
        # 如果 LLM 已经在候选中直接提供了格式化引用，优先使用
        if candidate.get("formatted_ref"):
            return candidate["formatted_ref"]

        source_type = candidate.get("source_type", "unknown")
        sentence = candidate.get("sentence", "")
        author = candidate.get("author", "")
        title = candidate.get("title", "")
        year = candidate.get("year", "")
        publisher = candidate.get("publisher", "")
        url = candidate.get("url", "")
        journal = candidate.get("journal", "")
        volume = candidate.get("volume", "")
        issue = candidate.get("issue", "")
        pages = candidate.get("pages", "")

        format_prompt = f"""请根据以下信息，生成一条符合 GB/T 7714-2015 标准的参考文献。

引用类型: {source_type}
相关句子: {sentence}
作者: {author or "未知"}
标题: {title or "未知"}
年份: {year or "未知"}
出版社/期刊: {publisher or journal or "未知"}
URL: {url or "无"}
卷/期: {volume or "无"}/{issue or "无"}
页码: {pages or "无"}

GB/T 7714-2015 格式参考：
- 专著 [M]: 作者. 书名[M]. 出版地: 出版社, 年份.
- 期刊 [J]: 作者. 文章标题[J]. 期刊名, 年份, 卷(期): 页码.
- 网页 [EB/OL]: 作者. 标题[EB/OL]. (发布日期)[引用日期]. URL.
- 学位论文 [D]: 作者. 论文题目[D]. 城市: 学校, 年份.
- 报告 [R]: 作者. 报告题目[R]. 出版地: 机构, 年份.

请仅输出一条格式化后的参考文献字符串，不要输出其他内容。如果信息不足，请用"[待补充]"标注缺失部分。"""

        try:
            formatted = self.llm_client.generate_content(
                prompt=format_prompt, max_tokens=300, temperature=0.2
            )
            formatted = formatted.strip().strip('"').strip("'")

            if not formatted:
                self.logger.warning("LLM 未能生成 GB/T 7714 格式引用，使用回退格式。")
                return self._fallback_format(candidate)

            return formatted

        except Exception as e:
            self.logger.warning("调用 LLM 格式化引用时出错: %s，使用回退格式。", e)
            return self._fallback_format(candidate)

    def _fallback_format(self, candidate: dict) -> str:
        """
        当 LLM 格式化失败时，根据已有信息生成简单的回退格式引用。

        Args:
            candidate: 引用候选字典。

        Returns:
            str: 简单格式化的引用字符串。
        """
        source_type = candidate.get("source_type", "unknown")
        author = candidate.get("author", "[待补充]")
        title = candidate.get("title", "[待补充]")
        year = candidate.get("year", "[待补充]")

        type_marker = {
            "academic": "J",
            "journal": "J",
            "book": "M",
            "web": "EB/OL",
            "report": "R",
            "thesis": "D",
            "conference": "C",
        }.get(source_type, "Z")

        parts = [f"{author}. {title}[{type_marker}]"]

        if source_type in ("book", "thesis"):
            publisher = candidate.get("publisher", "[待补充]")
            parts.append(f"[出版地不详]: {publisher}, {year}.")
        elif source_type in ("academic", "journal"):
            journal_name = candidate.get("journal", "[待补充]")
            parts.append(f"{journal_name}, {year}.")
        elif source_type == "web":
            url = candidate.get("url", "[待补充]")
            parts.append(f"[{year}]. {url}")
        else:
            parts.append(f"{year}.")

        return " ".join(parts)

    def _build_extraction_prompt(self, content: str) -> str:
        """
        构建用于 LLM 提取引用候选的提示词。

        Args:
            content: 章节正文内容。

        Returns:
            str: 完整的提示词。
        """
        return f"""你是一位专业的学术编辑和引用专家。请仔细阅读以下章节内容，识别所有需要添加引用（参考文献）的句子。

需要引用的内容类型包括：
1. **事实性陈述**：涉及历史事件、科学事实、统计数据等可验证的信息
2. **统计数据**：包含具体数字、百分比、比例等数据的陈述
3. **直接引语**：引用他人原话的句子
4. **转述观点**：转述他人研究结论、理论或观点的句子
5. **专业术语定义**：引用特定领域术语的权威定义

不需要引用的内容：
- 纯虚构情节和对话
- 作者自己的分析和评论（除非引用了他人的框架）
- 常识性内容（如"地球绕太阳转"）

章节内容：
---
{content}
---

请以 JSON 格式输出结果，格式如下：
```json
{{
  "citations": [
    {{
      "sentence": "需要引用的完整句子",
      "original_text": "原文中需要引用的片段（可能与 sentence 相同）",
      "source_type": "引用来源类型（academic/book/web/report/thesis/journal/conference）",
      "confidence": 0.85,
      "author": "如果能推断出作者则填写，否则留空",
      "title": "如果能推断出标题则填写，否则留空",
      "year": "如果能推断出年份则填写，否则留空",
      "publisher": "出版社或机构，如果能推断则填写",
      "journal": "期刊名，如果是期刊论文则填写",
      "url": "如果是网页来源则填写 URL"
    }}
  ]
}}
```

注意：
- confidence 取值 0-1，表示该句子确实需要引用的置信度
- 如果无法推断具体来源信息，author/title/year 等字段留空即可
- 请确保输出为合法的 JSON 格式"""
