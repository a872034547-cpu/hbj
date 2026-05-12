# src/libriscribe/memory/version_history.py
"""版本历史管理

基于文件的检查点系统，每次重大操作保存快照，支持回滚。
"""

import json
import shutil
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class VersionHistory:
    """版本历史管理器"""

    def __init__(self, project_dir: str = None):
        self.project_dir = Path(project_dir) if project_dir else None
        self.history_dir = self.project_dir / ".history" if self.project_dir else None
        self._index_file = self.history_dir / "index.json" if self.history_dir else None
        self._index: List[Dict[str, Any]] = []

    def init(self, project_dir: str = None):
        """初始化版本历史目录"""
        if project_dir:
            self.project_dir = Path(project_dir)
            self.history_dir = self.project_dir / ".history"
            self._index_file = self.history_dir / "index.json"

        if self.history_dir:
            self.history_dir.mkdir(parents=True, exist_ok=True)
            self._load_index()

    def _load_index(self):
        """加载版本索引"""
        if self._index_file and self._index_file.exists():
            try:
                with open(self._index_file, "r", encoding="utf-8") as f:
                    self._index = json.load(f)
            except Exception as e:
                logger.error(f"Error loading version index: {e}")
                self._index = []

    def _save_index(self):
        """保存版本索引"""
        if not self._index_file:
            return

        try:
            self._index_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._index_file, "w", encoding="utf-8") as f:
                json.dump(self._index, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error saving version index: {e}")

    def create_checkpoint(self, description: str, files: List[str] = None) -> str:
        """创建检查点
        
        Args:
            description: 检查点描述
            files: 要保存的文件列表（相对于 project_dir），None 则保存所有 .md 和 .json 文件
            
        Returns:
            检查点 ID
        """
        if not self.project_dir or not self.history_dir:
            logger.error("Project directory not set")
            return ""

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        checkpoint_id = f"checkpoint_{timestamp}"
        checkpoint_dir = self.history_dir / checkpoint_id
        checkpoint_dir.mkdir(parents=True, exist_ok=True)

        # 确定要保存的文件
        if files is None:
            files = []
            for pattern in ["*.md", "*.json"]:
                files.extend([str(f.relative_to(self.project_dir)) for f in self.project_dir.glob(pattern) if ".history" not in str(f)])

        # 复制文件
        saved_files = []
        for file_rel in files:
            src = self.project_dir / file_rel
            if src.exists():
                dst = checkpoint_dir / file_rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                saved_files.append(file_rel)

        # 记录检查点
        checkpoint_info = {
            "id": checkpoint_id,
            "timestamp": timestamp,
            "description": description,
            "files": saved_files,
            "created_at": datetime.now().isoformat()
        }
        self._index.append(checkpoint_info)
        self._save_index()

        logger.info(f"Created checkpoint: {checkpoint_id} ({len(saved_files)} files)")
        return checkpoint_id

    def list_checkpoints(self) -> List[Dict[str, Any]]:
        """列出所有检查点
        
        Returns:
            检查点信息列表
        """
        return self._index.copy()

    def get_checkpoint(self, checkpoint_id: str) -> Optional[Dict[str, Any]]:
        """获取检查点信息
        
        Args:
            checkpoint_id: 检查点 ID
            
        Returns:
            检查点信息，不存在返回 None
        """
        for cp in self._index:
            if cp["id"] == checkpoint_id:
                return cp
        return None

    def restore_checkpoint(self, checkpoint_id: str) -> bool:
        """恢复到指定检查点
        
        Args:
            checkpoint_id: 检查点 ID
            
        Returns:
            是否成功恢复
        """
        checkpoint_info = self.get_checkpoint(checkpoint_id)
        if not checkpoint_info:
            logger.error(f"Checkpoint not found: {checkpoint_id}")
            return False

        checkpoint_dir = self.history_dir / checkpoint_id
        if not checkpoint_dir.exists():
            logger.error(f"Checkpoint directory not found: {checkpoint_dir}")
            return False

        # 恢复文件
        restored_files = []
        for file_rel in checkpoint_info["files"]:
            src = checkpoint_dir / file_rel
            dst = self.project_dir / file_rel
            if src.exists():
                shutil.copy2(src, dst)
                restored_files.append(file_rel)

        logger.info(f"Restored checkpoint {checkpoint_id}: {len(restored_files)} files")
        return True

    def delete_checkpoint(self, checkpoint_id: str) -> bool:
        """删除检查点
        
        Args:
            checkpoint_id: 检查点 ID
            
        Returns:
            是否成功删除
        """
        checkpoint_dir = self.history_dir / checkpoint_id
        if checkpoint_dir.exists():
            shutil.rmtree(checkpoint_dir)

        self._index = [cp for cp in self._index if cp["id"] != checkpoint_id]
        self._save_index()
        logger.info(f"Deleted checkpoint: {checkpoint_id}")
        return True

    def get_diff(self, checkpoint_id: str, file_name: str) -> Optional[Dict[str, str]]:
        """获取检查点与当前文件的差异
        
        Args:
            checkpoint_id: 检查点 ID
            file_name: 文件名（相对于 project_dir）
            
        Returns:
            {"old": "...", "new": "..."} 或 None
        """
        checkpoint_dir = self.history_dir / checkpoint_id
        old_file = checkpoint_dir / file_name
        new_file = self.project_dir / file_name

        if not old_file.exists() or not new_file.exists():
            return None

        try:
            with open(old_file, "r", encoding="utf-8") as f:
                old_content = f.read()
            with open(new_file, "r", encoding="utf-8") as f:
                new_content = f.read()
            return {"old": old_content, "new": new_content}
        except Exception as e:
            logger.error(f"Error getting diff: {e}")
            return None

    def cleanup(self, keep_last_n: int = 10):
        """清理旧检查点，只保留最近 N 个
        
        Args:
            keep_last_n: 保留的检查点数量
        """
        if len(self._index) <= keep_last_n:
            return

        # 按时间排序
        sorted_checkpoints = sorted(self._index, key=lambda x: x["created_at"])
        to_delete = sorted_checkpoints[:-keep_last_n]

        for cp in to_delete:
            self.delete_checkpoint(cp["id"])

        logger.info(f"Cleaned up {len(to_delete)} old checkpoints")

    @property
    def count(self) -> int:
        """返回检查点数量"""
        return len(self._index)