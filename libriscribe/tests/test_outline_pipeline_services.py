from __future__ import annotations

from libriscribe.knowledge_base import Chapter, ChapterSection, ProjectKnowledgeBase
from libriscribe.services.literature_search_service import LiteratureSearchService
from libriscribe.services.outline_service import OutlineService
from libriscribe.services.pipeline_service import PipelineService


def test_outline_and_pipeline_services_report_basic_status() -> None:
    project = ProjectKnowledgeBase(project_name="demo", title="Demo", category="专著", genre="测试")
    project.chapters[1] = Chapter(
        chapter_number=1,
        title="第一章",
        sections=[ChapterSection(section_number="1.1", title="背景", level=2, word_count=1200)],
    )

    outline = OutlineService().outline_summary(project)
    pipeline = PipelineService().get_pipeline(project)

    assert outline["chapters"] == 1
    assert outline["sections"] == 1
    assert outline["target_words"] == 1200
    assert [stage["key"] for stage in pipeline] == [
        "briefing",
        "knowledge_injection",
        "outline_planning",
        "draft_writing",
        "visual_polish",
        "delivery",
    ]
    assert pipeline[0]["user_action"]
    assert pipeline[0]["primary_route"] == "workspace"
    assert pipeline[4]["optional"] is True


def test_literature_search_service_prepares_openalex_import_candidate() -> None:
    service = LiteratureSearchService()
    url = service.build_openalex_search_url("智慧工地 建筑技术 2025", limit=5, api_key="secret", recent_years=10)
    semantic_url = service.build_openalex_search_url(
        "智慧工地通过 BIM 与 AIoT 实现施工现场安全风险预测和项目协同管理。",
        limit=5,
        api_key="secret",
        recent_years=10,
        search_mode="semantic",
    )

    assert "api.openalex.org/works" in url
    assert "search=" in url
    assert "per_page=5" in url
    assert "cited_by_count" not in url
    assert "type%3Aarticle" in url or "type:article" in url
    assert "publication_year" in url
    assert "secret" not in url
    assert "search.semantic=" in semantic_url
    assert "cited_by_count" not in semantic_url
    assert "secret" not in semantic_url

    work = {
        "id": "https://openalex.org/W123",
        "doi": "https://doi.org/10.1234/demo",
        "title": "智能建造研究",
        "publication_year": 2025,
        "authorships": [{"author": {"display_name": "张三"}}, {"author": {"display_name": "李四"}}],
        "primary_location": {"source": {"display_name": "建筑技术"}, "landing_page_url": "https://example.com/paper"},
        "biblio": {"volume": "56", "issue": "1", "first_page": "27", "last_page": "30"},
        "abstract_inverted_index": {"这是": [0], "摘要": [1]},
        "concepts": [{"display_name": "智能建造"}],
    }
    normalized = service.normalize_openalex_work(work)
    formatted = service.format_citation(normalized, 1)
    project = ProjectKnowledgeBase(project_name="demo", title="Demo")
    document = service.import_work_as_source(project, work)
    imported = service.import_formatted_citations(project, [formatted], keywords="智能建造")

    assert normalized["doi"] == "10.1234/demo"
    assert normalized["authors"] == ["张三", "李四"]
    assert normalized["publication_name"] == "建筑技术"
    assert formatted == "[1]张三，李四．智能建造研究[J]．建筑技术，2025，56(1):27-30．"
    assert service.citation_missing_reasons(normalized) == []
    assert document.source_type == "external_literature"
    assert document.metadata["external_provider"] == "openalex"
    assert project.source_documents[0].id == document.id
    assert imported[0].status == "verified"
    assert imported[0].confidence == 0.95
    assert imported[0].metadata["external_provider"] == "openalex"
    assert "无需进入二次核验流程" in imported[0].metadata["verification_note"]


def test_literature_service_extracts_outline_queries_and_imports_verified_match() -> None:
    service = LiteratureSearchService()
    project = ProjectKnowledgeBase(project_name="demo", title="智慧工地数字化管理")
    project.chapters[1] = Chapter(
        chapter_number=1,
        title="智能建造与智慧工地管理系统",
        sections=[ChapterSection(section_number="1.1", title="BIM 与 AIoT 平台", level=2)],
    )

    queries = service.outline_search_queries(project, max_queries=4)
    assert "智慧工地数字化管理" in queries
    assert any("智能建造" in query for query in queries)

    normalized = service.normalize_openalex_work(
        {
            "id": "https://openalex.org/W456",
            "doi": "https://doi.org/10.33142/aem.v7i5.16798",
            "title": "建筑工程的施工技术及其现场的施工管理的探讨",
            "publication_year": 2025,
            "authorships": [{"author": {"display_name": "张三"}}],
            "primary_location": {"source": {"display_name": "建筑工程与管理"}, "landing_page_url": "https://example.com/work"},
            "biblio": {"volume": "7", "issue": "5", "first_page": "41", "last_page": "41"},
        }
    )
    result = {
        "raw_reference": "[1]张三．建筑工程的施工技术及其现场的施工管理的探讨[J]．建筑工程与管理，2025，7(5):41-41．",
        "status": "verified_by_api",
        "confidence": 0.95,
        "best_match": normalized,
        "matched_fields": ["题名", "年份", "刊名/来源"],
        "missing_fields": [],
    }

    imported = service.import_verified_results(project, [result])

    assert len(imported["documents"]) == 1
    assert len(imported["citations"]) == 1
    assert project.source_documents[0].doi == "10.33142/aem.v7i5.16798"
    assert project.citations[0].status == "verified"
    assert project.citations[0].metadata["verification_status"] == "verified_by_api"


def test_literature_semantic_search_uses_search_semantic_without_citation_sort(monkeypatch) -> None:
    service = LiteratureSearchService()
    calls = []

    class DummyResponse:
        url = "https://api.openalex.org/works?search.semantic=demo&api_key=secret"

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {"meta": {"count": 1}, "results": [{"id": "https://openalex.org/W1", "title": "Semantic BIM safety", "publication_year": 2024}]}

    def fake_get(url, params, timeout):
        calls.append({"url": url, "params": params, "timeout": timeout})
        return DummyResponse()

    monkeypatch.setattr("libriscribe.services.literature_search_service.requests.get", fake_get)

    diagnostics = service.search_with_diagnostics(
        "智慧工地通过 BIM 与 AIoT 实现安全风险预测。" * 80,
        api_key="secret",
        limit=5,
        recent_years=5,
        search_mode="semantic",
    )

    params = calls[0]["params"]
    assert "search.semantic" in params
    assert "search" not in params
    assert len(params["search.semantic"]) == 2000
    assert "sort" not in params
    assert "type:article" in params["filter"]
    assert "publication_year" in params["filter"]
    assert diagnostics["search_mode"] == "semantic"
    assert "secret" not in diagnostics["api_url"]


def test_literature_search_language_filter_and_relevance_defaults() -> None:
    service = LiteratureSearchService()

    zh_params = service._openalex_params("智慧工地 数字化管理", language_filter="中文文献")
    en_params = service._openalex_params("construction site digital management", language_filter="英文文献")
    all_params = service._openalex_params("BIM AIoT", language_filter="全部文献")

    assert "language:zh" in zh_params["filter"]
    assert "language:en" in en_params["filter"]
    assert "language:" not in all_params["filter"]
    assert "sort" not in zh_params
    assert "sort" not in en_params


def test_literature_search_by_outline_passes_language_filter(monkeypatch) -> None:
    service = LiteratureSearchService()
    calls = []

    def fake_search_with_diagnostics(query, **kwargs):
        calls.append({"query": query, **kwargs})
        return {"items": []}

    monkeypatch.setattr(service, "search_with_diagnostics", fake_search_with_diagnostics)

    service.search_by_outline(
        type("Project", (), {"title": "智慧工地建设", "description": "工程现场数字化管理", "outline": ""})(),
        language_filter="zh",
        max_queries=1,
    )

    assert calls
    assert calls[0]["language_filter"] == "zh"


def test_literature_web_search_params_clamp_and_include_optional_fields() -> None:
    service = LiteratureSearchService()

    params = service._web_search_params(
        "智慧工地 文献核查",
        page=9,
        developer_id="10016362",
        developer_key="secret-key",
        tn="98010089_dg",
        cookie="session-cookie",
    )

    assert params["id"] == "10016362"
    assert params["key"] == "secret-key"
    assert params["words"] == "智慧工地 文献核查"
    assert params["page"] == 3
    assert params["tn"] == "98010089_dg"
    assert params["ck"] == "session-cookie"


def test_literature_web_search_fetches_first_three_pages_and_dedupes(monkeypatch) -> None:
    service = LiteratureSearchService()
    calls = []

    class DummyResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return self._payload

    def fake_get(url, params, timeout):
        calls.append({"url": url, "params": params, "timeout": timeout})
        page = params["page"]
        return DummyResponse(
            {
                "code": 200,
                "count": 2,
                "datas": [
                    {"title": f"第{page}页结果", "url": f"https://example.com/{page}"},
                    {"title": "重复结果", "url": "https://example.com/dup"},
                ],
            }
        )

    monkeypatch.setattr("libriscribe.services.literature_search_service.requests.get", fake_get)

    result = service.web_search(
        "智慧工地 文献核查",
        api_url="https://api.example.com/search?key=secret-key&ck=session-cookie",
        developer_id="10016362",
        developer_key="secret-key",
        tn="98010089_dg",
        pages=9,
        timeout=7,
    )

    assert [call["params"]["page"] for call in calls] == [1, 2, 3]
    assert all(call["timeout"] == 7 for call in calls)
    assert len(result["pages"]) == 3
    assert result["count"] == 4
    assert "secret-key" not in result["api_url"]
    assert "session-cookie" not in result["api_url"]
    assert [item["url"] for item in result["items"]] == [
        "https://example.com/1",
        "https://example.com/dup",
        "https://example.com/2",
        "https://example.com/3",
    ]
