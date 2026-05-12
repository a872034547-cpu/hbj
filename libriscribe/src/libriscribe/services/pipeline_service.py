"""商业化专著生产流水线服务。

该模块只负责根据项目当前数据生成阶段化进度视图，不触发任何写作、
检索、审校或导出副作用，便于 Web 层、任务中心和后续 API 复用。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional


PipelineStatus = str


@dataclass(frozen=True)
class PipelineStage:
    """写作工作流阶段定义。"""

    key: str
    title: str
    description: str
    checker: Callable[[Any], PipelineStatus]
    user_action: str
    agent_action: str
    output: str
    primary_route: str
    primary_action: str
    optional: bool = False


class PipelineService:
    """生成写作工作流状态。

    阶段固定为：
    briefing -> knowledge_injection -> outline_planning -> draft_writing -> visual_polish -> delivery。

    返回状态约定：
    - ``completed``：阶段已达到可交付标准
    - ``in_progress``：阶段已有数据或任务正在推进，但尚未完成
    - ``pending``：阶段尚未开始或缺少前置产物
    - ``blocked``：阶段存在失败/风险状态，需要处理后继续
    - ``optional``：可选优化阶段，尚未启用或无需强制执行
    """

    STATUS_COMPLETED = "completed"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_PENDING = "pending"
    STATUS_BLOCKED = "blocked"
    STATUS_OPTIONAL = "optional"

    def __init__(self) -> None:
        self.stages: List[PipelineStage] = [
            PipelineStage(
                key="briefing",
                title="需求理解与选题策展",
                description="把书名、方向、目标读者、用途和篇幅约束整理为项目定位卡。",
                checker=self._project_status,
                user_action="填写书名、方向、目标读者、书型、用途、目标字数和风格要求。",
                agent_action="抽取价值主张、读者画像、写作边界和全书表达风格。",
                output="项目定位卡、写作目标、风格约束、成功标准。",
                primary_route="workspace",
                primary_action="完善项目定位",
            ),
            PipelineStage(
                key="knowledge_injection",
                title="文献 / 知识库注入",
                description="上传真实资料、粘贴参考文献并预留 OpenAlex 等外部文献检索入口。",
                checker=self._sources_status,
                user_action="上传 PDF/DOCX/TXT/Markdown，粘贴参考文献，输入检索关键词或 DOI。",
                agent_action="索引资料、生成证据片段、识别引用风险并形成可检索知识库。",
                output="资料库、证据片段、参考文献候选、未核验风险清单。",
                primary_route="sources",
                primary_action="导入资料 / 检索文献",
            ),
            PipelineStage(
                key="outline_planning",
                title="结构化大纲生成",
                description="基于需求和资料生成章—节—一、—（一）—写作思路的可解析目录。",
                checker=self._outline_status,
                user_action="确认章数、总字数、是否含前言，并选择全书生成或分章生成。",
                agent_action="规划章节逻辑、四级写作单元、字数分配和资料检索边界。",
                output="四级目录、每节写作目标、字数规划、RAG 查询词。",
                primary_route="outline",
                primary_action="生成全书大纲",
            ),
            PipelineStage(
                key="draft_writing",
                title="AI 正文逐章撰写",
                description="按四级写作单元逐节生成正文，结合资料库进行引用锚定与一致性控制。",
                checker=self._draft_status,
                user_action="选择章节或小节，确认模型配置，并监控生成进度。",
                agent_action="检索资料、撰写正文、补足字数、保持术语和上下文一致。",
                output="章节 Markdown 正文、小节生成状态、章节衔接与参考文献草案。",
                primary_route="editor",
                primary_action="开始逐章写作",
            ),
            PipelineStage(
                key="visual_polish",
                title="图文同步生成（可选）",
                description="基于已生成正文进行二次润色，按需生成表格、Mermaid 图和路线图。",
                checker=self._visual_polish_status,
                user_action="选择需要图表优化的章节，指定表格、流程图、路线图或对比矩阵类型。",
                agent_action="从正文提炼结构化信息，生成 Markdown 表格、Mermaid 图和图文优化建议。",
                output="章节图表、路线图、对比矩阵、可视化资产清单。",
                primary_route="editor",
                primary_action="图文优化（可选）",
                optional=True,
            ),
            PipelineStage(
                key="delivery",
                title="全书交付与版本管理",
                description="汇总引用核验、质量审校、导出文件和最终交付包状态。",
                checker=self._delivery_status,
                user_action="确认引用风险、质量报告、导出格式和交付版本。",
                agent_action="检查引用闭环、质量评分、字数偏差并生成出版级导出物。",
                output="DOCX/PDF/LaTeX/PPTX、质量报告、引用清单、交付包记录。",
                primary_route="exports",
                primary_action="导出交付包",
            ),
        ]

    def get_pipeline(self, project: Any) -> List[Dict[str, Any]]:
        """基于项目数据返回一小时写书阶段状态列表。

        Args:
            project: ``ProjectKnowledgeBase``、字典或兼容对象。

        Returns:
            每个阶段包含 ``key``、``title``、``description``、``status``、
            ``order``、``user_action``、``agent_action``、``output``、
            ``primary_route``、``primary_action`` 和 ``optional`` 字段。
        """
        return [
            {
                "key": stage.key,
                "title": stage.title,
                "description": stage.description,
                "status": stage.checker(project),
                "order": index + 1,
                "user_action": stage.user_action,
                "agent_action": stage.agent_action,
                "output": stage.output,
                "primary_route": stage.primary_route,
                "primary_action": stage.primary_action,
                "optional": stage.optional,
            }
            for index, stage in enumerate(self.stages)
        ]

    def _project_status(self, project: Any) -> PipelineStatus:
        if not project:
            return self.STATUS_PENDING

        required_fields = ["project_name", "title", "description"]
        present_count = sum(1 for field in required_fields if self._has_text(self._get(project, field)))
        optional_present = any(
            self._has_text(self._get(project, field))
            for field in ("genre", "category", "target_audience", "book_length", "tone")
        )

        if present_count == len(required_fields) and optional_present:
            return self.STATUS_COMPLETED
        if present_count > 0 or optional_present:
            return self.STATUS_IN_PROGRESS
        return self.STATUS_PENDING

    def _sources_status(self, project: Any) -> PipelineStatus:
        failed_tasks = self._task_logs(project, task_types={"sources", "source_index", "rag_index", "index_sources"}, statuses={"failed"})
        if failed_tasks:
            return self.STATUS_BLOCKED

        source_documents = self._as_list(self._get(project, "source_documents", []))
        rag_documents = self._as_list(self._get(project, "rag_documents", []))
        evidence_chunks = self._as_list(self._get(project, "evidence_chunks", []))

        failed_sources = [doc for doc in source_documents if self._get(doc, "status") == "failed"]
        if failed_sources:
            return self.STATUS_BLOCKED

        indexed_sources = [doc for doc in source_documents if self._get(doc, "status", "indexed") == "indexed"]
        pending_sources = [doc for doc in source_documents if self._get(doc, "status") in {"pending", "processing"}]

        if (indexed_sources or rag_documents) and evidence_chunks:
            return self.STATUS_COMPLETED
        if source_documents or rag_documents or pending_sources:
            return self.STATUS_IN_PROGRESS
        return self.STATUS_PENDING

    def _outline_status(self, project: Any) -> PipelineStatus:
        failed_tasks = self._task_logs(project, task_types={"outline", "outliner", "generate_outline"}, statuses={"failed"})
        if failed_tasks:
            return self.STATUS_BLOCKED

        outline = self._get(project, "outline", "")
        chapters = self._chapters(project)
        chapters_with_titles = [chapter for chapter in chapters if self._has_text(self._get(chapter, "title"))]

        if self._has_text(outline) and chapters_with_titles:
            return self.STATUS_COMPLETED
        if self._has_text(outline) or chapters_with_titles:
            return self.STATUS_IN_PROGRESS
        return self.STATUS_PENDING

    def _draft_status(self, project: Any) -> PipelineStatus:
        failed_tasks = self._task_logs(project, task_types={"draft", "chapter", "chapter_writer", "write_chapter"}, statuses={"failed"})
        if failed_tasks:
            return self.STATUS_BLOCKED

        chapters = self._chapters(project)
        if not chapters:
            return self.STATUS_PENDING

        completed = 0
        started = 0
        for chapter in chapters:
            status = self._get(chapter, "status", "pending")
            actual_word_count = self._to_int(self._get(chapter, "actual_word_count", 0))
            sections = self._as_list(self._get(chapter, "sections", []))
            section_started = any(
                self._get(section, "status", "pending") in {"writing", "completed", "reviewed"}
                or self._to_int(self._get(section, "actual_word_count", 0)) > 0
                for section in sections
            )

            if status in {"completed", "reviewed"} or actual_word_count > 0 and status == "completed":
                completed += 1
                started += 1
            elif status in {"writing", "completed", "reviewed"} or actual_word_count > 0 or section_started:
                started += 1

        if completed == len(chapters):
            return self.STATUS_COMPLETED
        if started > 0:
            return self.STATUS_IN_PROGRESS
        return self.STATUS_PENDING

    def _citation_check_status(self, project: Any) -> PipelineStatus:
        citations = self._as_list(self._get(project, "citations", []))
        if not citations:
            return self.STATUS_PENDING

        risky_statuses = {"missing_source", "risky", "failed"}
        risky_citations = [citation for citation in citations if self._get(citation, "status") in risky_statuses]
        if risky_citations:
            return self.STATUS_BLOCKED

        verified_citations = [citation for citation in citations if self._get(citation, "status") == "verified"]
        unverified_citations = [citation for citation in citations if self._get(citation, "status", "unverified") == "unverified"]

        if verified_citations and not unverified_citations and len(verified_citations) == len(citations):
            return self.STATUS_COMPLETED
        return self.STATUS_IN_PROGRESS

    def _quality_review_status(self, project: Any) -> PipelineStatus:
        reports = self._as_list(self._get(project, "book_review_reports", []))
        chapter_reviews = self._get(project, "chapter_reviews", {})

        latest_report = reports[-1] if reports else None
        if latest_report:
            issue_fields = (
                "structure_issues",
                "citation_issues",
                "terminology_issues",
                "evidence_gaps",
                "word_count_issues",
            )
            has_blocking_issues = any(self._as_list(self._get(latest_report, field, [])) for field in issue_fields)
            score = self._to_float(self._get(latest_report, "overall_score", 0.0))

            if score >= 0.8 and not has_blocking_issues:
                return self.STATUS_COMPLETED
            if score > 0 or has_blocking_issues:
                return self.STATUS_IN_PROGRESS

        if isinstance(chapter_reviews, Mapping) and any(chapter_reviews.values()):
            return self.STATUS_IN_PROGRESS
        return self.STATUS_PENDING

    def _export_status(self, project: Any) -> PipelineStatus:
        failed_exports = self._task_logs(project, task_types={"export", "docx_export", "pdf_export", "latex_export"}, statuses={"failed"})
        if failed_exports:
            return self.STATUS_BLOCKED

        completed_exports = self._task_logs(project, task_types={"export", "docx_export", "pdf_export", "latex_export"}, statuses={"completed"})
        running_exports = self._task_logs(project, task_types={"export", "docx_export", "pdf_export", "latex_export"}, statuses={"pending", "running"})
        metadata_exports = self._metadata_list(project, "exports") or self._metadata_list(project, "export_files")

        if completed_exports or metadata_exports:
            return self.STATUS_COMPLETED
        if running_exports:
            return self.STATUS_IN_PROGRESS
        return self.STATUS_PENDING

    def _publish_status(self, project: Any) -> PipelineStatus:
        failed_publish = self._task_logs(project, task_types={"publish", "delivery", "release"}, statuses={"failed"})
        if failed_publish:
            return self.STATUS_BLOCKED

        metadata = self._get(project, "metadata", {})
        publish_status = self._get(project, "publish_status") or self._get(metadata, "publish_status")
        published_at = self._get(project, "published_at") or self._get(metadata, "published_at")
        delivery_package = self._get(project, "delivery_package") or self._get(metadata, "delivery_package")
        completed_publish = self._task_logs(project, task_types={"publish", "delivery", "release"}, statuses={"completed"})
        running_publish = self._task_logs(project, task_types={"publish", "delivery", "release"}, statuses={"pending", "running"})

        if publish_status in {"published", "delivered", "released"} or published_at or delivery_package or completed_publish:
            return self.STATUS_COMPLETED
        if publish_status in {"pending", "preparing", "reviewing"} or running_publish:
            return self.STATUS_IN_PROGRESS
        return self.STATUS_PENDING

    def _visual_polish_status(self, project: Any) -> PipelineStatus:
        metadata = self._get(project, "metadata", {})
        enabled = bool(
            self._get(project, "visual_generation_enabled")
            or self._get(metadata, "visual_generation_enabled")
        )
        assets = self._as_list(self._get(project, "visual_assets", [])) or self._metadata_list(project, "visual_assets")
        visual_tasks = self._task_logs(project, task_types={"visual", "visual_polish", "diagram", "multimodal"})
        failed_visual = [task for task in visual_tasks if self._get(task, "status") == "failed"]
        running_visual = [task for task in visual_tasks if self._get(task, "status") in {"pending", "running"}]
        completed_visual = [task for task in visual_tasks if self._get(task, "status") == "completed"]

        if failed_visual:
            return self.STATUS_BLOCKED
        if assets or completed_visual:
            return self.STATUS_COMPLETED
        if enabled or running_visual:
            return self.STATUS_IN_PROGRESS
        return self.STATUS_OPTIONAL

    def _delivery_status(self, project: Any) -> PipelineStatus:
        citation_status = self._citation_check_status(project)
        quality_status = self._quality_review_status(project)
        export_status = self._export_status(project)
        publish_status = self._publish_status(project)

        if self.STATUS_BLOCKED in {citation_status, quality_status, export_status, publish_status}:
            return self.STATUS_BLOCKED
        if export_status == self.STATUS_COMPLETED and publish_status == self.STATUS_COMPLETED:
            return self.STATUS_COMPLETED
        if any(
            status in {self.STATUS_COMPLETED, self.STATUS_IN_PROGRESS}
            for status in (citation_status, quality_status, export_status, publish_status)
        ):
            return self.STATUS_IN_PROGRESS
        return self.STATUS_PENDING

    def _chapters(self, project: Any) -> List[Any]:
        chapters = self._get(project, "chapters", {})
        if isinstance(chapters, Mapping):
            return list(chapters.values())
        return self._as_list(chapters)

    def _task_logs(
        self,
        project: Any,
        task_types: Optional[set[str]] = None,
        statuses: Optional[set[str]] = None,
    ) -> List[Any]:
        task_logs = self._as_list(self._get(project, "task_logs", []))
        result = []
        for task in task_logs:
            task_type = str(self._get(task, "task_type", "")).lower()
            status = str(self._get(task, "status", "")).lower()
            if task_types and task_type not in task_types:
                continue
            if statuses and status not in statuses:
                continue
            result.append(task)
        return result

    def _metadata_list(self, project: Any, key: str) -> List[Any]:
        metadata = self._get(project, "metadata", {})
        value = self._get(metadata, key, [])
        return self._as_list(value)

    @staticmethod
    def _get(source: Any, key: str, default: Any = None) -> Any:
        if source is None:
            return default
        if isinstance(source, Mapping):
            return source.get(key, default)
        return getattr(source, key, default)

    @staticmethod
    def _as_list(value: Any) -> List[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, tuple):
            return list(value)
        if isinstance(value, set):
            return list(value)
        return [value]

    @staticmethod
    def _has_text(value: Any) -> bool:
        if value is None:
            return False
        text = str(value).strip()
        return bool(text) and text.lower() not in {"untitled", "unknown genre", "unknown category", "no description provided."}

    @staticmethod
    def _to_int(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _to_float(value: Any) -> float:
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0
