# src/libriscribe/memory/summary_manager.py
"""分层摘要管理器

每章生成后自动摘要，跨章时只传"前 N 章关键摘要 + 术语表"，解决长上下文问题。
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class SummaryManager:
    """分层摘要管理器"""

    def __init__(self, project_dir: str = None, llm_client = None):
        self.summaries: Dict[int, str] = {}  # chapter_number -> summary
        self.global_summary: str = ""  # 全书摘要
        self.project_dir = Path(project_dir) if project_dir else None
        self._file_path = self.project_dir / "summaries.json" if self.project_dir else None
        self.llm_client = llm_client

    def load(self, project_dir: str = None):
        """从文件加载摘要"""
        if project_dir:
            self.project_dir = Path(project_dir)
            self._file_path = self.project_dir / "summaries.json"

        if self._file_path and self._file_path.exists():
            try:
                with open(self._file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.summaries = {int(k): v for k, v in data.get("chapters", {}).items()}
                    self.global_summary = data.get("global_summary", "")
                logger.info(f"Loaded {len(self.summaries)} chapter summaries")
            except Exception as e:
                logger.error(f"Error loading summaries: {e}")

    def save(self):
        """保存摘要到文件"""
        if not self._file_path:
            return

        try:
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "chapters": {str(k): v for k, v in self.summaries.items()},
                "global_summary": self.global_summary
            }
            with open(self._file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            logger.info(f"Saved {len(self.summaries)} chapter summaries")
        except Exception as e:
            logger.error(f"Error saving summaries: {e}")

    def generate_chapter_summary(self, chapter_number: int, chapter_content: str) -> str:
        """为单章生成摘要
        
        Args:
            chapter_number: 章节号
            chapter_content: 章节内容
            
        Returns:
            章节摘要
        """
        if not self.llm_client:
            logger.warning("LLM client not set, using truncated content as summary")
            # 简单截断作为摘要
            return chapter_content[:500] + "..." if len(chapter_content) > 500 else chapter_content

        prompt = f"""请为以下章节内容生成简洁的摘要（200-300字），包含：
1. 主要情节/论点
2. 关键人物/概念
3. 重要事件/转折
4. 与前后章节的关联

章节内容：
{chapter_content[:3000]}

请直接输出摘要，不要添加标题或前缀。"""

        try:
            summary = self.llm_client.generate_content(prompt, max_tokens=500, temperature=0.3)
            self.summaries[chapter_number] = summary
            self.save()
            logger.info(f"Generated summary for chapter {chapter_number}")
            return summary
        except Exception as e:
            logger.error(f"Error generating summary for chapter {chapter_number}: {e}")
            fallback = chapter_content[:300] + "..."
            self.summaries[chapter_number] = fallback
            self.save()
            return fallback

    def get_summary(self, chapter_number: int) -> Optional[str]:
        """获取单章摘要"""
        return self.summaries.get(chapter_number)

    def get_previous_summaries(self, current_chapter: int, max_n: int = 3) -> str:
        """获取前 N 章的摘要（用于注入 prompt）
        
        Args:
            current_chapter: 当前章节号
            max_n: 最多返回前 N 章
            
        Returns:
            格式化的前文摘要字符串
        """
        if not self.summaries:
            return ""

        lines = []
        for ch_num in sorted(self.summaries.keys()):
            if ch_num < current_chapter:
                lines.append(f"### 第{ch_num}章摘要\n{self.summaries[ch_num]}")

        # 只取最后 max_n 章
        if len(lines) > max_n:
            lines = lines[-max_n:]

        if not lines:
            return ""

        return "## 前文摘要\n\n" + "\n\n".join(lines)

    def get_all_summaries(self) -> Dict[int, str]:
        """获取所有章节摘要"""
        return self.summaries.copy()

    def update_global_summary(self, all_chapters_content: str):
        """更新全书摘要
        
        Args:
            all_chapters_content: 全书内容
        """
        if not self.llm_client:
            return

        prompt = f"""请为以下书籍生成一个全局摘要（500-800字），包含：
1. 核心主题和主旨
2. 主要人物和关系
3. 整体叙事结构
4. 关键转折点

书籍内容（节选）：
{all_chapters_content[:5000]}

请直接输出摘要。"""

        try:
            self.global_summary = self.llm_client.generate_content(prompt, max_tokens=1000, temperature=0.3)
            self.save()
            logger.info("Updated global summary")
        except Exception as e:
            logger.error(f"Error updating global summary: {e}")

    def get_context_for_prompt(self, current_chapter: int, max_previous: int = 3) -> str:
        """获取完整的上下文（用于注入 prompt）
        
        Args:
            current_chapter: 当前章节号
            max_previous: 最多包含前 N 章摘要
            
        Returns:
            格式化的上下文字符串
        """
        parts = []

        # 全书摘要
        if self.global_summary:
            parts.append(f"## 全书概览\n{self.global_summary}")

        # 前文摘要
        prev_summaries = self.get_previous_summaries(current_chapter, max_previous)
        if prev_summaries:
            parts.append(prev_summaries)

        return "\n\n".join(parts)

    def sync_from_knowledge_base(self, kb_summaries: Dict[int, str]):
        """从知识库同步摘要"""
        self.summaries.update(kb_summaries)
        self.save()

    def sync_to_knowledge_base(self) -> Dict[int, str]:
        """同步摘要到知识库"""
        return self.summaries.copy()

    @property
    def count(self) -> int:
        """返回摘要数量"""
        return len(self.summaries)