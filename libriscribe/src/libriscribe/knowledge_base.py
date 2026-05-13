# src/libriscribe/knowledge_base.py

from typing import Any, Dict, Optional, List, Union, Tuple
import hashlib
from pydantic import BaseModel, Field, field_validator, model_validator
import json
from pathlib import Path
from datetime import datetime


class Character(BaseModel):
    name: str
    age: str = ""
    physical_description: str = ""
    personality_traits: str = ""
    background: str = ""
    motivations: str = ""
    relationships: Dict[str, str] = {}  # Character name -> Relationship description
    role: str = ""
    internal_conflicts: str = ""
    external_conflicts: str = ""
    character_arc: str = ""


class Scene(BaseModel):
    scene_number: int
    summary: str = ""
    characters: List[str] = []  # List of character names
    setting: str = ""
    goal: str = ""  # What's the purpose of this scene?
    emotional_beat: str = ""  # What's the primary emotion conveyed?


class ChapterSection(BaseModel):
    """学术专著写作单元。

    用于承载四级目录中的“节/三级标题/四级标题”及其写作状态。
    旧版 `Scene` 仍保留用于兼容历史项目，但专著写作流程以本模型为核心。
    """
    section_number: str = ""  # e.g., "1.1", "1.1.1", "1.1.1.1"
    parent_number: str = ""  # e.g., "1.1" 的上级为 "1"
    title: str = ""
    summary: str = ""  # 小节写作目标/要点
    word_count: int = 0  # 目标字数
    actual_word_count: int = 0  # 已生成/已写入字数
    level: int = 1  # 1=节, 2=三级标题, 3=四级标题
    status: str = "pending"  # pending | writing | completed | reviewed | word_count_soft_fail
    content_path: str = ""  # 小节独立内容路径（可选）
    rag_query: str = ""  # 小节资料检索查询词（可选）
    word_count_status: str = ""  # ok | word_count_soft_fail
    word_count_target: int = 0  # 字数控制目标，供软失败提示使用
    word_count_actual: int = 0  # 字数控制实际值，供软失败提示使用
    word_count_note: str = ""  # 字数软失败说明


class Chapter(BaseModel):
    chapter_number: int
    title: str = ""
    summary: str = ""
    word_count: int = 0  # 目标字数
    actual_word_count: int = 0  # 实际已生成/已写入字数
    status: str = "pending"  # pending | writing | completed | reviewed
    sections: List["ChapterSection"] = []  # 学术目录写作单元
    scenes: List[Scene] = []  # 旧版小说场景，仅作兼容保留
    # We don't store the full chapter text *here*, just metadata and sections/scenes.


class Worldbuilding(BaseModel):
    # Keep this empty for now, and we will use it on the agents
    geography: str = ""
    culture_and_society: str = ""
    history: str = ""
    rules_and_laws: str = ""
    technology_level: str = ""
    magic_system: str = ""
    key_locations: str = ""
    important_organizations: str = ""
    flora_and_fauna: str = ""
    languages: str = ""
    religions_and_beliefs: str = ""
    economy: str = ""
    conflicts: str = ""
    # Non fiction
    setting_context: str = ""
    key_figures: str = ""
    major_events: str = ""
    underlying_causes: str = ""
    consequences: str = ""
    relevant_data: str = ""
    different_perspectives: str = ""
    key_concepts: str = ""
    # business
    industry_overview: str = ""
    target_audience: str = ""
    market_analysis: str = ""
    business_model: str = ""
    marketing_and_sales_strategy: str = ""
    operations: str = ""
    financial_projections: str = ""
    management_team: str = ""
    legal_and_regulatory_environment: str = ""
    risks_and_challenges: str = ""
    opportunities_for_growth: str = ""
    # research
    introduction: str = ""
    literature_review: str = ""
    methodology: str = ""
    results: str = ""
    discussion: str = ""
    conclusion: str = ""
    references: str = ""
    appendices: str = ""


# === 新增：引用溯源模型 ===
class SourceDocument(BaseModel):
    """资料库中的原始来源文档。"""
    id: str = ""
    title: str = ""
    authors: List[str] = []
    year: str = ""
    source_type: str = ""
    file_path: str = ""
    file_name: str = ""
    file_hash: str = ""
    doi: str = ""
    isbn: str = ""
    url: str = ""
    chunk_count: int = 0
    indexed_at: str = ""
    status: str = "indexed"  # indexed | failed | pending
    summary: str = ""
    metadata: Dict[str, Any] = {}


class EvidenceChunk(BaseModel):
    """可追溯证据片段，用于连接资料、RAG 与正文引用。"""
    id: str = ""
    document_id: str = ""
    source: str = ""
    text: str = ""
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    paragraph_index: Optional[int] = None
    chunk_index: int = 0
    chunk_hash: str = ""
    score: float = 0.0
    metadata: Dict[str, Any] = {}


class Citation(BaseModel):
    """单条引用记录。2.0 起支持证据片段绑定，旧字段继续兼容。"""
    id: str = ""
    evidence_chunk_id: str = ""
    sentence: str = ""  # 被引用的句子
    source: str = ""  # 来源文档名
    page: Optional[int] = None  # 页码
    quote_original: str = ""  # 原文引用
    formatted_ref: str = ""  # GB/T 7714 格式化引用
    style: str = "GB/T 7714"
    source_type: str = ""
    doi: str = ""
    isbn: str = ""
    url: str = ""
    confidence: float = 0.0  # 置信度 0-1
    status: str = "unverified"  # verified | unverified | missing_source | risky
    metadata: Dict[str, Any] = {}  # 原始参考文献、检索词、核验备注等扩展信息


class TaskLog(BaseModel):
    """持久化任务日志，用于长任务断点恢复和故障诊断。"""
    id: str = ""
    task_type: str = ""
    target: str = ""
    status: str = "pending"  # pending | running | completed | failed
    progress: float = 0.0
    message: str = ""
    error: str = ""
    started_at: str = ""
    completed_at: str = ""
    model_profile_id: str = ""
    prompt_version: str = ""
    retry_count: int = 0
    metadata: Dict[str, Any] = {}


class BookReviewReport(BaseModel):
    """全书级质量报告。"""
    id: str = ""
    created_at: str = ""
    overall_score: float = 0.0
    structure_issues: List[str] = []
    citation_issues: List[str] = []
    terminology_issues: List[str] = []
    evidence_gaps: List[str] = []
    word_count_issues: List[str] = []
    export_warnings: List[str] = []
    suggestions: List[str] = []


class ChapterReview(BaseModel):
    """章节评审记录"""
    iteration: int = 0
    score: float = 0.0  # 0-1
    consistency_issues: List[str] = []
    terminology_issues: List[str] = []
    suggestions: List[str] = []
    reviewed_at: str = ""


class ProjectKnowledgeBase(BaseModel):
    project_name: str
    title: str = ""
    genre: str = "学术专著"
    description: str = ""
    category: str = "专著"
    language: str = "简体中文"
    num_characters: Union[int, Tuple[int, int]] = 0
    num_characters_str: str = ""
    worldbuilding_needed: bool = False
    review_preference: str = "AI"
    book_length: str = ""
    logline: str = ""
    tone: str = "严谨、清晰、证据导向"
    target_audience: str = "专著读者"
    num_chapters: Union[int, Tuple[int, int]] = 1
    num_chapters_str: str = ""
    llm_provider: str = "openai"
    model_profile_id: str = ""  # 统一模型配置页中的模型档案 ID
    dynamic_questions: Dict[str, str] = {}

    characters: Dict[str, Character] = {}  # Character name -> Character object
    worldbuilding: Optional[Worldbuilding] = None
    chapters: Dict[int, Chapter] = {}  # Chapter number -> Chapter object
    outline: str = ""  # Store outline as markdown
    outline_brainstorm: str = ""  # 大纲生成前基于资料/检索/引用形成的结构化头脑风暴
    project_dir: Optional[Path] = None

    # === 新增：术语表 ===
    terminology: Dict[str, str] = {}  # 术语 -> 定义/统一写法

    # === 新增：引用映射 ===
    citations: List[Citation] = []
    source_documents: List[SourceDocument] = []  # 2.0 资料来源库
    evidence_chunks: List[EvidenceChunk] = []  # 2.0 可追溯证据片段索引

    # === 新增：章节摘要 ===
    chapter_summaries: Dict[int, str] = {}  # 章节号 -> 摘要

    # === 新增：RAG 文档列表 ===
    rag_documents: List[str] = []  # 已索引的文档路径列表

    # === 新增：章节评审历史 ===
    chapter_reviews: Dict[int, List[ChapterReview]] = {}  # 章节号 -> 评审记录列表

    # === 新增：版本历史元数据 ===
    version_history: List[Dict[str, Any]] = []  # [{timestamp, description, checkpoint_path}]

    # === 新增：全局风格向量 ===
    style_guide: str = ""  # 风格指南文本

    # === 新增：2.0 任务与全书质量报告 ===
    task_logs: List[TaskLog] = []
    book_review_reports: List[BookReviewReport] = []

    # === 新增：自定义 AI 平台配置 ===
    custom_api_base: str = ""  # 自定义 API 基础 URL
    custom_api_key: str = ""   # 自定义 API 密钥
    custom_model: str = ""     # 自定义模型名称

    # === 新增：创建/更新时间 ===
    created_at: str = ""
    updated_at: str = ""

    @field_validator("title", "description", "genre", "category", "logline", "tone", "target_audience", mode="before")
    @classmethod
    def clean_legacy_placeholder_text(cls, value):
        if isinstance(value, str) and value.strip() in {
            "No description provided.",
            "No logline available",
            "Unknown Genre",
            "Unknown Category",
            "Untitled",
            "None",
            "null",
        }:
            return ""
        return value

    @field_validator("num_characters", "num_chapters", mode="before")
    @classmethod
    def parse_range_or_plus(cls, value):
        if isinstance(value, str):
            if "-" in value:
                try:
                    min_val, max_val = map(int, value.split("-"))
                    return (min_val, max_val)
                except ValueError:
                    return 0
            elif "+" in value:
                try:
                    return int(value.replace("+", ""))
                except ValueError:
                    return 0
            else:
                try:
                    return int(value)
                except ValueError:
                    return 0
        return value

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return getattr(self, key)
        except AttributeError:
            return default

    def set(self, key: str, value: Any) -> None:
        if hasattr(self, key):
            setattr(self, key, value)

    def add_character(self, character: Character):
        self.characters[character.name] = character

    def get_character(self, character_name: str) -> Optional[Character]:
        return self.characters.get(character_name)

    def add_chapter(self, chapter: Chapter):
        self.chapters[chapter.chapter_number] = chapter

    def get_chapter(self, chapter_number: int) -> Optional[Chapter]:
        return self.chapters.get(chapter_number)

    def add_scene_to_chapter(self, chapter_number: int, scene: Scene):
        if chapter_number not in self.chapters:
            self.chapters[chapter_number] = Chapter(chapter_number=chapter_number)
        self.chapters[chapter_number].scenes.append(scene)

    # === 新增：术语表操作 ===
    def add_terminology(self, term: str, definition: str):
        """添加术语"""
        self.terminology[term] = definition

    def get_terminology_context(self) -> str:
        """获取术语表上下文（用于注入 prompt）"""
        if not self.terminology:
            return ""
        lines = ["术语表："]
        for term, defn in self.terminology.items():
            lines.append(f"- {term}: {defn}")
        return "\n".join(lines)

    # === 新增：引用/证据操作 ===
    def add_source_document(self, document: SourceDocument):
        """添加或更新资料来源文档。"""
        if not document.id:
            raw = document.file_hash or document.file_path or document.file_name or document.title
            document.id = hashlib.md5(str(raw).encode("utf-8", errors="ignore")).hexdigest()[:16]
        self.source_documents = [d for d in self.source_documents if d.id != document.id]
        self.source_documents.append(document)

    def add_evidence_chunk(self, chunk: EvidenceChunk):
        """添加或更新证据片段。"""
        if not chunk.id:
            raw = chunk.chunk_hash or f"{chunk.document_id}:{chunk.chunk_index}:{chunk.text[:80]}"
            chunk.id = hashlib.md5(str(raw).encode("utf-8", errors="ignore")).hexdigest()[:16]
        self.evidence_chunks = [c for c in self.evidence_chunks if c.id != chunk.id]
        self.evidence_chunks.append(chunk)

    def add_citation(self, citation: Citation):
        """添加引用"""
        if not citation.id:
            raw = citation.evidence_chunk_id or f"{citation.source}:{citation.page}:{citation.sentence[:80]}"
            citation.id = hashlib.md5(str(raw).encode("utf-8", errors="ignore")).hexdigest()[:16]
        self.citations.append(citation)

    def get_citations_for_chapter(self, chapter_number: int) -> List[Citation]:
        """获取某章节的引用（通过句子匹配）"""
        chapter = self.get_chapter(chapter_number)
        if not chapter:
            return []
        # 简单匹配：引用的句子在章节摘要中出现
        return self.citations  # 返回所有引用，后续可优化

    # === 新增：章节摘要操作 ===
    def set_chapter_summary(self, chapter_number: int, summary: str):
        """设置章节摘要"""
        self.chapter_summaries[chapter_number] = summary

    def get_previous_summaries(self, current_chapter: int, max_n: int = 3) -> str:
        """获取前 N 章的摘要（用于注入 prompt）"""
        if not self.chapter_summaries:
            return ""
        lines = []
        for ch_num in sorted(self.chapter_summaries.keys()):
            if ch_num < current_chapter:
                lines.append(f"第{ch_num}章摘要: {self.chapter_summaries[ch_num]}")
        # 只取最后 max_n 章
        if len(lines) > max_n:
            lines = lines[-max_n:]
        return "\n".join(lines)

    # === 新增：评审操作 ===
    def add_review(self, chapter_number: int, review: ChapterReview):
        """添加章节评审记录"""
        if chapter_number not in self.chapter_reviews:
            self.chapter_reviews[chapter_number] = []
        self.chapter_reviews[chapter_number].append(review)

    def get_latest_review(self, chapter_number: int) -> Optional[ChapterReview]:
        """获取最新评审记录"""
        reviews = self.chapter_reviews.get(chapter_number, [])
        return reviews[-1] if reviews else None

    def to_json(self) -> str:
        """Serializes the knowledge base to a JSON string."""
        return self.model_dump_json(indent=4)

    @classmethod
    def from_json(cls, json_str: str) -> "ProjectKnowledgeBase":
        """Deserializes the knowledge base from a JSON string."""
        return cls.model_validate_json(json_str)

    def save_to_file(self, file_path: str):
        """Saves the knowledge base to a JSON file."""
        self.updated_at = datetime.now().isoformat()
        if not self.created_at:
            self.created_at = self.updated_at
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(self.to_json())

    @classmethod
    def load_from_file(cls, file_path: str) -> Optional["ProjectKnowledgeBase"]:
        """Loads the knowledge base from a JSON file."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                # 迁移：确保旧数据包含新字段
                if "model_profile_id" not in data:
                    data["model_profile_id"] = ""
                if "custom_api_base" not in data:
                    data["custom_api_base"] = ""
                if "custom_api_key" not in data:
                    data["custom_api_key"] = ""
                if "custom_model" not in data:
                    data["custom_model"] = ""
                # 迁移：确保 2.0 资料库/证据链/任务日志字段存在
                data.setdefault("source_documents", [])
                data.setdefault("evidence_chunks", [])
                data.setdefault("task_logs", [])
                data.setdefault("book_review_reports", [])
                for citation in data.get("citations", []):
                    citation.setdefault("id", "")
                    citation.setdefault("evidence_chunk_id", "")
                    citation.setdefault("style", "GB/T 7714")
                    citation.setdefault("source_type", "")
                    citation.setdefault("doi", "")
                    citation.setdefault("isbn", "")
                    citation.setdefault("url", "")
                    citation.setdefault("status", "unverified")
                # 迁移：确保章节和学术写作单元包含新字段
                for ch_num, ch_data in data.get("chapters", {}).items():
                    if "word_count" not in ch_data:
                        ch_data["word_count"] = 0
                    if "actual_word_count" not in ch_data:
                        ch_data["actual_word_count"] = 0
                    if "status" not in ch_data:
                        ch_data["status"] = "pending"
                    if "sections" not in ch_data:
                        ch_data["sections"] = []
                    for sec_data in ch_data.get("sections", []):
                        sec_number = str(sec_data.get("section_number", ""))
                        if "parent_number" not in sec_data:
                            sec_data["parent_number"] = sec_number.rsplit(".", 1)[0] if "." in sec_number else str(ch_num)
                        if "summary" not in sec_data:
                            sec_data["summary"] = ""
                        if "actual_word_count" not in sec_data:
                            sec_data["actual_word_count"] = 0
                        if "status" not in sec_data:
                            sec_data["status"] = "pending"
                        sec_data.setdefault("word_count_status", "")
                        sec_data.setdefault("word_count_target", int(sec_data.get("word_count", 0) or 0))
                        sec_data.setdefault("word_count_actual", int(sec_data.get("actual_word_count", 0) or 0))
                        sec_data.setdefault("word_count_note", "")
                        if "content_path" not in sec_data:
                            sec_data["content_path"] = ""
                        if "rag_query" not in sec_data:
                            sec_data["rag_query"] = ""
                # 确保 project_dir 正确设置（从文件路径推导）
                project_dir = str(Path(file_path).parent)
                data["project_dir"] = project_dir
                return cls.model_validate(data)
        except FileNotFoundError:
            return None
        except json.JSONDecodeError:
            print(f"ERROR: Invalid JSON in {file_path}")
            return None
        except Exception as e:
            print(f"ERROR loading knowledge base from {file_path}: {e}")
            return None

    @model_validator(mode="after")
    def set_worldbuilding(self) -> "ProjectKnowledgeBase":
        if not self.worldbuilding_needed:
            self.worldbuilding = None
        elif self.worldbuilding is None:
            self.worldbuilding = Worldbuilding()
        return self
