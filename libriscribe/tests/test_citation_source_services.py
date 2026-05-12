from __future__ import annotations

from libriscribe.knowledge_base import Citation, EvidenceChunk, ProjectKnowledgeBase, SourceDocument
from libriscribe.services.citation_service import CitationService
from libriscribe.services.source_service import SourceService


SAMPLE_REFERENCES = """[1]张成英，姜涌，官名昊，林澎，陈禄阳，辛鲁超．建设工程数字化管理的建筑信息模型构件编码标准及应用[J]．建筑技术，2025(1)：4-7．
[2]侯朝，郝丁默，杨阳，刘占省．智能建造及智慧工地管理系统在施工中的应用[J]. 建筑技术，2025，56(1)：27-30．
[7]刁尚东．智慧代建体系构建与关键技术：数字化转型升级研究与实践[M]．北京：中国建筑工业出版社，2022．"""


def test_citation_service_binds_evidence_to_verified_citation() -> None:
    project = ProjectKnowledgeBase(project_name="demo", title="Demo")
    project.add_source_document(
        SourceDocument(id="doc1", title="测试资料", authors=["张三"], year="2024", source_type="M", doi="10.1/demo")
    )
    project.add_evidence_chunk(
        EvidenceChunk(id="chunk1", document_id="doc1", source="测试资料", text="这是一个可用的证据片段，用于支撑正文论断。", page_start=12)
    )

    citation = CitationService().bind_evidence_to_citation(project, "chunk1", "正文论断需要证据。")

    assert citation.status == "verified"
    assert citation.evidence_chunk_id == "chunk1"
    assert citation.page == 12
    assert CitationService().citation_risk_summary(project)["verified"] == 1


def test_citation_service_imports_pasted_references_as_risky_unverified() -> None:
    project = ProjectKnowledgeBase(project_name="demo", title="Demo")

    parsed = CitationService.parse_reference_text(SAMPLE_REFERENCES)
    imported = CitationService.import_reference_text(project, SAMPLE_REFERENCES)
    summary = CitationService.citation_risk_summary(project)

    assert len(parsed) == 3
    assert parsed[0]["title"] == "建设工程数字化管理的建筑信息模型构件编码标准及应用"
    assert parsed[0]["source"] == "建筑技术"
    assert parsed[0]["year"] == "2025"
    assert parsed[2]["source_type"] == "M"
    assert len(imported) == 3
    assert all(c.status == "risky" for c in imported)
    assert all(c.confidence == 0.1 for c in imported)
    assert summary["risky"] == 3
    assert "智慧代建体系" in CitationService.build_reference_search_query(imported[2])



def test_citation_service_builds_external_verification_links() -> None:
    links = CitationService.reference_verification_links("智慧工地 建筑技术 2025")

    assert "通用网页检索" in links
    assert "Crossref DOI" in links
    assert "智慧" not in links["通用网页检索"]



def test_source_service_reports_document_coverage_and_bad_chunks() -> None:
    project = ProjectKnowledgeBase(project_name="demo", title="Demo")
    project.source_documents.append(SourceDocument(id="doc1", title="资料A"))
    project.evidence_chunks.append(EvidenceChunk(id="c1", document_id="doc1", text="正常证据文本，包含足够的中文内容用于判断。"))
    project.evidence_chunks.append(EvidenceChunk(id="c2", document_id="doc1", text="\x00\x00bad"))
    project.citations.append(Citation(evidence_chunk_id="c1", source="资料A", page=1, status="verified"))

    summary = SourceService().source_summary(project)
    coverage = SourceService().document_coverage(project)

    assert summary["documents"] == 1
    assert summary["bad_chunks"] == 1
    assert coverage[0]["citations"] == 1
