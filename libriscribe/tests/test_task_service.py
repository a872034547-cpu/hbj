from __future__ import annotations

from libriscribe.services.task_service import TaskService


def test_task_service_create_update_and_clear_completed() -> None:
    service = TaskService()
    task = service.create("生成章节", status="running", progress=0.2)

    updated = service.update(task.task_id, status="completed", progress=1.2, message="完成")

    assert updated.status == "completed"
    assert updated.progress == 1.0
    assert service.get(task.task_id) is updated
    assert service.clear_completed() == 1
    assert service.get(task.task_id) is None


def test_task_service_persists_to_json(tmp_path) -> None:
    task_file = tmp_path / "tasks.json"
    service = TaskService(task_file)
    task = service.create("索引资料", status="running", progress=0.4, metadata={"project": "demo"})
    service.update(task.task_id, status="failed", error="network")

    restored = TaskService(task_file)
    loaded = restored.get(task.task_id)

    assert loaded is not None
    assert loaded.status == "failed"
    assert loaded.error == "network"
    assert loaded.metadata["project"] == "demo"
