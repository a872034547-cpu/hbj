"""项目审计服务。

第一轮商业化升级先提供轻量审计事件结构与内存记录能力；后续可替换为
JSONL、SQLite 或服务端审计日志。该模块不依赖 Streamlit。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4


@dataclass
class AuditEvent:
    """单条项目审计事件。"""

    event_id: str
    action: str
    actor: str = "system"
    project_name: str = ""
    target: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        """转换为 JSON 友好的字典。"""
        return {
            "event_id": self.event_id,
            "action": self.action,
            "actor": self.actor,
            "project_name": self.project_name,
            "target": self.target,
            "details": self.details,
            "created_at": self.created_at.isoformat(),
        }


class AuditService:
    """轻量审计事件记录器。"""

    def __init__(self) -> None:
        self._events: List[AuditEvent] = []

    def record(
        self,
        action: str,
        *,
        actor: str = "system",
        project_name: str = "",
        target: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> AuditEvent:
        """记录一条审计事件并返回事件对象。"""
        event = AuditEvent(
            event_id=str(uuid4()),
            action=action,
            actor=actor,
            project_name=project_name,
            target=target,
            details=dict(details or {}),
        )
        self._events.append(event)
        return event

    def list_events(self, *, project_name: str = "", limit: int = 100) -> List[AuditEvent]:
        """按项目过滤并返回最近审计事件。"""
        events = self._events
        if project_name:
            events = [event for event in events if event.project_name == project_name]
        return list(reversed(events))[: max(1, int(limit))]

    def clear(self) -> int:
        """清空审计事件，返回清理数量。"""
        count = len(self._events)
        self._events.clear()
        return count
