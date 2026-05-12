# src/libriscribe/web/__init__.py
"""Streamlit Web UI for Libriscribe."""

# 旧版多页面模块已迁移到 legacy_pages，避免 Streamlit 自动发现 pages 目录并在启动时闪现英文导航。
# 主应用入口使用 libriscribe.web.app 中的单页路由，不再从这里导出旧 Dashboard。

__all__ = []
