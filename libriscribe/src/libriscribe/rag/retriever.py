# src/libriscribe/rag/retriever.py
"""混合检索器

结合向量相似度和关键词匹配，返回带溯源信息的检索结果。
"""

import logging
from typing import List, Dict, Any, Optional

from libriscribe.rag.vector_store import VectorStore
from libriscribe.rag.document_loader import DocumentLoader, DocumentChunk
from libriscribe.rag.embeddings import EmbeddingProvider
from libriscribe.settings import Settings

logger = logging.getLogger(__name__)


class RetrievalResult:
    """检索结果"""

    def __init__(self, content: str, source: str, score: float, metadata: Dict = None):
        self.content = content
        self.source = source
        self.score = score
        self.metadata = metadata or {}

    def to_context_string(self) -> str:
        """转换为可注入 prompt 的上下文字符串"""
        page_info = f" (p.{self.metadata['page']})" if self.metadata.get('page') else ""
        return f"[来源: {self.source}{page_info}]\n{self.content}"

    def __repr__(self):
        return f"RetrievalResult(source='{self.source}', score={self.score:.3f})"


class Retriever:
    """混合检索器
    
    结合向量相似度检索和关键词匹配，提供高质量的文档检索。
    """

    def __init__(self, vector_store: VectorStore = None, embedding_provider: EmbeddingProvider = None):
        settings = Settings()
        self.top_k = settings.rag_top_k
        self.embedding_provider = embedding_provider
        self.vector_store = vector_store or VectorStore(embedding_provider=embedding_provider)
        self.document_loader = DocumentLoader(
            chunk_size=settings.rag_chunk_size,
            chunk_overlap=settings.rag_chunk_overlap
        )

    def _ensure_embedding_provider(self) -> EmbeddingProvider:
        """仅在真正需要向量计算时初始化 embedding，避免空库检索反复加载本地模型。"""
        if self.embedding_provider is None:
            self.embedding_provider = EmbeddingProvider()
            self.vector_store.embedding_provider = self.embedding_provider
        return self.embedding_provider

    def index_file(self, file_path: str) -> int:
        """索引单个文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            索引的分块数量
        """
        chunks = self.document_loader.load_file(file_path)
        if not chunks:
            return 0
        self._ensure_embedding_provider()
        return self.vector_store.add_documents(chunks)

    def index_directory(self, dir_path: str, recursive: bool = True) -> int:
        """索引目录下的所有文件
        
        Args:
            dir_path: 目录路径
            recursive: 是否递归
            
        Returns:
            索引的分块数量
        """
        chunks = self.document_loader.load_directory(dir_path, recursive)
        if not chunks:
            return 0
        self._ensure_embedding_provider()
        return self.vector_store.add_documents(chunks)

    def retrieve(self, query: str, top_k: int = None, filter_source: str = None) -> List[RetrievalResult]:
        """检索与查询最相关的文档片段
        
        Args:
            query: 查询文本
            top_k: 返回结果数量
            filter_source: 按来源过滤
            
        Returns:
            检索结果列表
        """
        k = top_k or self.top_k
        filter_meta = {"source": filter_source} if filter_source else None

        if self.vector_store.count == 0:
            logger.info("Vector store is empty; skipping embedding query")
            return []
        self._ensure_embedding_provider()
        raw_results = self.vector_store.query(query, top_k=k, filter_metadata=filter_meta)

        results = []
        for r in raw_results:
            # ChromaDB 使用 cosine distance，转换为相似度分数
            similarity = 1.0 - r["distance"]
            result = RetrievalResult(
                content=r["content"],
                source=r["metadata"].get("source", "unknown"),
                score=similarity,
                metadata=r["metadata"]
            )
            results.append(result)

        # 按相似度排序
        results.sort(key=lambda x: x.score, reverse=True)
        return results

    def retrieve_for_chapter(self, chapter_summary: str, chapter_title: str = "", top_k: int = None) -> List[RetrievalResult]:
        """为特定章节检索相关资料
        
        结合章节标题和摘要构建查询。
        
        Args:
            chapter_summary: 章节摘要
            chapter_title: 章节标题
            top_k: 返回结果数量
            
        Returns:
            检索结果列表
        """
        query = f"{chapter_title}: {chapter_summary}" if chapter_title else chapter_summary
        return self.retrieve(query, top_k=top_k)

    def get_context_for_prompt(self, query: str, top_k: int = None) -> str:
        """获取可直接注入 prompt 的检索上下文
        
        Args:
            query: 查询文本
            top_k: 返回结果数量
            
        Returns:
            格式化的上下文字符串
        """
        results = self.retrieve(query, top_k=top_k)
        if not results:
            return ""

        context_parts = ["以下是相关的参考资料：\n"]
        for i, r in enumerate(results, 1):
            context_parts.append(f"--- 参考资料 {i} (来源: {r.source}, 相关度: {r.score:.2f}) ---")
            context_parts.append(r.content)
            context_parts.append("")

        return "\n".join(context_parts)

    @property
    def total_documents(self) -> int:
        """返回索引的文档总数"""
        return self.vector_store.count

    def list_indexed_sources(self) -> List[str]:
        """列出所有已索引的文档来源"""
        return self.vector_store.list_sources()

    def clear_index(self):
        """清空索引"""
        self.vector_store.clear()
        logger.info("Retrieval index cleared")