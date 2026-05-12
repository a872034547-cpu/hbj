"""全局设置服务。

集中保存与项目无关的网站名称、全局参数、视觉风格、默认模型档案和全局提示词。
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


DEFAULT_GLOBAL_SETTINGS: dict[str, Any] = {
    "site_name": "好编辑",
    "site_subtitle": "按顺序完成：项目 → 资料 → 大纲 → 写章节 → 审校 → 导出。",
    "style": {
        "theme": "米白玻璃风",
        "primary_color": "#496D57",
        "accent_color": "#B9863D",
        "writing_tone": "严谨、清晰、专著体",
    },
    "parameters": {
        "default_language": "简体中文",
        "rag_top_k": 5,
        "target_word_tolerance": 20,
        "anti_hallucination": True,
        "fullwidth_indent": True,
    },
    "model": {
        "default_profile_id": "",
        "temperature": 0.35,
        "max_tokens": 8000,
    },
    "prompts": {},
}


class GlobalSettingsService:
    """读写全局配置，不与任何单个项目绑定。"""

    def __init__(self, config_path: str | Path | None = None) -> None:
        if config_path is None:
            config_path = Path(__file__).resolve().parents[3] / "config" / "global_settings.json"
        self.config_path = Path(config_path)

    def load(self) -> dict[str, Any]:
        """加载全局设置，自动补齐缺失字段。"""
        data: dict[str, Any] = {}
        if self.config_path.exists():
            try:
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        return self._merge_defaults(data)

    def save(self, settings: dict[str, Any]) -> Path:
        """保存全局设置并返回配置文件路径。"""
        normalized = self._merge_defaults(settings)
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.config_path

    def get(self, key: str, default: Any = None) -> Any:
        return self.load().get(key, default)

    def get_prompt(self, prompt_key: str, default: str = "") -> str:
        prompts = self.load().get("prompts", {}) or {}
        return str(prompts.get(prompt_key) or default)

    def save_prompt(self, prompt_key: str, prompt_text: str) -> Path:
        settings = self.load()
        prompts = dict(settings.get("prompts", {}) or {})
        prompts[prompt_key] = prompt_text
        settings["prompts"] = prompts
        return self.save(settings)

    def reset_prompt(self, prompt_key: str) -> Path:
        settings = self.load()
        prompts = dict(settings.get("prompts", {}) or {})
        prompts.pop(prompt_key, None)
        settings["prompts"] = prompts
        return self.save(settings)

    @staticmethod
    def _merge_defaults(data: dict[str, Any]) -> dict[str, Any]:
        merged = deepcopy(DEFAULT_GLOBAL_SETTINGS)
        if not isinstance(data, dict):
            return merged
        for key, value in data.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key].update(value)
            else:
                merged[key] = value
        return merged
