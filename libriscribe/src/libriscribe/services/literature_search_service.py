"""外部文献检索与中文参考文献格式化服务。

OpenAlex 可免费检索真实学术文献。API Key 不应硬编码到源码中，Web 层
会从用户输入或环境变量传入，避免泄露到公开仓库。
"""

from __future__ import annotations

import hashlib
import os
import re
from html import unescape
from typing import Any, Dict, List, Optional

import requests

from libriscribe.knowledge_base import Citation, SourceDocument
from libriscribe.services.citation_service import CitationService


class LiteratureSearchService:
    """文献检索与外部数据库导入预留服务。"""

    DEFAULT_PROVIDER = "openalex"
    OPENALEX_WORKS_URL = "https://api.openalex.org/works"
    DEFAULT_WEB_SEARCH_URL = "https://api.apihz.cn/api/baidu/baidu"
    DEFAULT_TAVILY_BASE_URL = "https://api.tavily.com"

    def search(
        self,
        query: str,
        *,
        provider: str = DEFAULT_PROVIDER,
        limit: int = 10,
        api_key: str = "",
        recent_years: Optional[int] = None,
        journal_only: bool = True,
        timeout: int = 15,
        search_mode: str = "keyword",
        language_filter: str = "all",
    ) -> List[Dict[str, Any]]:
        """从 OpenAlex 检索真实文献并返回规范化结果。"""
        return self.search_with_diagnostics(
            query,
            provider=provider,
            limit=limit,
            api_key=api_key,
            recent_years=recent_years,
            journal_only=journal_only,
            timeout=timeout,
            search_mode=search_mode,
            language_filter=language_filter,
        )["items"]

    def search_with_diagnostics(
        self,
        query: str,
        *,
        provider: str = DEFAULT_PROVIDER,
        limit: int = 10,
        api_key: str = "",
        recent_years: Optional[int] = None,
        journal_only: bool = True,
        timeout: int = 15,
        search_mode: str = "keyword",
        language_filter: str = "all",
    ) -> Dict[str, Any]:
        """检索 OpenAlex，并返回可用于 UI 诊断的候选、可格式化结果与剔除原因。"""
        normalized_provider = (provider or self.DEFAULT_PROVIDER).lower().strip()
        normalized_mode = self._normalize_search_mode(search_mode)
        normalized_language = self._normalize_language_filter(language_filter)
        safe_limit = max(1, min(int(limit or 10), 10))
        empty = {"items": [], "raw_count": 0, "meta": {}, "rejected": [], "api_url": "", "search_mode": normalized_mode, "language_filter": normalized_language}
        if not query.strip() or normalized_provider != "openalex":
            return empty

        params = self._openalex_params(
            query,
            limit=safe_limit,
            api_key=api_key,
            recent_years=recent_years,
            journal_only=journal_only,
            search_mode=normalized_mode,
            language_filter=normalized_language,
        )
        response = requests.get(self.OPENALEX_WORKS_URL, params=params, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        raw_results = payload.get("results", []) or []
        items = [
            item for item in (self.normalize_openalex_work(work) for work in raw_results)
            if self._language_matches(item, normalized_language)
        ]
        rejected = [
            {"title": item.get("title") or "未命名文献", "reason": "；".join(self.citation_missing_reasons(item)), "item": item}
            for item in items
            if self.citation_missing_reasons(item)
        ]
        return {
            "items": items,
            "raw_count": len(raw_results),
            "meta": payload.get("meta", {}) or {},
            "rejected": rejected,
            "api_url": response.url.replace(str(params.get("api_key", "")), "***") if params.get("api_key") else response.url,
            "search_mode": normalized_mode,
            "language_filter": normalized_language,
        }

    def build_openalex_search_url(
        self,
        query: str,
        *,
        limit: int = 10,
        api_key: str = "",
        recent_years: Optional[int] = None,
        journal_only: bool = True,
        search_mode: str = "keyword",
        language_filter: str = "all",
    ) -> str:
        """构造 OpenAlex Works 检索 URL（隐藏 API Key 明文展示）。"""
        params = self._openalex_params(
            query,
            limit=limit,
            api_key=api_key,
            recent_years=recent_years,
            journal_only=journal_only,
            search_mode=search_mode,
            language_filter=language_filter,
        )
        safe_params = {key: ("***" if key == "api_key" else value) for key, value in params.items()}
        query_text = requests.Request("GET", self.OPENALEX_WORKS_URL, params=safe_params).prepare().url
        return query_text or self.OPENALEX_WORKS_URL

    def web_search(
        self,
        query: str,
        *,
        api_url: str = "",
        developer_id: str = "",
        developer_key: str = "",
        tn: str = "",
        cookie: str = "",
        dkey: str = "",
        uip: str = "",
        pages: int = 3,
        timeout: int = 15,
    ) -> Dict[str, Any]:
        """调用通用网页搜索 API，默认检索前三页并合并去重。"""
        endpoint = (api_url or os.getenv("WEB_SEARCH_API_URL", "") or self.DEFAULT_WEB_SEARCH_URL).strip()
        safe_pages = max(1, min(int(pages or 3), 3))
        if not query.strip():
            return {"items": [], "pages": [], "count": 0, "api_url": self._mask_web_search_url(endpoint)}
        items: List[Dict[str, Any]] = []
        page_results: List[Dict[str, Any]] = []
        seen = set()
        for page in range(1, safe_pages + 1):
            params = self._web_search_params(
                query,
                page=page,
                developer_id=developer_id,
                developer_key=developer_key,
                tn=tn,
                cookie=cookie,
                dkey=dkey,
                uip=uip,
            )
            response = requests.get(endpoint, params=params, timeout=timeout)
            response.raise_for_status()
            payload = response.json()
            raw_items = payload.get("datas", []) or []
            normalized_items = []
            for raw in raw_items:
                normalized = {
                    "title": raw.get("title", ""),
                    "url": raw.get("url", ""),
                    "page": page,
                    "query": query.strip(),
                    "provider": "web_search_api",
                    "raw": raw,
                }
                key = normalized["url"] or normalized["title"]
                if key and key not in seen:
                    seen.add(key)
                    items.append(normalized)
                    normalized_items.append(normalized)
            page_results.append(
                {
                    "page": page,
                    "code": payload.get("code"),
                    "msg": payload.get("msg", ""),
                    "count": payload.get("count", len(raw_items)),
                    "items": normalized_items,
                }
            )
        return {
            "items": items,
            "pages": page_results,
            "count": len(items),
            "api_url": self._mask_web_search_url(endpoint),
        }

    def tavily_search(
        self,
        query: str,
        *,
        api_key: str = "",
        base_url: str = "",
        max_results: int = 10,
        search_depth: str = "advanced",
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """调用 Tavily 搜索并返回与现有网页搜索一致的归一化结果结构。"""
        resolved_key = self._normalize_secret_value(api_key or os.getenv("TAVILY_API_KEY", ""))
        resolved_base_url = self._normalize_url_value(base_url or os.getenv("TAVILY_BASE_URL", "") or self.DEFAULT_TAVILY_BASE_URL)
        safe_limit = max(1, min(int(max_results or os.getenv("TAVILY_MAX_RESULTS", "10") or 10), 20))
        depth = str(search_depth or os.getenv("TAVILY_SEARCH_DEPTH", "advanced") or "advanced").strip().lower()
        if depth not in {"basic", "advanced"}:
            depth = "advanced"
        if not query.strip():
            return {"items": [], "pages": [], "count": 0, "api_url": resolved_base_url, "provider": "tavily"}
        if not resolved_key:
            raise ValueError("Tavily API Key 未配置，请设置 TAVILY_API_KEY 或在界面中输入。")

        try:
            from tavily import TavilyClient
        except ImportError as exc:
            raise RuntimeError("缺少 tavily-python 依赖，请先安装 requirements.txt 中的 tavily-python。") from exc

        client_kwargs: Dict[str, Any] = {"api_key": resolved_key}
        if resolved_base_url:
            client_kwargs["api_base_url"] = resolved_base_url
        client = TavilyClient(**client_kwargs)
        search_params: Dict[str, Any] = {
            "query": query.strip(),
            "max_results": safe_limit,
            "search_depth": depth,
            "include_answer": True,
            "include_raw_content": False,
        }
        if include_domains:
            search_params["include_domains"] = include_domains
        if exclude_domains:
            search_params["exclude_domains"] = exclude_domains

        response = client.search(**search_params)
        raw_items = response.get("results", []) if isinstance(response, dict) else []
        items = [self._normalize_tavily_result(raw, query=query, rank=index + 1) for index, raw in enumerate(raw_items)]
        return {
            "items": items,
            "pages": [
                {
                    "page": 1,
                    "code": 200,
                    "msg": "Tavily search completed",
                    "count": len(items),
                    "items": items,
                }
            ],
            "count": len(items),
            "api_url": resolved_base_url,
            "provider": "tavily",
            "answer": response.get("answer", "") if isinstance(response, dict) else "",
            "raw": response,
        }

    def fetch_web_page_text(self, url: str, *, timeout: int = 12, max_chars: int = 24000) -> Dict[str, Any]:
        """打开搜索结果链接并抽取网页正文；返回诊断信息而不是抛出异常。

        百度搜索 API 常只返回 baidu/link 跳转地址和标题。这里会跟随跳转，
        读取最终网页 HTML，移除脚本/样式/标签后得到可交给 AI 筛选的正文片段。
        """
        cleaned_url = str(url or "").strip()
        if not cleaned_url:
            return {"ok": False, "url": "", "final_url": "", "text": "", "error": "URL 为空"}
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.5",
        }
        try:
            response = requests.get(cleaned_url, headers=headers, timeout=timeout, allow_redirects=True)
            status_code = response.status_code
            content_type = response.headers.get("content-type", "")
            final_url = response.url or cleaned_url
            if status_code >= 400:
                return {
                    "ok": False,
                    "url": cleaned_url,
                    "final_url": final_url,
                    "status_code": status_code,
                    "content_type": content_type,
                    "text": "",
                    "error": f"网页请求失败：HTTP {status_code}",
                }
            if "html" not in content_type.lower() and "text" not in content_type.lower() and content_type:
                return {
                    "ok": False,
                    "url": cleaned_url,
                    "final_url": final_url,
                    "status_code": status_code,
                    "content_type": content_type,
                    "text": "",
                    "error": f"非网页文本内容：{content_type}",
                }
            response.encoding = response.encoding or response.apparent_encoding or "utf-8"
            html = response.text or ""
            text = self.extract_readable_text(html, max_chars=max_chars)
            if len(text) < 120:
                return {
                    "ok": False,
                    "url": cleaned_url,
                    "final_url": final_url,
                    "status_code": status_code,
                    "content_type": content_type,
                    "text": text,
                    "error": "网页正文过短或无法抽取有效文本",
                }
            return {
                "ok": True,
                "url": cleaned_url,
                "final_url": final_url,
                "status_code": status_code,
                "content_type": content_type,
                "text": text,
                "error": "",
            }
        except Exception as exc:  # pragma: no cover - 网络环境不可控，单测用 fake service 覆盖
            return {"ok": False, "url": cleaned_url, "final_url": cleaned_url, "text": "", "error": str(exc)}

    @staticmethod
    def extract_readable_text(html: str, *, max_chars: int = 24000) -> str:
        """用标准库规则从 HTML 中抽取足够干净的可读文本。"""
        text = re.sub(r"(?is)<(script|style|noscript|svg|canvas|iframe).*?>.*?</\\1>", " ", str(html or ""))
        text = re.sub(r"(?i)<br\s*/?>", "\n", text)
        text = re.sub(r"(?i)</(p|div|li|tr|h[1-6]|section|article|dd|dt)>", "\n", text)
        text = re.sub(r"<[^>]+>", " ", text)
        text = unescape(text)
        lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
        cleaned = "\n".join(line for line in lines if len(line) >= 2)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
        return cleaned[:max_chars]

    def outline_search_queries(self, project: Any, *, max_queries: int = 8) -> List[str]:
        """从项目标题、描述和大纲章节中提取可直接检索的文献查询词。"""
        candidates: List[str] = []
        for value in [
            getattr(project, "title", ""),
            getattr(project, "category", ""),
            getattr(project, "description", ""),
        ]:
            cleaned = self._clean_query(value)
            if cleaned:
                candidates.append(cleaned)

        chapters = getattr(project, "chapters", {}) or {}
        chapter_items = chapters.items() if hasattr(chapters, "items") else enumerate(chapters, 1)
        for _, chapter in chapter_items:
            chapter_title = self._clean_query(getattr(chapter, "title", ""))
            if chapter_title:
                candidates.append(chapter_title)
            for section in (getattr(chapter, "sections", []) or [])[:3]:
                section_title = self._clean_query(getattr(section, "title", ""))
                if section_title and chapter_title:
                    candidates.append(f"{chapter_title} {section_title}")
                elif section_title:
                    candidates.append(section_title)

        outline_text = getattr(project, "outline", "") or ""
        for line in str(outline_text).splitlines():
            cleaned = self._clean_query(re.sub(r"^[第\d一二三四五六七八九十百章节、\.\s（）()]+", "", line))
            if cleaned:
                candidates.append(cleaned)
            if len(candidates) >= max_queries * 2:
                break

        deduped: List[str] = []
        seen = set()
        for query in candidates:
            key = query.lower()
            if key not in seen:
                seen.add(key)
                deduped.append(query[:120])
            if len(deduped) >= max_queries:
                break
        return deduped

    def search_by_outline(
        self,
        project: Any,
        *,
        api_key: str = "",
        limit_per_query: int = 3,
        recent_years: Optional[int] = None,
        max_queries: int = 6,
        search_mode: str = "semantic",
        language_filter: str = "all",
    ) -> List[Dict[str, Any]]:
        """根据项目大纲批量检索 OpenAlex，返回去重后的候选文献。"""
        results: List[Dict[str, Any]] = []
        seen = set()
        for query in self.outline_search_queries(project, max_queries=max_queries):
            diagnostics = self.search_with_diagnostics(
                query,
                limit=limit_per_query,
                api_key=api_key,
                recent_years=recent_years,
                journal_only=True,
                search_mode=search_mode,
                language_filter=language_filter,
            )
            for item in diagnostics.get("items", []):
                key = item.get("external_id") or item.get("doi") or item.get("title")
                if not key or key in seen:
                    continue
                seen.add(key)
                enriched = dict(item)
                enriched["search_query"] = query
                enriched["missing_reasons"] = self.citation_missing_reasons(item)
                enriched["formatted_citation"] = self.format_citation(item, len(results) + 1)
                results.append(enriched)
        return results

    def verify_reference(self, raw_reference: str, *, api_key: str = "", timeout: int = 15) -> Dict[str, Any]:
        """对单条参考文献执行 OpenAlex 二次核验，并返回透明匹配结果。"""
        parsed = CitationService.parse_reference_text(raw_reference)
        reference = parsed[0] if parsed else {"raw": raw_reference, "title": raw_reference, "authors": [], "year": "", "source": "", "doi": ""}
        query = reference.get("doi") or reference.get("title") or raw_reference
        diagnostics = self.search_with_diagnostics(
            str(query),
            limit=5,
            api_key=api_key,
            recent_years=None,
            journal_only=False,
            timeout=timeout,
        )
        candidates = diagnostics.get("items", [])
        scored = [self._score_reference_match(reference, candidate) for candidate in candidates]
        best = max(scored, key=lambda item: item["score"], default=None)
        status = "missing_source"
        confidence = 0.0
        if best:
            confidence = best["score"]
            if confidence >= 0.86:
                status = "verified_by_api"
            elif confidence >= 0.55:
                status = "partial_match"
            else:
                status = "risky"
        return {
            "raw_reference": raw_reference.strip(),
            "parsed": reference,
            "query": str(query),
            "status": status,
            "confidence": round(confidence, 2),
            "best_match": best["item"] if best else None,
            "matched_fields": best["matched_fields"] if best else [],
            "missing_fields": best["missing_fields"] if best else ["OpenAlex 未返回候选"],
            "candidates": [score["item"] for score in scored],
            "verification_links": CitationService.reference_verification_links(CitationService.build_reference_search_query(reference)),
            "api_url": diagnostics.get("api_url", ""),
        }

    def web_search_for_references(
        self,
        reference_text: str,
        *,
        api_url: str = "",
        developer_id: str = "",
        developer_key: str = "",
        tn: str = "",
        cookie: str = "",
        pages: int = 3,
        timeout: int = 15,
    ) -> List[Dict[str, Any]]:
        """按参考文献题名/检索式调用网页搜索 API，用于辅助真实性复核。"""
        parsed = CitationService.parse_reference_text(reference_text)
        raw_items = parsed or [{"raw": line.strip(), "title": line.strip()} for line in reference_text.splitlines() if line.strip()]
        results = []
        for ref in raw_items:
            query = CitationService.build_reference_search_query(ref)
            search_result = self.web_search(
                query,
                api_url=api_url,
                developer_id=developer_id,
                developer_key=developer_key,
                tn=tn,
                cookie=cookie,
                pages=pages,
                timeout=timeout,
            )
            results.append({"reference": ref, "query": query, "search": search_result})
        return results
 
    def verify_references(self, reference_text: str, *, api_key: str = "", timeout: int = 15) -> List[Dict[str, Any]]:
        """批量解析并核验粘贴的参考文献列表。"""
        parsed = CitationService.parse_reference_text(reference_text)
        raw_items = [item.get("raw", "") for item in parsed] or [line.strip() for line in reference_text.splitlines() if line.strip()]
        return [self.verify_reference(raw, api_key=api_key, timeout=timeout) for raw in raw_items if raw.strip()]

    def normalize_openalex_work(self, work: Dict[str, Any]) -> Dict[str, Any]:
        """将 OpenAlex work 原始 JSON 规范化为资料库候选文献。"""
        authorships = work.get("authorships") or []
        authors = []
        for authorship in authorships:
            author = authorship.get("author") or {}
            display_name = author.get("display_name")
            if display_name:
                authors.append(display_name)

        primary_location = work.get("primary_location") or {}
        source = primary_location.get("source") or {}
        host_venue = work.get("host_venue") or {}
        biblio = work.get("biblio") or {}
        doi = (work.get("doi") or "").replace("https://doi.org/", "")
        title = work.get("title") or work.get("display_name") or "未命名文献"
        openalex_id = work.get("id") or ""
        publication_name = source.get("display_name") or host_venue.get("display_name") or ""

        return {
            "external_provider": "openalex",
            "external_id": openalex_id,
            "doi": doi,
            "title": title,
            "authors": authors,
            "publication_year": work.get("publication_year") or "",
            "publication_name": publication_name,
            "language": work.get("language") or "",
            "volume": biblio.get("volume") or work.get("volume") or "",
            "issue": biblio.get("issue") or work.get("issue") or "",
            "first_page": biblio.get("first_page") or work.get("first_page") or "",
            "last_page": biblio.get("last_page") or work.get("last_page") or "",
            "type": work.get("type") or "journal-article",
            "url": work.get("landing_page_url") or primary_location.get("landing_page_url") or openalex_id,
            "abstract": self._abstract_from_inverted_index(work.get("abstract_inverted_index") or {}),
            "keywords": [concept.get("display_name", "") for concept in (work.get("concepts") or [])[:8] if concept.get("display_name")],
            "raw": work,
        }

    def format_citation(self, item: Dict[str, Any], index: int = 1) -> str:
        """按用户指定中文期刊论文格式输出参考文献。"""
        authors = item.get("authors") or []
        author_text = "佚名" if not authors else "，".join(authors[:3]) + ("，等" if len(authors) > 3 else "")
        title = str(item.get("title") or "").strip()
        journal = str(item.get("publication_name") or "").strip()
        year = str(item.get("publication_year") or "").strip()
        volume = str(item.get("volume") or "").strip()
        issue = str(item.get("issue") or "").strip()
        first_page = str(item.get("first_page") or "").strip()
        last_page = str(item.get("last_page") or "").strip()

        if self.citation_missing_reasons(item):
            return ""

        year_part = year
        if volume and issue:
            year_part = f"{year}，{volume}({issue})"
        elif issue:
            year_part = f"{year}({issue})"
        elif volume:
            year_part = f"{year}，{volume}"

        page_part = ""
        if first_page and last_page:
            page_part = f":{first_page}-{last_page}"
        elif first_page:
            page_part = f":{first_page}"

        return f"[{index}]{author_text}．{title}[J]．{journal}，{year_part}{page_part}．"

    def fetch_and_format_citations(
        self,
        keywords: str,
        num_results: int = 5,
        *,
        api_key: str = "",
        recent_years: Optional[int] = None,
    ) -> List[str]:
        """检索 OpenAlex 并返回格式化参考文献文本列表。"""
        diagnostics = self.search_with_diagnostics(
            keywords,
            limit=num_results,
            api_key=api_key or os.getenv("OPENALEX_API_KEY", ""),
            recent_years=recent_years,
            journal_only=True,
        )
        items = diagnostics["items"]
        citations: List[str] = []
        for item in items:
            formatted = self.format_citation(item, len(citations) + 1)
            if formatted:
                citations.append(formatted)
            if len(citations) >= num_results:
                break
        return citations

    def import_formatted_citations(self, project: Any, citations: List[str], *, keywords: str = "") -> List[Citation]:
        """把 OpenAlex 格式化结果导入项目引用库，并按产品流程标记为已核验。"""
        imported: List[Citation] = []
        for raw in citations:
            citation_id = "openalex-ref-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
            citation = Citation(
                id=citation_id,
                formatted_ref=raw,
                source="OpenAlex",
                source_type="J",
                confidence=0.95,
                status="verified",
                metadata={
                    "external_provider": "openalex",
                    "search_query": keywords,
                    "verification_note": "OpenAlex 数据库检索并格式化导入；本版本按已核验引用处理，无需进入二次核验流程。",
                },
            )
            project.citations = [c for c in getattr(project, "citations", []) if getattr(c, "id", "") != citation_id]
            project.add_citation(citation)
            imported.append(citation)
        return imported

    def import_verified_results(self, project: Any, verification_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """把二次核验结果中的最佳匹配加入资料库与引用记录。"""
        documents: List[SourceDocument] = []
        citations: List[Citation] = []
        for result in verification_results:
            best_match = result.get("best_match") or None
            if not best_match:
                continue
            documents.append(self.import_normalized_work_as_source(project, best_match, verification_result=result))
            formatted = self.format_citation(best_match, len(citations) + 1) or result.get("raw_reference", "")
            citation_id = "verified-ref-" + hashlib.sha1((result.get("raw_reference", "") + str(best_match.get("external_id", ""))).encode("utf-8")).hexdigest()[:12]
            status = "verified" if result.get("status") == "verified_by_api" else "unverified"
            citation = Citation(
                id=citation_id,
                formatted_ref=formatted,
                source=best_match.get("publication_name") or "OpenAlex",
                source_type="J",
                doi=best_match.get("doi", ""),
                url=best_match.get("url", ""),
                confidence=float(result.get("confidence") or 0),
                status=status,
                metadata={
                    "external_provider": "openalex",
                    "external_id": best_match.get("external_id", ""),
                    "raw_reference": result.get("raw_reference", ""),
                    "verification_status": result.get("status", ""),
                    "matched_fields": result.get("matched_fields", []),
                    "missing_fields": result.get("missing_fields", []),
                    "verification_note": "OpenAlex 二次核验结果；verified 表示题名/年份/刊名等字段高度匹配，仍建议最终核对原文。",
                },
            )
            project.citations = [c for c in getattr(project, "citations", []) if getattr(c, "id", "") != citation_id]
            project.add_citation(citation)
            citations.append(citation)
        return {"documents": documents, "citations": citations}

    def import_work_candidates(self, project: Any, items: List[Dict[str, Any]]) -> List[SourceDocument]:
        """把 OpenAlex 规范化候选批量加入资料库。"""
        return [self.import_normalized_work_as_source(project, item) for item in items]

    def import_work_as_source(self, project: Any, work: Dict[str, Any]) -> SourceDocument:
        """把 OpenAlex work 候选项转换为 ``SourceDocument`` 并加入项目资料库。"""
        normalized = self.normalize_openalex_work(work)
        return self.import_normalized_work_as_source(project, normalized)

    def import_normalized_work_as_source(self, project: Any, normalized: Dict[str, Any], *, verification_result: Optional[Dict[str, Any]] = None) -> SourceDocument:
        """把规范化 OpenAlex 文献转换为 ``SourceDocument`` 并加入项目资料库。"""
        source_id = self._source_id(normalized)
        metadata = dict(normalized)
        if verification_result:
            metadata["verification_result"] = {
                "status": verification_result.get("status"),
                "confidence": verification_result.get("confidence"),
                "matched_fields": verification_result.get("matched_fields", []),
                "missing_fields": verification_result.get("missing_fields", []),
            }
        document = SourceDocument(
            id=source_id,
            title=normalized["title"],
            authors=normalized.get("authors", []),
            year=str(normalized.get("publication_year") or ""),
            source_type="external_literature",
            file_name=f"openalex-{source_id}.json",
            file_path=normalized.get("url", ""),
            doi=normalized.get("doi", ""),
            url=normalized.get("url", ""),
            status="pending",
            metadata=metadata,
        )
        documents = getattr(project, "source_documents", None)
        if documents is not None:
            project.source_documents = [doc for doc in documents if getattr(doc, "id", "") != source_id]
            project.add_source_document(document)
        return document

    def _web_search_params(
        self,
        query: str,
        *,
        page: int,
        developer_id: str = "",
        developer_key: str = "",
        tn: str = "",
        cookie: str = "",
        dkey: str = "",
        uip: str = "",
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "id": developer_id or os.getenv("WEB_SEARCH_API_ID", ""),
            "key": developer_key or os.getenv("WEB_SEARCH_API_KEY", ""),
            "words": query.strip(),
            "page": max(1, min(int(page or 1), 3)),
        }
        optional = {
            "tn": tn or os.getenv("WEB_SEARCH_API_TN", ""),
            "ck": cookie or os.getenv("WEB_SEARCH_API_COOKIE", ""),
            "dkey": dkey or os.getenv("WEB_SEARCH_API_DKEY", ""),
            "uip": uip or os.getenv("WEB_SEARCH_API_UIP", ""),
        }
        params.update({key: value for key, value in optional.items() if value})
        return {key: value for key, value in params.items() if value}

    @staticmethod
    def _mask_web_search_url(url: str) -> str:
        masked = re.sub(r"(key=)[^&]+", r"\1***", url)
        masked = re.sub(r"(ck=)[^&]+", r"\1***", masked)
        return masked

    @staticmethod
    def _normalize_secret_value(value: Any) -> str:
        normalized = str(value or "").strip()
        return "" if normalized in {"********", "••••••••", "***"} else normalized

    @staticmethod
    def _normalize_url_value(value: Any) -> str:
        return str(value or "").strip().rstrip("/")

    @staticmethod
    def _normalize_tavily_result(raw: Dict[str, Any], *, query: str, rank: int) -> Dict[str, Any]:
        title = raw.get("title") or raw.get("url") or "Untitled"
        content = raw.get("content") or raw.get("snippet") or raw.get("raw_content") or ""
        return {
            "title": title,
            "url": raw.get("url", ""),
            "content": content,
            "snippet": content,
            "score": raw.get("score"),
            "rank": rank,
            "page": 1,
            "query": query.strip(),
            "provider": "tavily",
            "raw": raw,
        }

    def _openalex_params(
        self,
        query: str,
        *,
        limit: int = 10,
        api_key: str = "",
        recent_years: Optional[int] = None,
        journal_only: bool = True,
        search_mode: str = "keyword",
        language_filter: str = "all",
    ) -> Dict[str, Any]:
        safe_limit = max(1, min(int(limit or 10), 10))
        normalized_mode = self._normalize_search_mode(search_mode)
        normalized_language = self._normalize_language_filter(language_filter)
        filters = []
        if journal_only:
            # OpenAlex Works 的 type 取值是 article/review/book-chapter 等，
            # 不是 Crossref 常见的 journal-article；使用 journal-article 会导致中文期刊论文被过滤为空。
            filters.append("type:article")
        if normalized_language == "zh":
            filters.append("language:zh")
        elif normalized_language == "en":
            filters.append("language:en")
        if recent_years:
            from datetime import datetime

            start_year = datetime.now().year - int(recent_years)
            filters.append(f"publication_year:>{start_year}")
        params: Dict[str, Any] = {
            "search.semantic" if normalized_mode == "semantic" else "search": query.strip()[:2000],
            "per_page": safe_limit,
        }
        # 不再默认按 cited_by_count 排序，避免中文短词被高被引但不相关的英文/预印本文献挤占。
        # OpenAlex 默认相关性排序更适合专著章节检索；语义搜索也不支持 cited_by_count 排序。
        if filters:
            params["filter"] = ",".join(filters)
        resolved_key = api_key or os.getenv("OPENALEX_API_KEY", "")
        if resolved_key:
            params["api_key"] = resolved_key
        return params

    @staticmethod
    def _normalize_search_mode(search_mode: str) -> str:
        return "semantic" if str(search_mode or "").strip().lower() in {"semantic", "语义搜索", "语义"} else "keyword"

    @staticmethod
    def _normalize_language_filter(language_filter: str) -> str:
        value = str(language_filter or "all").strip().lower()
        if value in {"zh", "chinese", "中文", "只中文", "中文文献"}:
            return "zh"
        if value in {"en", "english", "英文", "只英文", "英文文献"}:
            return "en"
        return "all"

    @classmethod
    def _language_matches(cls, item: Dict[str, Any], language_filter: str) -> bool:
        normalized_language = cls._normalize_language_filter(language_filter)
        if normalized_language == "all":
            return True
        language = str(item.get("language") or "").lower()
        title = str(item.get("title") or "")
        abstract = str(item.get("abstract") or "")
        has_cjk = bool(re.search(r"[\u4e00-\u9fff]", f"{title}\n{abstract}"))
        if normalized_language == "zh":
            return language.startswith("zh") or has_cjk
        if normalized_language == "en":
            return language == "en" or (not language and not has_cjk)
        return True

    def _score_reference_match(self, reference: Dict[str, Any], item: Dict[str, Any]) -> Dict[str, Any]:
        matched: List[str] = []
        missing: List[str] = []
        score = 0.0
        ref_title = self._norm_text(reference.get("title", ""))
        item_title = self._norm_text(item.get("title", ""))
        if ref_title and item_title and (ref_title in item_title or item_title in ref_title):
            matched.append("题名")
            score += 0.45
        else:
            missing.append("题名未精确匹配")

        ref_year = str(reference.get("year") or "").strip()
        item_year = str(item.get("publication_year") or "").strip()
        if ref_year and item_year and ref_year == item_year:
            matched.append("年份")
            score += 0.15
        elif ref_year:
            missing.append("年份不一致或缺失")

        ref_source = self._norm_text(reference.get("source", ""))
        item_source = self._norm_text(item.get("publication_name", ""))
        if ref_source and item_source and (ref_source in item_source or item_source in ref_source):
            matched.append("刊名/来源")
            score += 0.15
        elif ref_source:
            missing.append("刊名/来源未匹配")

        ref_doi = self._norm_text(reference.get("doi", ""))
        item_doi = self._norm_text(item.get("doi", ""))
        if ref_doi and item_doi and ref_doi == item_doi:
            matched.append("DOI")
            score += 0.2
        elif ref_doi:
            missing.append("DOI 未匹配")

        ref_authors = [self._norm_text(a) for a in (reference.get("authors") or []) if a]
        item_authors = [self._norm_text(a) for a in (item.get("authors") or []) if a]
        if ref_authors and item_authors and any(a and any(a in b or b in a for b in item_authors) for a in ref_authors[:2]):
            matched.append("作者")
            score += 0.05
        elif ref_authors:
            missing.append("作者未匹配")

        if not self.citation_missing_reasons(item):
            score += 0.05
        return {"item": item, "score": min(score, 1.0), "matched_fields": matched, "missing_fields": missing}

    @staticmethod
    def citation_missing_reasons(item: Dict[str, Any]) -> List[str]:
        """返回候选文献无法生成用户指定中文期刊引用的字段原因。"""
        reasons = []
        if not str(item.get("title") or "").strip():
            reasons.append("缺少标题")
        if not str(item.get("publication_name") or "").strip():
            reasons.append("缺少刊名")
        if not str(item.get("publication_year") or "").strip():
            reasons.append("缺少年份")
        return reasons

    @staticmethod
    def _abstract_from_inverted_index(index: Dict[str, List[int]]) -> str:
        if not index:
            return ""
        positioned: List[tuple[int, str]] = []
        for word, positions in index.items():
            for position in positions or []:
                positioned.append((int(position), word))
        return " ".join(word for _, word in sorted(positioned))

    @staticmethod
    def _clean_query(value: Any) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip(" ：:，,。.;；")
        return text[:120]

    @staticmethod
    def _norm_text(value: Any) -> str:
        return re.sub(r"[\s\-—_：:，,。\.．\[\]【】（）()]+", "", str(value or "")).lower()

    @staticmethod
    def _source_id(normalized: Dict[str, Any]) -> str:
        raw_key = normalized.get("external_id") or normalized.get("doi") or normalized.get("title") or "openalex"
        digest = hashlib.sha1(str(raw_key).encode("utf-8")).hexdigest()[:12]
        return f"lit-{digest}"


def fetch_and_format_citations(keywords: str, num_results: int = 5) -> List[str]:
    """
    keywords: str, 检索关键词
    num_results: int, 返回的引用条目数量
    returns: list of str, 每一条已经是格式化好的引用文本
    """
    return LiteratureSearchService().fetch_and_format_citations(keywords, num_results=num_results)
