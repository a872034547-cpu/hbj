"""持久化任务服务。

该模块不依赖 Streamlit 或线程运行器，提供可被 Web UI、后台任务、未来 API 和
上线门禁复用的任务状态注册表。配置 ``persistence_path`` 后会自动从 JSON 文件
加载任务，并在创建、更新、清理时写回磁盘。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4


@dataclass
class TaskRecord:
    """任务状态记录。"""

    task_id: str
    name: str
    status: str = "pending"
    progress: float = 0.0
    message: str = ""
    result: Optional[Any] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        """转换为 JSON 友好的字典。"""
        return {
            "task_id": self.task_id,
            "name": self.name,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "result": self.result,
            "error": self.error,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskRecord":
        """从 JSON 字典恢复任务记录。"""
        return cls(
            task_id=str(data.get("task_id") or data.get("id") or uuid4()),
            name=str(data.get("name") or data.get("description") or data.get("type") or "未命名任务"),
            status=str(data.get("status") or "pending"),
            progress=TaskService._normalize_progress(data.get("progress", 0.0)),
            message=str(data.get("message") or ""),
            result=data.get("result"),
            error=data.get("error"),
            metadata=dict(data.get("metadata") or {}),
            created_at=TaskService._parse_datetime(data.get("created_at") or data.get("started_at")),
            updated_at=TaskService._parse_datetime(data.get("updated_at") or data.get("completed_at")),
        )


class TaskService:
    """同步任务注册表，支持可选 JSON 持久化。"""

    TERMINAL_STATUSES = {"completed", "success", "done", "failed", "cancelled"}

    def __init__(self, persistence_path: Optional[str | Path] = None) -> None:
        self.persistence_path = Path(persistence_path) if persistence_path else None
        self._tasks: Dict[str, TaskRecord] = {}
        self._load_if_configured()

    def create(
        self,
        name: str,
        *,
        task_id: Optional[str] = None,
        status: str = "pending",
        progress: float = 0.0,
        message: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TaskRecord:
        """创建并注册任务。"""
        resolved_task_id = task_id or str(uuid4())
        if resolved_task_id in self._tasks:
            raise ValueError(f"Task already exists: {resolved_task_id}")

        now = datetime.now(timezone.utc)
        record = TaskRecord(
            task_id=resolved_task_id,
            name=name,
            status=status,
            progress=self._normalize_progress(progress),
            message=message,
            metadata=dict(metadata or {}),
            created_at=now,
            updated_at=now,
        )
        self._tasks[resolved_task_id] = record
        self._persist_if_configured()
        return record

    def update(
        self,
        task_id: str,
        *,
        name: Optional[str] = None,
        status: Optional[str] = None,
        progress: Optional[float] = None,
        message: Optional[str] = None,
        result: Any = None,
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TaskRecord:
        """更新任务并返回更新后的记录。"""
        record = self.get(task_id)
        if record is None:
            raise KeyError(f"Task not found: {task_id}")

        if name is not None:
            record.name = name
        if status is not None:
            record.status = status
        if progress is not None:
            record.progress = self._normalize_progress(progress)
        if message is not None:
            record.message = message
        if result is not None:
            record.result = result
        if error is not None:
            record.error = error
        if metadata is not None:
            record.metadata.update(metadata)

        record.updated_at = datetime.now(timezone.utc)
        self._persist_if_configured()
        return record

    def list(self, *, status: Optional[str] = None) -> List[TaskRecord]:
        """列出任务，可按状态过滤。"""
        records = list(self._tasks.values())
        if status is not None:
            records = [record for record in records if record.status == status]
        return sorted(records, key=lambda record: record.created_at, reverse=True)

    def get(self, task_id: str) -> Optional[TaskRecord]:
        """按 ID 返回任务；不存在时返回 ``None``。"""
        return self._tasks.get(task_id)

    def clear_completed(self) -> int:
        """清理已完成/失败/取消任务并返回清理数量。"""
        completed_ids = [
            task_id
            for task_id, record in self._tasks.items()
            if record.status in self.TERMINAL_STATUSES
        ]
        for task_id in completed_ids:
            del self._tasks[task_id]

        if completed_ids:
            self._persist_if_configured()
        return len(completed_ids)

    def to_jsonable(self) -> List[Dict[str, Any]]:
        """返回可 JSON 序列化的任务列表。"""
        return [record.to_dict() for record in self.list()]

    def _load_if_configured(self) -> None:
        if self.persistence_path is None or not self.persistence_path.exists():
            return
        try:
            data = json.loads(self.persistence_path.read_text(encoding="utf-8"))
            rows = data.get("tasks", data) if isinstance(data, dict) else data
            for row in rows or []:
                if not isinstance(row, dict):
                    continue
                record = TaskRecord.from_dict(row)
                self._tasks[record.task_id] = record
        except Exception:
            # 持久化文件损坏不能阻断应用启动；后续写入会覆盖为健康结构。
            self._tasks = {}

    def _persist_if_configured(self) -> None:
        if self.persistence_path is None:
            return
        self.persistence_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "tasks": [record.to_dict() for record in self.list()],
        }
        self.persistence_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _normalize_progress(progress: Any) -> float:
        """将进度限制在 0.0 到 1.0。"""
        try:
            value = float(progress)
        except (TypeError, ValueError):
            value = 0.0
        return max(0.0, min(1.0, value))

    @staticmethod
    def _parse_datetime(value: Any) -> datetime:
        """解析 ISO datetime，失败则返回当前 UTC 时间。"""
        if isinstance(value, datetime):
            return value
        if isinstance(value, str) and value.strip():
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        return datetime.now(timezone.utc)
