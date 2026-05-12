# src/libriscribe/export/reference_formatter.py
"""参考文献格式化（GB/T 7714）"""

import re
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)


class ReferenceFormatter:
    DOC_TYPES = {"book": "M", "journal": "J", "newspaper": "N", "conference": "C", "thesis": "D", "report": "R", "standard": "S", "patent": "P", "database": "DB", "webpage": "EB"}

    def format_reference(self, ref_data: Dict) -> str:
        doc_type = ref_data.get("type", "book")
        type_code = self.DOC_TYPES.get(doc_type, "M")
        authors = self._format_authors(ref_data.get("authors", []))
        title = ref_data.get("title", "")
        source = ref_data.get("source", "")
        year = ref_data.get("year", "")
        pages = ref_data.get("pages", "")
        volume = ref_data.get("volume", "")
        issue = ref_data.get("issue", "")
        url = ref_data.get("url", "")

        ref = f"{authors}. {title}[{type_code}]."
        if source:
            ref += f" {source},"
        if year:
            ref += f" {year}"
        if volume:
            ref += f", {volume}"
        if issue:
            ref += f"({issue})"
        if pages:
            ref += f": {pages}"
        if url and doc_type == "webpage":
            ref += f" {url}"
        ref += "."
        return ref

    def _format_authors(self, authors: List[str]) -> str:
        if not authors:
            return ""
        formatted = []
        for a in authors[:3]:
            if any('\u4e00' <= c <= '\u9fff' for c in a):
                formatted.append(a)
            else:
                parts = a.strip().split()
                if len(parts) >= 2:
                    formatted.append(f"{parts[-1]} {''.join(p[0].upper()+'.' for p in parts[:-1])}")
                else:
                    formatted.append(a)
        result = ', '.join(formatted)
        if len(authors) > 3:
            result += ', et al'
        return result

    def format_references_list(self, references: List[Dict]) -> str:
        if not references:
            return ""
        lines = ["## 参考文献\n"]
        for i, ref in enumerate(references, 1):
            lines.append(f"[{i}] {self.format_reference(ref)}")
        return "\n".join(lines)

    def extract_citations_from_text(self, text: str) -> List[str]:
        citations = []
        for ref in re.findall(r'\[(\d+(?:[,\-\s]\d+)*)\]', text):
            for part in re.split(r'[,\s]', ref):
                if '-' in part:
                    s, e = part.split('-')
                    citations.extend(str(i) for i in range(int(s), int(e)+1))
                else:
                    citations.append(part.strip())
        return list(set(citations))

    def generate_bibtex(self, ref_data: Dict, key: str = "") -> str:
        doc_type = ref_data.get("type", "book")
        bt = {"book": "book", "journal": "article", "conference": "inproceedings", "thesis": "phdthesis", "report": "techreport", "webpage": "misc"}.get(doc_type, "misc")
        if not key:
            authors = ref_data.get("authors", ["unknown"])
            key = f"{authors[0].split()[-1].lower()}{ref_data.get('year', '0000')}"
        fields = []
        if ref_data.get("authors"):
            fields.append(f"  author = {{{' and '.join(ref_data['authors'])}}}")
        if ref_data.get("title"):
            fields.append(f"  title = {{{ref_data['title']}}}")
        if ref_data.get("source"):
            fields.append(f"  journal = {{{ref_data['source']}}}")
        if ref_data.get("year"):
            fields.append(f"  year = {{{ref_data['year']}}}")
        if ref_data.get("volume"):
            fields.append(f"  volume = {{{ref_data['volume']}}}")
        if ref_data.get("pages"):
            fields.append(f"  pages = {{{ref_data['pages']}}}")
        return f"@{bt}{{{key},\n{','.join(fields)}\n}}"
