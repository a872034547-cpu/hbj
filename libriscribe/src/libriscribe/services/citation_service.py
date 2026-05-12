"""引用核验与证据绑定服务。"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import quote_plus
from typing import Any, Dict, List, Optional

from libriscribe.knowledge_base import Citation, EvidenceChunk, ProjectKnowledgeBase, SourceDocument


class CitationService:
    """提供引用列表、风险统计、证据绑定与引用闭环检查。"""

    @staticmethod
    def list_citations(project: Any) -> List[Any]:
        """返回项目中的全部引用记录。"""
        if project is None:
            return []
        citations = project.get("citations", []) if isinstance(project, dict) else getattr(project, "citations", [])
        return list(citations or [])

    @classmethod
    def parse_reference_text(cls, text: str) -> List[Dict[str, Any]]:
        """解析用户粘贴的 GB/T 7714 风格参考文献列表。

        解析结果只作为“待核验参考文献”，不会被视为真实来源。真实核验仍需
        DOI/URL、上传原文资料或人工在可信数据库中确认。
        """
        references: List[Dict[str, Any]] = []
        if not text or not text.strip():
            return references

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        current = ""
        for line in lines:
            if re.match(r"^\s*\[?\d+\]?\s*", line) and current:
                references.append(cls._parse_single_reference(current))
                current = line
            else:
                current = f"{current} {line}".strip() if current else line
        if current:
            references.append(cls._parse_single_reference(current))
        return references

    @classmethod
    def import_reference_text(cls, project: ProjectKnowledgeBase, text: str) -> List[Citation]:
        """将粘贴参考文献导入为未核验/风险引用记录。"""
        imported: List[Citation] = []
        for item in cls.parse_reference_text(text):
            raw_ref = item.get("raw", "").strip()
            if not raw_ref:
                continue
            citation_id = cls._raw_reference_id(raw_ref)
            citation = Citation(
                id=citation_id,
                formatted_ref=raw_ref,
                source=item.get("source", ""),
                source_type=item.get("source_type", ""),
                doi=item.get("doi", ""),
                url=item.get("url", ""),
                confidence=0.2 if item.get("doi") or item.get("url") else 0.1,
                status="unverified" if item.get("doi") or item.get("url") else "risky",
            )
            citation.metadata = {  # type: ignore[attr-defined]
                "raw_reference": raw_ref,
                "title": item.get("title", ""),
                "authors": item.get("authors", []),
                "year": item.get("year", ""),
                "journal_or_publisher": item.get("source", ""),
                "search_query": cls.build_reference_search_query(item),
                "verification_note": "用户粘贴或 AI 生成的参考文献，尚未通过 DOI/URL、上传原文或可信数据库核验。",
            }
            project.citations = [c for c in project.citations if getattr(c, "id", "") != citation_id]
            project.add_citation(citation)
            imported.append(citation)
        return imported

    @classmethod
    def build_reference_search_query(cls, reference: Dict[str, Any] | Citation | str) -> str:
        """生成用于知网/万方/期刊官网/搜索引擎核验的检索词。"""
        if isinstance(reference, str):
            parsed = cls._parse_single_reference(reference)
        elif isinstance(reference, Citation):
            meta = getattr(reference, "metadata", {}) or {}
            parsed = {
                "title": meta.get("title", ""),
                "authors": meta.get("authors", []),
                "year": meta.get("year", ""),
                "source": getattr(reference, "source", "") or meta.get("journal_or_publisher", ""),
                "raw": getattr(reference, "formatted_ref", ""),
            }
        else:
            parsed = reference
        parts: List[str] = []
        authors = parsed.get("authors") or []
        if authors:
            parts.append(str(authors[0]))
        for key in ("title", "source", "year"):
            value = str(parsed.get(key, "") or "").strip()
            if value:
                parts.append(value)
        return " ".join(parts) or str(parsed.get("raw", "") or "").strip()

    @classmethod
    def reference_verification_links(cls, query: str) -> Dict[str, str]:
        """返回人工核验入口链接；实际是否可访问取决于用户网络与账号权限。"""
        encoded = quote_plus(query.strip())
        if not encoded:
            return {}
        return {
            "通用网页检索": f"https://www.baidu.com/s?wd={encoded}",
            "Google Scholar": f"https://scholar.google.com/scholar?q={encoded}",
            "Crossref DOI": f"https://search.crossref.org/?q={encoded}",
            "Semantic Scholar": f"https://www.semanticscholar.org/search?q={encoded}",
        }

    @classmethod
    def citation_risk_summary(cls, project: Any) -> Dict[str, int]:
        """统计引用核验和完整性风险。"""
        citations = cls.list_citations(project)
        summary = {
            "total": len(citations),
            "verified": 0,
            "unverified": 0,
            "missing_source_id": 0,
            "missing_locator": 0,
            "risky": 0,
        }

        for citation in citations:
            status = str(cls._get_value(citation, "status", "unverified") or "unverified")
            if status == "verified":
                summary["verified"] += 1
            else:
                summary["unverified"] += 1
            if status in {"risky", "missing_source"}:
                summary["risky"] += 1
            if not cls._has_source_id(citation):
                summary["missing_source_id"] += 1
            if not cls._has_locator(citation):
                summary["missing_locator"] += 1

        return summary

    @classmethod
    def bind_evidence_to_citation(
        cls,
        project: ProjectKnowledgeBase,
        evidence_chunk_id: str,
        sentence: str,
        *,
        style: str = "GB/T 7714",
        confidence: float = 0.8,
    ) -> Citation:
        """基于证据片段创建或更新引用记录。

        这是第二轮引用闭环的核心入口：从 ``EvidenceChunk`` 取来源、页码、DOI/URL
        等信息，生成绑定 ``evidence_chunk_id`` 的 ``Citation``，避免事实性引用无来源。
        """
        chunk = cls.find_evidence_chunk(project, evidence_chunk_id)
        if chunk is None:
            raise ValueError(f"Evidence chunk not found: {evidence_chunk_id}")

        document = cls.find_source_document(project, getattr(chunk, "document_id", ""))
        citation = Citation(
            id=cls._citation_id(evidence_chunk_id, sentence),
            evidence_chunk_id=evidence_chunk_id,
            sentence=sentence.strip(),
            source=getattr(document, "title", "") or getattr(chunk, "source", ""),
            page=getattr(chunk, "page_start", None),
            quote_original=getattr(chunk, "text", ""),
            formatted_ref=cls.format_reference(document, chunk, style=style),
            style=style,
            source_type=getattr(document, "source_type", "") if document else "",
            doi=getattr(document, "doi", "") if document else "",
            isbn=getattr(document, "isbn", "") if document else "",
            url=getattr(document, "url", "") if document else "",
            confidence=max(0.0, min(1.0, float(confidence))),
            status="verified" if document else "missing_source",
        )

        project.citations = [c for c in project.citations if getattr(c, "id", "") != citation.id]
        project.add_citation(citation)
        return citation

    @staticmethod
    def find_evidence_chunk(project: ProjectKnowledgeBase, evidence_chunk_id: str) -> Optional[EvidenceChunk]:
        """按 ID 查找证据片段。"""
        return next((chunk for chunk in project.evidence_chunks if getattr(chunk, "id", "") == evidence_chunk_id), None)

    @staticmethod
    def find_source_document(project: ProjectKnowledgeBase, document_id: str) -> Optional[SourceDocument]:
        """按 ID 查找来源文档。"""
        return next((doc for doc in project.source_documents if getattr(doc, "id", "") == document_id), None)

    @staticmethod
    def format_reference(document: Optional[SourceDocument], chunk: EvidenceChunk, *, style: str = "GB/T 7714") -> str:
        """生成轻量参考文献文本，后续可替换为完整格式化器。"""
        if document is None:
            return getattr(chunk, "source", "") or "未知来源"
        authors = ", ".join(getattr(document, "authors", []) or [])
        title = getattr(document, "title", "") or getattr(document, "file_name", "") or "未命名资料"
        year = getattr(document, "year", "") or "n.d."
        locator = f": {getattr(chunk, 'page_start', '')}" if getattr(chunk, "page_start", None) else ""
        doi = f" DOI:{document.doi}" if getattr(document, "doi", "") else ""
        return f"{authors + '. ' if authors else ''}{title}[{document.source_type or 'Z'}]. {year}{locator}.{doi}".strip()

    @classmethod
    def coverage_matrix(cls, project: ProjectKnowledgeBase) -> List[Dict[str, Any]]:
        """返回引用与证据、来源的绑定矩阵。"""
        rows: List[Dict[str, Any]] = []
        for citation in project.citations:
            chunk = cls.find_evidence_chunk(project, getattr(citation, "evidence_chunk_id", ""))
            document = cls.find_source_document(project, getattr(chunk, "document_id", "") if chunk else "")
            rows.append(
                {
                    "citation_id": getattr(citation, "id", ""),
                    "status": getattr(citation, "status", "unverified"),
                    "has_evidence": chunk is not None,
                    "has_source_document": document is not None,
                    "source": getattr(citation, "source", ""),
                    "page": getattr(citation, "page", None),
                    "confidence": getattr(citation, "confidence", 0.0),
                }
            )
        return rows

    @classmethod
    def _parse_single_reference(cls, raw: str) -> Dict[str, Any]:
        cleaned = re.sub(r"^\s*\[?\d+\]?\s*", "", raw).strip().strip("。.")
        source_type_match = re.search(r"\[([JMCDEPRZ])\]", cleaned, flags=re.IGNORECASE)
        source_type = source_type_match.group(1).upper() if source_type_match else ""
        doi_match = re.search(r"(?:DOI[:：]?\s*|doi[:：]?\s*)(10\.\S+)", cleaned)
        url_match = re.search(r"https?://\S+", cleaned)
        year_match = re.search(r"(?:19|20)\d{2}", cleaned)

        before_type = cleaned.split(source_type_match.group(0), 1)[0] if source_type_match else cleaned
        title = ""
        authors: List[str] = []
        source = ""
        if "．" in before_type:
            author_part, title_part = before_type.split("．", 1)
            authors = [a.strip() for a in re.split(r"[，,、]\s*", author_part) if a.strip() and a.strip() != "等"]
            title = title_part.strip()
        elif "." in before_type:
            author_part, title_part = before_type.split(".", 1)
            authors = [a.strip() for a in re.split(r"[，,、]\s*", author_part) if a.strip() and a.strip() != "等"]
            title = title_part.strip()

        after_type = cleaned.split(source_type_match.group(0), 1)[1] if source_type_match else ""
        if after_type:
            source_part = re.split(r"[，,]", after_type.strip("．.，, "), maxsplit=1)[0]
            source = source_part.strip("．.，, ")

        return {
            "raw": raw.strip(),
            "authors": authors,
            "title": title,
            "source_type": source_type,
            "source": source,
            "year": year_match.group(0) if year_match else "",
            "doi": doi_match.group(1).rstrip("。.") if doi_match else "",
            "url": url_match.group(0).rstrip("。.") if url_match else "",
        }

    @staticmethod
    def _raw_reference_id(raw_reference: str) -> str:
        return hashlib.md5(f"raw-reference:{raw_reference}".encode("utf-8", errors="ignore")).hexdigest()[:16]

    @staticmethod
    def _get_value(record: Any, key: str, default: Any = None) -> Any:
        if isinstance(record, dict):
            return record.get(key, default)
        return getattr(record, key, default)

    @classmethod
    def _has_source_id(cls, citation: Any) -> bool:
        return bool(cls._get_value(citation, "evidence_chunk_id", "") or cls._get_value(citation, "source", ""))

    @classmethod
    def _has_locator(cls, citation: Any) -> bool:
        return cls._get_value(citation, "page") not in (None, "")

    @staticmethod
    def _citation_id(evidence_chunk_id: str, sentence: str) -> str:
        raw = f"{evidence_chunk_id}:{sentence[:120]}"
        return hashlib.md5(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]
