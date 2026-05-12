# src/libriscribe/rag/vector_store.py
"""ChromaDB 向量存储

管理文档向量的存储、索引和查询。
"""

import logging
from typing import List, Dict, Any, Optional
from pathlib import Path

from libriscribe.rag.document_loader import DocumentChunk
from libriscribe.rag.embeddings import EmbeddingProvider
from libriscribe.settings import Settings

logger = logging.getLogger(__name__)


class VectorStore:
    """基于 ChromaDB 的向量存储"""

    def __init__(self, collection_name: str = "libriscribe", embedding_provider: EmbeddingProvider = None):
        settings = Settings()
        self.persist_dir = settings.chroma_persist_dir
        self.collection_name = collection_name
        self.embedding_provider = embedding_provider
        self._client = None
        self._collection = None
        self._init_chroma()

    def _init_chroma(self):
        """初始化 ChromaDB 客户端"""
        try:
            import chromadb
            from chromadb.config import Settings as ChromaSettings

            # 确保持久化目录存在
            Path(self.persist_dir).mkdir(parents=True, exist_ok=True)

            self._client = chromadb.PersistentClient(
                path=self.persist_dir,
                settings=ChromaSettings(anonymized_telemetry=False)
            )
            self._collection = self._client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"}
            )
            logger.info(f"ChromaDB initialized: collection='{self.collection_name}', persist_dir='{self.persist_dir}'")
        except ImportError:
            raise ImportError("chromadb is required. Install with: pip install chromadb")

    def add_documents(self, chunks: List[DocumentChunk]) -> int:
        """添加文档分块到向量存储
        
        Args:
            chunks: 文档分块列表
            
        Returns:
            成功添加的分块数量
        """
        if not chunks:
            return 0

        # 检查哪些 chunk 已经存在
        existing_ids = set()
        try:
            existing = self._collection.get(ids=[c.chunk_id for c in chunks])
            existing_ids = set(existing["ids"])
        except Exception:
            pass

        # 过滤已存在的
        new_chunks = [c for c in chunks if c.chunk_id not in existing_ids]
        if not new_chunks:
            logger.info("All chunks already exist in vector store")
            return 0

        if self.embedding_provider is None:
            self.embedding_provider = EmbeddingProvider()

        # 批量添加
        batch_size = 100
        added = 0
        for i in range(0, len(new_chunks), batch_size):
            batch = new_chunks[i:i + batch_size]
            texts = [c.content for c in batch]
            ids = [c.chunk_id for c in batch]
            metadatas = [self._sanitize_metadata(c.metadata) for c in batch]

            # 生成嵌入
            embeddings = self.embedding_provider.embed_texts(texts)

            self._collection.add(
                ids=ids,
                embeddings=embeddings,
                documents=texts,
                metadatas=metadatas
            )
            added += len(batch)

        logger.info(f"Added {added} new chunks to vector store")
        return added

    def _sanitize_metadata(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Chroma metadata 只接受非空标量字典；复杂对象统一转字符串。"""
        sanitized: Dict[str, Any] = {}
        for key, value in (metadata or {}).items():
            if value is None:
                sanitized[key] = ""
            elif isinstance(value, (str, int, float, bool)):
                sanitized[key] = value
            else:
                sanitized[key] = str(value)

        # ChromaDB 1.x 不接受空 metadata dict。测试分块、极短文本或外部调用
        # 可能没有元数据，必须补一个稳定占位字段，避免索引阶段失败。
        if not sanitized:
            sanitized["source"] = "unknown"
        return sanitized

    def query(self, query_text: str, top_k: int = 5, filter_metadata: Dict = None) -> List[Dict[str, Any]]:
        """查询最相关的文档分块
        
        Args:
            query_text: 查询文本
            top_k: 返回结果数量
            filter_metadata: 元数据过滤条件
            
        Returns:
            查询结果列表，每项包含 content, metadata, distance
        """
        if self._collection.count() == 0:
            logger.warning("Vector store is empty")
            return []

        if self.embedding_provider is None:
            self.embedding_provider = EmbeddingProvider()

        # 生成查询嵌入
        query_embedding = self.embedding_provider.embed_query(query_text)

        # 构建查询参数
        query_params = {
            "query_embeddings": [query_embedding],
            "n_results": min(top_k, self._collection.count()),
            "include": ["documents", "metadatas", "distances"]
        }

        if filter_metadata:
            query_params["where"] = filter_metadata

        results = self._collection.query(**query_params)

        # 格式化结果
        formatted_results = []
        if results and results["documents"]:
            for i in range(len(results["documents"][0])):
                formatted_results.append({
                    "content": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                    "distance": results["distances"][0][i] if results["distances"] else 0.0,
                    "id": results["ids"][0][i] if results["ids"] else ""
                })

        return formatted_results

    def delete_by_source(self, source: str):
        """按来源删除文档分块"""
        try:
            self._collection.delete(where={"source": source})
            logger.info(f"Deleted chunks from source: {source}")
        except Exception as e:
            logger.error(f"Error deleting chunks from source {source}: {e}")

    def clear(self):
        """清空向量存储"""
        try:
            self._client.delete_collection(self.collection_name)
            self._collection = self._client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"}
            )
            logger.info("Vector store cleared")
        except Exception as e:
            logger.error(f"Error clearing vector store: {e}")

    @property
    def count(self) -> int:
        """返回存储的文档数量"""
        return self._collection.count()

    def list_sources(self) -> List[str]:
        """列出所有已索引的文档来源"""
        if self._collection.count() == 0:
            return []
        try:
            all_data = self._collection.get(include=["metadatas"])
            sources = set()
            for meta in all_data["metadatas"]:
                if meta and "source" in meta:
                    sources.add(meta["source"])
            return sorted(list(sources))
        except Exception as e:
            logger.error(f"Error listing sources: {e}")
            return []
