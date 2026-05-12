"""资料来源与 RAG 覆盖服务。"""

from __future__ import annotations

import string
from typing import Any, Dict, List


class SourceService:
    """提供资料库、证据片段与章节覆盖分析。"""

    _BINARY_SIGNATURES = (
        "\x00",
        "\ufffd",
        "\ud0cf\ud0d0\ud0c1\ud0d1",
        "PK\x03\x04",
        "%PDF-",
    )

    @staticmethod
    def is_usable_evidence_text(text: Any) -> bool:
        """判断证据片段文本是否可用于检索/引用。"""
        if not isinstance(text, str):
            return False
        normalized = text.strip()
        if len(normalized) < 8:
            return False
        if any(signature in normalized[:256] for signature in SourceService._BINARY_SIGNATURES):
            return False
        total = len(normalized)
        control_chars = sum(1 for char in normalized if ord(char) < 32 and char not in {"\n", "\r", "\t"})
        if total == 0 or control_chars / total > 0.02:
            return False
        printable_chars = sum(1 for char in normalized if char.isprintable() or char in {"\n", "\r", "\t"})
        if printable_chars / total < 0.85:
            return False
        meaningful_chars = sum(
            1
            for char in normalized
            if char.isalnum() or "\u4e00" <= char <= "\u9fff" or char in string.punctuation
        )
        return meaningful_chars / total >= 0.25

    @staticmethod
    def source_summary(project: Any) -> Dict[str, int]:
        """统计项目资料库概况。"""
        source_documents = list(getattr(project, "source_documents", None) or [])
        evidence_chunks = list(getattr(project, "evidence_chunks", None) or [])
        rag_documents = list(getattr(project, "rag_documents", None) or [])
        indexed_sources = sum(1 for document in source_documents if getattr(document, "status", "indexed") == "indexed")
        if not source_documents:
            indexed_sources = len(rag_documents)
        bad_chunks = sum(1 for chunk in evidence_chunks if not SourceService.is_usable_evidence_text(getattr(chunk, "text", "")))
        return {
            "documents": len(source_documents),
            "evidence_chunks": len(evidence_chunks),
            "indexed_sources": indexed_sources,
            "bad_chunks": bad_chunks,
            "usable_chunks": max(0, len(evidence_chunks) - bad_chunks),
        }

    @staticmethod
    def document_coverage(project: Any) -> List[Dict[str, Any]]:
        """按来源文档统计证据片段与引用覆盖。"""
        documents = list(getattr(project, "source_documents", None) or [])
        chunks = list(getattr(project, "evidence_chunks", None) or [])
        citations = list(getattr(project, "citations", None) or [])
        rows: List[Dict[str, Any]] = []
        for document in documents:
            doc_id = getattr(document, "id", "")
            doc_chunks = [chunk for chunk in chunks if getattr(chunk, "document_id", "") == doc_id]
            chunk_ids = {getattr(chunk, "id", "") for chunk in doc_chunks}
            doc_citations = [citation for citation in citations if getattr(citation, "evidence_chunk_id", "") in chunk_ids]
            rows.append(
                {
                    "document_id": doc_id,
                    "title": getattr(document, "title", "") or getattr(document, "file_name", ""),
                    "status": getattr(document, "status", "indexed"),
                    "chunks": len(doc_chunks),
                    "usable_chunks": sum(1 for chunk in doc_chunks if SourceService.is_usable_evidence_text(getattr(chunk, "text", ""))),
                    "citations": len(doc_citations),
                    "coverage_score": SourceService._coverage_score(len(doc_chunks), len(doc_citations)),
                }
            )
        return rows

    @staticmethod
    def chapter_source_gaps(project: Any) -> List[Dict[str, Any]]:
        """按章节写作单元的 RAG 查询粗略识别资料覆盖缺口。"""
        chunks = list(getattr(project, "evidence_chunks", None) or [])
        chapters = getattr(project, "chapters", {}) or {}
        rows: List[Dict[str, Any]] = []
        for chapter_number, chapter in chapters.items():
            sections = list(getattr(chapter, "sections", []) or [])
            queries = [getattr(section, "rag_query", "") or getattr(section, "title", "") for section in sections]
            matched = 0
            for query in queries:
                q = str(query).strip().lower()
                if q and any(q[:20] in str(getattr(chunk, "text", "")).lower() for chunk in chunks):
                    matched += 1
            rows.append(
                {
                    "chapter_number": int(chapter_number),
                    "title": getattr(chapter, "title", ""),
                    "writing_units": len(sections),
                    "matched_units": matched,
                    "gap_units": max(0, len(sections) - matched),
                }
            )
        return rows

    @staticmethod
    def _coverage_score(chunks: int, citations: int) -> float:
        if chunks <= 0:
            return 0.0
        return round(min(citations / chunks * 100, 100.0), 1)
