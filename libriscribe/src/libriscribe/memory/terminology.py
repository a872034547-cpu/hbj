# src/libriscribe/memory/terminology.py
"""术语表管理

维护全书统一的术语字典，支持添加、查询、批量替换。
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class TerminologyManager:
    """术语表管理器"""

    def __init__(self, project_dir: str = None):
        self.terminology: Dict[str, str] = {}
        self.project_dir = Path(project_dir) if project_dir else None
        self._file_path = self.project_dir / "terminology.json" if self.project_dir else None

    def load(self, project_dir: str = None):
        """从文件加载术语表"""
        if project_dir:
            self.project_dir = Path(project_dir)
            self._file_path = self.project_dir / "terminology.json"

        if self._file_path and self._file_path.exists():
            try:
                with open(self._file_path, "r", encoding="utf-8") as f:
                    self.terminology = json.load(f)
                logger.info(f"Loaded {len(self.terminology)} terms from {self._file_path}")
            except Exception as e:
                logger.error(f"Error loading terminology: {e}")
                self.terminology = {}

    def save(self):
        """保存术语表到文件"""
        if not self._file_path:
            return

        try:
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._file_path, "w", encoding="utf-8") as f:
                json.dump(self.terminology, f, indent=4, ensure_ascii=False)
            logger.info(f"Saved {len(self.terminology)} terms to {self._file_path}")
        except Exception as e:
            logger.error(f"Error saving terminology: {e}")

    def add(self, term: str, definition: str):
        """添加或更新术语
        
        Args:
            term: 术语名称
            definition: 术语定义/统一写法
        """
        self.terminology[term] = definition
        self.save()
        logger.info(f"Added/updated term: {term}")

    def add_batch(self, terms: Dict[str, str]):
        """批量添加术语
        
        Args:
            terms: 术语字典 {term: definition}
        """
        self.terminology.update(terms)
        self.save()
        logger.info(f"Added {len(terms)} terms in batch")

    def remove(self, term: str) -> bool:
        """删除术语
        
        Args:
            term: 术语名称
            
        Returns:
            是否成功删除
        """
        if term in self.terminology:
            del self.terminology[term]
            self.save()
            logger.info(f"Removed term: {term}")
            return True
        return False

    def get(self, term: str) -> Optional[str]:
        """获取术语定义
        
        Args:
            term: 术语名称
            
        Returns:
            术语定义，不存在返回 None
        """
        return self.terminology.get(term)

    def get_all(self) -> Dict[str, str]:
        """获取所有术语"""
        return self.terminology.copy()

    def search(self, keyword: str) -> List[Tuple[str, str]]:
        """搜索术语
        
        Args:
            keyword: 搜索关键词
            
        Returns:
            匹配的术语列表 [(term, definition), ...]
        """
        keyword_lower = keyword.lower()
        results = []
        for term, defn in self.terminology.items():
            if keyword_lower in term.lower() or keyword_lower in defn.lower():
                results.append((term, defn))
        return results

    def get_context_for_prompt(self) -> str:
        """获取术语表上下文（用于注入 prompt）
        
        Returns:
            格式化的术语表字符串
        """
        if not self.terminology:
            return ""

        lines = ["## 术语表（写作时必须统一使用以下术语）\n"]
        for term, defn in sorted(self.terminology.items()):
            lines.append(f"- **{term}**: {defn}")
        return "\n".join(lines)

    def apply_to_text(self, text: str) -> str:
        """将术语表应用到文本（批量替换）
        
        注意：这是一个简单的字符串替换，可能需要更智能的 NLP 方法。
        
        Args:
            text: 原始文本
            
        Returns:
            替换后的文本
        """
        result = text
        for term, defn in self.terminology.items():
            # 简单替换，后续可优化为更智能的替换
            if term != defn and term in result:
                result = result.replace(term, defn)
        return result

    def merge_from_knowledge_base(self, kb_terminology: Dict[str, str]):
        """从知识库合并术语
        
        Args:
            kb_terminology: 知识库中的术语字典
        """
        self.terminology.update(kb_terminology)
        self.save()

    def export_to_knowledge_base(self) -> Dict[str, str]:
        """导出术语到知识库格式"""
        return self.terminology.copy()

    @property
    def count(self) -> int:
        """返回术语数量"""
        return len(self.terminology)