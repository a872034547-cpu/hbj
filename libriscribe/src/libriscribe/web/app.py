from __future__ import annotations

"""
Libriscribe Web UI - Streamlit 主应用入口

使用方式:
    cd libriscribe
    streamlit run src/libriscribe/web/app.py
"""

import sys

# 修复 Windows GBK 编码问题：仅在 Streamlit 提供的标准流可用时重新配置编码。
# 不再手动 TextIOWrapper 包装 stdout/stderr；Streamlit rerun 或热重载时标准流可能已关闭，
# 强行访问 sys.stdout.buffer 会触发 “ValueError: I/O operation on closed file”。
if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        try:
            if _stream and not getattr(_stream, "closed", False) and hasattr(_stream, "reconfigure"):
                _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

import streamlit as st
import hashlib
import json
import logging
import re
import threading
import time
import uuid
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, Sequence

# ── Libriscribe 核心模块 ──────────────────────────────────────────────
from libriscribe.knowledge_base import ProjectKnowledgeBase, SourceDocument, EvidenceChunk, Citation
from libriscribe.services import (
    CitationService,
    GlobalSettingsService,
    LiteratureSearchService,
    OutlineService,
    PipelineService,
    PromptService,
    QualityService,
    SourceService,
)
from libriscribe.settings import Settings
from libriscribe.utils.llm_client import LLMClient
from libriscribe.utils.chinese_labels import chinese_number, format_chapter_label, chapter_heading_pattern, strip_leading_chapter_heading
from libriscribe.web.i18n import t, get_lang, TRANSLATIONS

logger = logging.getLogger(__name__)


# ── 后台任务管理器 ────────────────────────────────────────────────────
class BackgroundTaskManager:
    """管理后台 AI 任务的执行、进度追踪和结果存储。
    
    任务在独立线程中运行，即使关闭页面也会继续执行。
    结果保存在 session_state 中，页面重新打开后可查看。
    """

    def __init__(self):
        self._tasks: Dict[str, Dict[str, Any]] = {}

    def start_task(
        self,
        task_type: str,
        task_func,
        task_args: tuple = (),
        task_kwargs: dict = None,
        description: str = "",
        pass_progress_callback: bool = False,
    ) -> str:
        """启动一个后台任务，返回任务 ID。"""
        task_id = str(uuid.uuid4())[:8]
        task_info = {
            "id": task_id,
            "type": task_type,
            "description": description,
            "status": "running",
            "progress": 0.0,
            "message": "",
            "result": None,
            "error": None,
            "started_at": datetime.now().isoformat(),
            "completed_at": None,
        }
        self._tasks[task_id] = task_info

        def _run():
            try:
                kwargs = dict(task_kwargs or {})
                if pass_progress_callback:
                    kwargs["progress_callback"] = lambda progress, message="": self.update_progress(task_id, progress, message)
                result = task_func(*task_args, **kwargs)
                # 检查返回值是否为错误字符串（后台函数返回 "ERROR: ..." 而非抛异常）
                if isinstance(result, str) and result.startswith("ERROR"):
                    self._tasks[task_id]["status"] = "failed"
                    self._tasks[task_id]["error"] = result
                    self._tasks[task_id]["completed_at"] = datetime.now().isoformat()
                    self._tasks[task_id]["message"] = f"任务失败: {result}"
                else:
                    self._tasks[task_id]["status"] = "completed"
                    self._tasks[task_id]["progress"] = 1.0
                    self._tasks[task_id]["result"] = result
                    self._tasks[task_id]["completed_at"] = datetime.now().isoformat()
                    self._tasks[task_id]["message"] = "任务完成"
            except Exception as e:
                self._tasks[task_id]["status"] = "failed"
                self._tasks[task_id]["error"] = str(e)
                self._tasks[task_id]["completed_at"] = datetime.now().isoformat()
                self._tasks[task_id]["message"] = f"任务失败: {e}"
                logger.exception("Background task %s failed", task_id)

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        return task_id

    def update_progress(self, task_id: str, progress: float, message: str = ""):
        """更新任务进度（可从任务函数内部调用）。"""
        if task_id in self._tasks:
            self._tasks[task_id]["progress"] = min(progress, 1.0)
            if message:
                self._tasks[task_id]["message"] = message

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        return self._tasks.get(task_id)

    def get_all_tasks(self) -> Dict[str, Dict[str, Any]]:
        return self._tasks

    def get_running_tasks(self) -> list:
        return [t for t in self._tasks.values() if t["status"] == "running"]

    def clear_completed(self):
        """清除已完成和失败的任务。"""
        to_remove = [
            tid for tid, t in self._tasks.items()
            if t["status"] in ("completed", "failed")
        ]
        for tid in to_remove:
            del self._tasks[tid]


def _get_task_manager() -> BackgroundTaskManager:
    """获取全局后台任务管理器（存储在 session_state 中）。"""
    if "bg_task_manager" not in st.session_state:
        st.session_state["bg_task_manager"] = BackgroundTaskManager()
    return st.session_state["bg_task_manager"]


def _render_task_progress():
    """渲染后台任务进度条（可在任何页面调用）。"""
    mgr = _get_task_manager()
    running = mgr.get_running_tasks()
    if not running:
        return

    st.markdown("---")
    st.markdown("### 后台任务")
    for task in running:
        progress_val = task.get("progress", 0.0)
        msg = task.get("message", "")
        desc = task.get("description", task.get("type", ""))
        st.progress(progress_val, text=f"{desc} — {msg}" if msg else desc)

    # 自动刷新（每 3 秒）
    time.sleep(0.1)


def _render_task_results():
    """渲染已完成/失败的任务结果。"""
    mgr = _get_task_manager()
    all_tasks = mgr.get_all_tasks()
    completed = [t for t in all_tasks.values() if t["status"] in ("completed", "failed")]

    if not completed:
        return

    for task in completed:
        if task["status"] == "completed":
            st.success(f"{task.get('description', task['type'])} — 完成")
        elif task["status"] == "failed":
            st.error(f"{task.get('description', task['type'])} — 失败: {task.get('error', '未知错误')}")

    if st.button("清除已完成任务", key="clear_completed_tasks"):
        mgr.clear_completed()
        st.rerun()


# ── Streamlit 页面配置 ────────────────────────────────────────────────
_GLOBAL_SETTINGS = GlobalSettingsService().load()
st.set_page_config(
    page_title=f"{_GLOBAL_SETTINGS.get('site_name', '好编辑')} - AI 智能写作助手",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── 全局视觉系统：米白悬浮玻璃风 ──────────────────────────────────
HIDE_STREAMLIT_STYLE = """
<style>
    :root {
        --hb-bg: #faf8f2;
        --hb-bg-2: #f2eee4;
        --hb-paper: rgba(255, 252, 245, 0.80);
        --hb-paper-solid: #fffaf0;
        --hb-sidebar: rgba(247, 243, 234, 0.90);
        --hb-border: rgba(116, 93, 59, 0.16);
        --hb-border-strong: rgba(73, 109, 87, 0.32);
        --hb-ink: #243326;
        --hb-ink-soft: #4e5c50;
        --hb-muted: #71806f;
        --hb-green: #496d57;
        --hb-green-2: #2f5940;
        --hb-gold: #b9863d;
        --hb-shadow: 0 18px 45px rgba(76, 62, 38, 0.11);
        --hb-shadow-hover: 0 24px 60px rgba(76, 62, 38, 0.18);
        --hb-radius: 18px;
        --hb-blur: blur(18px) saturate(1.25);
    }

    html, body, #root, .stApp { background-color: var(--hb-bg) !important; }
    /* 隐藏 Streamlit 多页面自动发现导航，避免启动时短暂显示 app/chat/dashboard/editor/outline/settings 英文目录 */
    [data-testid="stSidebarNav"], [data-testid="stSidebarNavItems"], [data-testid="stPageLink-NavLink"], nav[aria-label="Pages"], nav[aria-label="页面"], section[data-testid="stSidebar"] > div:first-child > div:first-child:not([data-testid="stSidebarUserContent"]) {display: none !important; visibility: hidden !important; height: 0 !important; min-height: 0 !important; overflow: hidden !important;}
    #MainMenu {visibility: hidden !important;}
    footer {visibility: hidden !important;}
    [data-testid="stSidebarNav"] {display: none !important; visibility: hidden !important; height: 0 !important; min-height: 0 !important; overflow: hidden !important;}
    button[data-testid="stBaseButton-header"] {display: inline-flex !important; visibility: visible !important; opacity: 1 !important;}
    .stApp > header, header[data-testid="stHeader"], [data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stStatusWidget"] {
        display: none !important; height: 0 !important; min-height: 0 !important; background: transparent !important;
    }
    [data-testid="stSidebarHeader"] { display: none !important; height: 0 !important; min-height: 0 !important; padding: 0 !important; margin: 0 !important; background: transparent !important; }

    html, body, [class*="css"] {
        font-family: "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Segoe UI", Arial, sans-serif !important;
        color: var(--hb-ink) !important;
        text-rendering: optimizeLegibility;
        -webkit-font-smoothing: antialiased;
    }

    html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"], [data-testid="stMainBlockContainer"], [data-testid="stVerticalBlock"], .main, .main .block-container {
        background:
            radial-gradient(circle at 15% 8%, rgba(185, 134, 61, 0.16), transparent 26%),
            radial-gradient(circle at 86% 18%, rgba(73, 109, 87, 0.13), transparent 30%),
            linear-gradient(rgba(116, 93, 59, 0.028) 1px, transparent 1px),
            linear-gradient(90deg, rgba(116, 93, 59, 0.026) 1px, transparent 1px),
            linear-gradient(135deg, var(--hb-bg), var(--hb-bg-2)) !important;
        background-size: auto, auto, 34px 34px, 34px 34px, auto !important;
        color: var(--hb-ink) !important;
    }

    .block-container { padding-top: 0.85rem !important; padding-bottom: 3rem !important; max-width: 1320px !important; }
    h1, h2, h3 { color: var(--hb-ink) !important; letter-spacing: -0.01em; }
    h1 { position: relative; padding-bottom: 0.45rem; font-weight: 760 !important; font-size: 1.82rem !important; }
    h1::after { content: ""; position: absolute; left: 0; bottom: 0; width: 86px; height: 3px; border-radius: 99px; background: linear-gradient(90deg, var(--hb-green), var(--hb-gold)); opacity: 0.92; }
    p, li, label, span, div { line-height: 1.64; }

    [data-testid="stForm"], [data-testid="stExpander"], [data-testid="stMetric"], div[data-testid="stVerticalBlockBorderWrapper"], div[data-testid="stAlert"], div[data-testid="stTabs"] > div:last-child > div {
        border: 1px solid var(--hb-border) !important;
        border-radius: var(--hb-radius) !important;
        background: var(--hb-paper) !important;
        box-shadow: var(--hb-shadow) !important;
        backdrop-filter: var(--hb-blur);
        -webkit-backdrop-filter: var(--hb-blur);
    }
    [data-testid="stMetric"] { padding: 1rem 1.05rem !important; overflow: hidden; position: relative; }
    [data-testid="stMetric"]::before { content: ""; position: absolute; inset: 0 auto 0 0; width: 4px; background: linear-gradient(180deg, var(--hb-green), var(--hb-gold)); opacity: 0.9; }
    [data-testid="stMetricLabel"] p { color: var(--hb-muted) !important; font-weight: 650 !important; }
    [data-testid="stMetricValue"] { color: var(--hb-green-2) !important; font-weight: 760 !important; }

    [data-testid="stSidebar"], [data-testid="stSidebar"] *, [data-testid="stSidebarContent"], [data-testid="stSidebarUserContent"], [data-testid="collapsedControl"], section[data-testid="stSidebar"], section[data-testid="stSidebar"] > div, section[data-testid="stSidebar"] .block-container {
        background-color: transparent !important;
        background-image: none !important;
    }
    [data-testid="stSidebar"] {
        background: linear-gradient(rgba(255,255,255,0.42), rgba(255,250,240,0.22)), radial-gradient(circle at 30% 0%, rgba(185, 134, 61, 0.15), transparent 40%), var(--hb-sidebar) !important;
        border-right: 1px solid var(--hb-border) !important;
        box-shadow: 14px 0 45px rgba(77, 63, 40, 0.11) !important;
        backdrop-filter: var(--hb-blur);
        -webkit-backdrop-filter: var(--hb-blur);
    }
    [data-testid="stSidebar"] > div:first-child, [data-testid="stSidebarContent"] { padding-top: 0rem !important; margin-top: 0rem !important; }
    section[data-testid="stSidebar"] .block-container { padding-top: 0.35rem !important; padding-bottom: 0.7rem !important; }
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div:first-child { padding-top: 0rem !important; }
    [data-testid="stSidebar"] h1 { font-size: 1.38rem !important; line-height: 1.35 !important; padding: 0.58rem 0.25rem 0.2rem !important; margin-bottom: 0.05rem !important; color: var(--hb-green-2) !important; }
    [data-testid="stSidebar"] h1::after { width: 78px; height: 2px; background: linear-gradient(90deg, var(--hb-green), var(--hb-gold)); }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p, [data-testid="stSidebar"] label, [data-testid="stSidebar"] .stCaptionContainer { color: var(--hb-ink-soft) !important; }

    .hb-sidebar-nav-title {
        width: 100%; margin: 0.42rem 0 0.62rem; text-align: center;
        color: #203325; font-size: 0.92rem; font-weight: 880; letter-spacing: 0.12em;
    }
    .hb-sidebar-nav-list {
        width: 100%; padding: 0; margin: 0 auto 0.25rem;
        box-sizing: border-box;
    }
    [data-testid="stSidebar"] .hb-sidebar-nav-list + div,
    [data-testid="stSidebar"] div[data-testid="stButton"] {
        width: 100% !important;
        max-width: 100% !important;
        margin-left: 0 !important;
        margin-right: 0 !important;
        box-sizing: border-box !important;
    }
    [data-testid="stSidebar"] div[data-testid="stButton"] > button {
        width: 100% !important;
        max-width: 100% !important;
        min-width: 100% !important;
        min-height: 2.58rem !important;
        display: flex !important;
        align-items: center !important;
        justify-content: flex-start !important;
        padding: 0.52rem 0.95rem !important;
        box-sizing: border-box !important;
        border-radius: 14px !important;
        text-align: left !important;
        white-space: nowrap !important;
    }
    [data-testid="stSidebar"] div[data-testid="stButton"] > button[kind="secondary"] {
        border-color: rgba(73, 109, 87, 0.22) !important;
        background: rgba(255, 253, 247, 0.72) !important;
        color: var(--hb-green-2) !important;
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.88), 0 6px 14px rgba(76, 62, 38, 0.06) !important;
    }
    [data-testid="stSidebar"] div[data-testid="stButton"] > button[kind="secondary"]:hover {
        background: rgba(255, 250, 240, 0.95) !important;
        border-color: rgba(73, 109, 87, 0.34) !important;
        color: var(--hb-green-2) !important;
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.92), 0 10px 20px rgba(76, 62, 38, 0.10) !important;
    }
    [data-testid="stSidebar"] div[data-testid="stButton"] > button[kind="primary"] {
        border-color: rgba(73, 109, 87, 0.42) !important;
        background: linear-gradient(135deg, #496d57, #365844) !important;
        color: #fffaf0 !important;
        box-shadow: 0 12px 26px rgba(73, 109, 87, 0.18) !important;
    }
    [data-testid="stSidebar"] div[data-testid="stButton"] > button p,
    [data-testid="stSidebar"] div[data-testid="stButton"] > button span,
    [data-testid="stSidebar"] div[data-testid="stButton"] > button div {
        width: 100% !important;
        margin: 0 !important;
        padding: 0 !important;
        text-align: left !important;
        line-height: 1.22 !important;
        justify-content: flex-start !important;
    }

    .stButton > button, .stDownloadButton > button, button[kind="primary"], button[kind="secondary"] {
        border: 1px solid rgba(73, 109, 87, 0.28) !important;
        border-radius: 14px !important;
        background: linear-gradient(135deg, #496d57, #365844) !important;
        color: #fffaf0 !important;
        font-weight: 720 !important;
        box-shadow: 0 12px 26px rgba(73, 109, 87, 0.18) !important;
        transition: transform 0.18s ease, box-shadow 0.18s ease, background 0.18s ease;
    }
    .stButton > button:hover, .stDownloadButton > button:hover { transform: translateY(-2px); background: linear-gradient(135deg, #547b63, #3f654e) !important; box-shadow: 0 18px 36px rgba(73, 109, 87, 0.25) !important; }
    .stButton > button:disabled { opacity: 0.58 !important; filter: grayscale(0.12); }

    input, textarea, [data-baseweb="select"] > div, [data-baseweb="textarea"] textarea { border-radius: 14px !important; border-color: rgba(116, 93, 59, 0.25) !important; background-color: rgba(255, 253, 247, 0.96) !important; color: var(--hb-ink) !important; box-shadow: inset 0 1px 0 rgba(255,255,255,0.85) !important; }
    input:focus, textarea:focus, [data-baseweb="select"] > div:focus-within { border-color: rgba(73, 109, 87, 0.56) !important; box-shadow: 0 0 0 3px rgba(73, 109, 87, 0.12) !important; }
    .stTabs [data-baseweb="tab-list"] { gap: 0.45rem; background: rgba(255, 250, 240, 0.62); padding: 0.38rem; border-radius: 16px; border: 1px solid var(--hb-border); box-shadow: inset 0 1px 0 rgba(255,255,255,0.8); }
    .stTabs [data-baseweb="tab"] { border-radius: 13px; color: var(--hb-muted); font-weight: 720; }
    .stTabs [aria-selected="true"] { background: rgba(73, 109, 87, 0.13); color: var(--hb-green-2) !important; }
    [data-testid="stProgress"] > div > div > div > div { background: linear-gradient(90deg, var(--hb-green), var(--hb-gold)) !important; }
    hr { border: none !important; height: 1px !important; background: linear-gradient(90deg, transparent, rgba(116, 93, 59, 0.28), transparent) !important; margin: 1.05rem 0 !important; }
    [data-testid="stExpander"] summary { border-radius: 16px !important; color: var(--hb-green-2) !important; font-weight: 720 !important; }
    [data-testid="stChatMessage"] { border: 1px solid var(--hb-border) !important; border-radius: 18px !important; background: rgba(255, 250, 240, 0.82) !important; box-shadow: var(--hb-shadow) !important; backdrop-filter: blur(12px); }
    svg, img { color: inherit !important; fill: currentColor; }
    [data-testid="stMarkdownContainer"], [data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li, label, span { font-size: 0.96rem; }
    code, pre { border-radius: 10px !important; background: rgba(73, 109, 87, 0.08) !important; color: #284631 !important; }

    /* 商业化工作台增强：提升按钮/导出区对比度，统一品牌图形与页面节奏 */
    .hb-brand-card {
        margin: 0.35rem auto 0.75rem;
        padding: 0.95rem 0.9rem;
        text-align: center;
        border: 1px solid rgba(73, 109, 87, 0.22);
        border-radius: 22px;
        background:
            radial-gradient(circle at 18% 18%, rgba(255,255,255,0.92), transparent 28%),
            linear-gradient(145deg, rgba(255,252,245,0.92), rgba(238,231,216,0.80));
        box-shadow: 0 18px 42px rgba(76, 62, 38, 0.14), inset 0 1px 0 rgba(255,255,255,0.90);
    }
    .hb-brand-logo {
        width: 58px; height: 58px; border-radius: 20px;
        display: inline-flex; align-items: center; justify-content: center;
        color: #fffaf0;
        background:
            radial-gradient(circle at 28% 24%, rgba(255,255,255,0.96), rgba(255,255,255,0.28) 18%, transparent 19%),
            conic-gradient(from 215deg, #2f5940 0 34%, #496d57 34% 67%, #b9863d 67% 100%);
        box-shadow: 0 16px 30px rgba(47, 89, 64, 0.28), inset 0 1px 0 rgba(255,255,255,0.45);
    }
    .hb-brand-logo svg { width: 35px; height: 35px; display:block; filter: drop-shadow(0 5px 9px rgba(28, 50, 35, 0.24)); }
    .hb-brand-name { margin-top: 0.58rem; color: #203325; font-size: 1.36rem; font-weight: 880; letter-spacing: -0.03em; }
    .hb-brand-subtitle { color: #4e5c50; font-size: 0.84rem; font-weight: 650; line-height: 1.45; }
    .hb-brand-pills { display:flex; justify-content:center; gap:0.35rem; flex-wrap:wrap; margin-top:0.56rem; }
    .hb-brand-pill { padding:0.16rem 0.48rem; border-radius:999px; background:rgba(73,109,87,0.10); color:#2f5940; font-size:0.72rem; font-weight:760; }

    .hb-hero {
        position: relative; overflow: hidden; margin: 0.15rem 0 1.1rem; padding: 1.45rem 1.55rem;
        border: 1px solid rgba(73, 109, 87, 0.20); border-radius: 28px;
        background:
            radial-gradient(circle at 88% 20%, rgba(185,134,61,0.22), transparent 26%),
            radial-gradient(circle at 10% 10%, rgba(73,109,87,0.16), transparent 30%),
            linear-gradient(135deg, rgba(255,252,245,0.94), rgba(246,240,228,0.82));
        box-shadow: 0 24px 64px rgba(76, 62, 38, 0.16), inset 0 1px 0 rgba(255,255,255,0.95);
    }
    .hb-hero h1 { margin: 0 !important; padding: 0 !important; font-size: 2.1rem !important; }
    .hb-hero h1::after { display: none !important; }
    .hb-hero p { max-width: 780px; margin: 0.55rem 0 0; color: #4e5c50; font-size: 1rem; font-weight: 560; }
    .hb-hero-badge { display:inline-flex; align-items:center; gap:0.42rem; margin-bottom:0.72rem; padding:0.24rem 0.64rem; border-radius:999px; background:rgba(73,109,87,0.11); color:#2f5940; font-weight:800; font-size:0.82rem; }
    .hb-section-title { margin: 1.1rem 0 0.55rem; color:#203325; font-size:1.08rem; font-weight:850; }
    .hb-action-grid { display:grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap:0.75rem; margin:0.6rem 0 1.0rem; }
    .hb-action-card { padding:0.92rem; border:1px solid rgba(116,93,59,0.16); border-radius:18px; background:rgba(255,252,245,0.74); box-shadow:0 14px 34px rgba(76,62,38,0.10); }
    .hb-action-card strong { color:#203325; }
    .hb-action-card span { display:block; color:#5a665b; font-size:0.84rem; margin-top:0.22rem; }
    .hb-product-grid { display:grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap:0.82rem; margin:0.75rem 0 1.2rem; }
    .hb-stage-card { position:relative; overflow:hidden; padding:1.05rem 1.08rem; border:1px solid rgba(73,109,87,0.18); border-radius:22px; background:linear-gradient(145deg, rgba(255,252,245,0.88), rgba(246,240,228,0.72)); box-shadow:0 18px 42px rgba(76,62,38,0.12), inset 0 1px 0 rgba(255,255,255,0.88); }
    .hb-stage-card::before { content:""; position:absolute; inset:0 auto 0 0; width:5px; background:linear-gradient(180deg, var(--hb-green), var(--hb-gold)); opacity:0.82; }
    .hb-stage-head { display:flex; align-items:center; justify-content:space-between; gap:0.75rem; margin-bottom:0.35rem; }
    .hb-stage-title { color:#203325; font-weight:860; font-size:1.02rem; }
    .hb-stage-desc { color:#59665d; font-size:0.88rem; margin-top:0.22rem; }
    .hb-status-pill { display:inline-flex; align-items:center; justify-content:center; min-width:5.4rem; padding:0.18rem 0.55rem; border-radius:999px; font-size:0.76rem; font-weight:830; }
    .hb-status-completed { color:#1f5135; background:rgba(73,109,87,0.14); border:1px solid rgba(73,109,87,0.22); }
    .hb-status-in_progress { color:#7b541e; background:rgba(185,134,61,0.16); border:1px solid rgba(185,134,61,0.24); }
    .hb-status-pending { color:#6b7168; background:rgba(113,128,111,0.12); border:1px solid rgba(113,128,111,0.18); }
    .hb-status-failed, .hb-status-risky { color:#873b2e; background:rgba(169,72,52,0.12); border:1px solid rgba(169,72,52,0.22); }
    .hb-progress-track { height:8px; margin-top:0.72rem; border-radius:999px; background:rgba(116,93,59,0.10); overflow:hidden; }
    .hb-progress-fill { height:100%; border-radius:999px; background:linear-gradient(90deg, var(--hb-green), var(--hb-gold)); }

    [data-testid="stSidebar"] .stButton > button, [data-testid="stSidebar"] .stDownloadButton > button {
        min-height: 2.45rem !important; color: #fffaf0 !important; text-shadow: 0 1px 1px rgba(0,0,0,0.12);
    }
    [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] { gap: 0.45rem !important; }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h3 { color:#203325 !important; font-size:0.98rem !important; margin-top:0.2rem !important; }
    [data-testid="stSidebar"] hr { margin: 0.72rem 0 !important; }
    .stDownloadButton > button { background: linear-gradient(135deg, #9b6b2f, #75501f) !important; color:#fffaf0 !important; }
    [data-testid="stAlert"] { color:#203325 !important; }
    [data-testid="stAlert"] * { color: inherit !important; }
    .hb-mobile-nav-card, .hb-floating-chat-card {
        margin: 0.35rem 0 0.85rem; padding: 0.82rem 0.95rem; border: 1px solid rgba(73, 109, 87, 0.18); border-radius: 18px;
        background: rgba(255, 252, 245, 0.82); box-shadow: 0 14px 34px rgba(76, 62, 38, 0.10); backdrop-filter: blur(14px);
    }
    .hb-mobile-nav-card strong, .hb-floating-chat-card strong { color:#203325; font-weight:880; }
    .hb-mobile-nav-card span, .hb-floating-chat-card span { color:#59665d; font-size:0.86rem; }
    .hb-floating-chat-button {
        position: fixed; right: 1.05rem; bottom: 1.05rem; z-index: 9999;
        width: 58px; height: 58px; border-radius: 999px; display:flex; align-items:center; justify-content:center;
        color:#fffaf0 !important; text-decoration:none !important; font-weight:900; font-size:1.08rem;
        background: linear-gradient(135deg, #2f5940, #496d57 55%, #b9863d);
        box-shadow: 0 18px 42px rgba(47, 89, 64, 0.34), inset 0 1px 0 rgba(255,255,255,0.32);
    }
    .hb-floating-chat-button:hover { transform: translateY(-2px); box-shadow: 0 22px 48px rgba(47, 89, 64, 0.42); }
    @media (max-width: 980px) {
        .hb-action-grid, .hb-product-grid { grid-template-columns: 1fr; }
        .hb-hero { padding: 1.05rem; }
        .block-container { padding-left: 0.85rem !important; padding-right: 0.85rem !important; padding-bottom: 5.4rem !important; }
        [data-testid="collapsedControl"] { display: block !important; visibility: visible !important; opacity: 1 !important; z-index: 10000 !important; }
        .hb-floating-chat-button { right: 0.85rem; bottom: 0.85rem; width: 54px; height: 54px; }
    }
</style>
"""
st.markdown(HIDE_STREAMLIT_STYLE, unsafe_allow_html=True)

# ── 常量 ──────────────────────────────────────────────────────────────
GLOBAL_SETTINGS_PAGE = "GlobalSettings"
NAV_PAGES = [
    "Projects",
    "Sources",
    "Outline",
    "Editor",
    "Prompts",
    "Quality",
    "Exports",
    "AIConfig",
]
MOBILE_NAV_PAGES = ["Workspace", *NAV_PAGES]
INTERNAL_PAGES = [
    "Workspace",
    "Pipeline",
    "Citations",
    "Tools",
    "Settings",
    "Audit",
]
NAV_PAGE_LABELS = {
    "GlobalSettings": "全局设置",
    "Workspace": "首页",
    "Projects": "① 项目",
    "Dashboard": "首页",  # legacy compatibility
    "Sources": "② 资料",
    "Outline": "③ 大纲",
    "Pipeline": "生产流水线",
    "Editor": "④ 写章节",
    "Citations": "引用核验",
    "Prompts": "⑤ 提示词",
    "Quality": "⑥ 审校",
    "Exports": "⑦ 导出",
    "Tools": "写作工具",
    "Chat": "写作工具",  # legacy compatibility
    "Settings": "项目设置",
    "AIConfig": "⑧ 模型设置",
    "Audit": "审计记录",
}
LEGACY_PAGE_ALIASES = {
    "Dashboard": "Workspace",
    "Chat": "Tools",
}
LLM_PROVIDERS = ["openai", "claude", "google_ai_studio", "deepseek", "mistral", "openrouter", "custom"]
PROVIDER_DISPLAY_NAMES = {
    "openai": "OpenAI",
    "claude": "Claude (Anthropic)",
    "google_ai_studio": "Google AI Studio (Gemini)",
    "deepseek": "DeepSeek",
    "mistral": "Mistral AI",
    "openrouter": "OpenRouter",
    "custom": "自定义 OpenAI 兼容平台",
}
DEFAULT_PROVIDER_MODELS = {
    "openai": "gpt-5.5",
    "claude": "claude-sonnet-4-5",
    "google_ai_studio": "gemini-3.1-pro-preview",
    "deepseek": "deepseek-v4-pro",
    "mistral": "mistral-medium-latest",
    "openrouter": "openai/gpt-5.5",
    "custom": "",
}
LEGACY_DEFAULT_PROVIDER_MODELS = {
    "openai": {"gpt-4o-mini", "gpt-4o"},
    "claude": {"claude-3-opus-20240229", "claude-3-5-sonnet-20241022", "claude-3-haiku-20240307"},
    "google_ai_studio": {"gemini-1.5-pro-002", "gemini-1.5-flash", "gemini-pro"},
    "deepseek": {"deepseek-chat", "deepseek-reasoner", "deepseek-coder-6.7b-instruct"},
    "mistral": {"mistral-medium", "mistral-small-latest"},
    "openrouter": {"anthropic/claude-3-haiku", "anthropic/claude-3-opus", "openai/gpt-4o-mini"},
}
PROVIDER_MODEL_GUIDANCE = {
    "openai": {
        "title": "OpenAI / GPT 模型配置提示",
        "recommended_model": "gpt-5.5",
        "key_url": "https://platform.openai.com/api-keys",
        "model_url": "https://platform.openai.com/docs/models",
        "api_base": "官方 OpenAI 通常留空；如果使用兼容中转/企业代理，填写形如 https://.../v1 的地址。",
        "required": "API Key、模型名。官方平台还需要账号已开通 API 计费和对应模型访问权限。",
        "notes": [
            "用户常说的 gpt5.5 在 API 中一般应按控制台模型名填写；本应用默认使用 gpt-5.5。",
            "如果检测返回网页或空响应，多半是 API Base 填到了网站首页而不是 /v1 接口。",
            "不同账号/地区可见模型可能不同，最终以 OpenAI 控制台 Models 页面为准。",
        ],
    },
    "claude": {
        "title": "Claude (Anthropic) 模型配置提示",
        "recommended_model": "claude-sonnet-4-5",
        "key_url": "https://console.anthropic.com/settings/keys",
        "model_url": "https://docs.anthropic.com/en/docs/about-claude/models/all-models",
        "api_base": "当前内置 Claude 客户端使用 Anthropic 官方端点，通常无需填写 API Base。",
        "required": "Anthropic Console API Key、Claude 模型名，并确保 anthropic Python 包已安装。",
        "notes": [
            "Claude 官方文档可能因地区访问限制打不开；模型名请以 Console 或官方文档为准。",
            "如需通过第三方 OpenAI 兼容网关调用 Claude，请改用“自定义 OpenAI 兼容平台”。",
        ],
    },
    "google_ai_studio": {
        "title": "Google AI Studio / Gemini 模型配置提示",
        "recommended_model": "gemini-3.1-pro-preview",
        "key_url": "https://aistudio.google.com/apikey",
        "model_url": "https://ai.google.dev/gemini-api/docs/models",
        "api_base": "内置 Gemini 客户端使用 Google AI Studio SDK，通常无需填写 API Base。",
        "required": "Google AI Studio API Key、Gemini 模型名，并确保 google-generativeai Python 包已安装。",
        "notes": [
            "Gemini preview/latest 模型可能有更严格限额或会滚动更新，生产写作可切换到稳定模型。",
            "如果所在地区不可用或配额不足，连接检测会失败，请先到 AI Studio 控制台确认额度。",
        ],
    },
    "deepseek": {
        "title": "DeepSeek 模型配置提示",
        "recommended_model": "deepseek-v4-pro",
        "key_url": "https://platform.deepseek.com/api_keys",
        "model_url": "https://api-docs.deepseek.com/",
        "api_base": "官方 OpenAI 兼容地址可留空；如手动填写建议使用 https://api.deepseek.com 或 https://api.deepseek.com/v1。",
        "required": "DeepSeek API Key、模型名。",
        "notes": [
            "DeepSeek 文档显示 deepseek-chat / deepseek-reasoner 将逐步弃用，推荐使用 deepseek-v4-flash 或 deepseek-v4-pro。",
            "本应用会自动拼接 /chat/completions；API Base 不要填写到完整 chat/completions 路径。",
        ],
    },
    "mistral": {
        "title": "Mistral AI 模型配置提示",
        "recommended_model": "mistral-medium-latest",
        "key_url": "https://console.mistral.ai/api-keys/",
        "model_url": "https://docs.mistral.ai/getting-started/models/models_overview/",
        "api_base": "官方 OpenAI 兼容地址可留空；自定义端点通常填写 https://api.mistral.ai/v1。",
        "required": "Mistral API Key、模型名。",
        "notes": [
            "Mistral 模型更新较快，latest 别名会随官方发布变动；如需稳定复现，可在控制台复制固定版本模型名。",
            "本应用会自动拼接 /chat/completions；API Base 不要填写到完整接口路径。",
        ],
    },
    "openrouter": {
        "title": "OpenRouter 聚合模型配置提示",
        "recommended_model": "openai/gpt-5.5",
        "key_url": "https://openrouter.ai/keys",
        "model_url": "https://openrouter.ai/models",
        "api_base": "必须使用 OpenAI 兼容地址 https://openrouter.ai/api/v1；本应用默认已填。",
        "required": "OpenRouter API Key、模型名（格式通常是 provider/model，例如 openai/gpt-5.5）。",
        "notes": [
            "OpenRouter 模型 ID 需要带供应商前缀，不能直接填写 gpt-5.5。",
            "部分模型需要额外余额、地区或供应商授权；以 OpenRouter 模型详情页为准。",
        ],
    },
    "custom": {
        "title": "自定义 OpenAI 兼容平台配置提示",
        "recommended_model": "",
        "key_url": "",
        "model_url": "",
        "api_base": "必须填写兼容 OpenAI Chat Completions 的 Base URL，通常形如 https://你的域名/v1。",
        "required": "API Base、API Key、模型名三项都必填。",
        "notes": [
            "不要把 API Base 填成网页首页、控制台地址或完整 /chat/completions；本应用会自动拼接 /chat/completions。",
            "如果平台只支持 Responses API 或参数名不同，连接检测可能失败，需要使用兼容 Chat Completions 的入口。",
        ],
    },
}
CATEGORIES = ["专著", "其他"]
PROJECT_LANGUAGES = ["简体中文", "English", "繁體中文", "日本語", "Français", "Deutsch", "Español"]
MODEL_PROFILE_CONFIG = Path(__file__).resolve().parents[3] / "config" / "model_profiles.json"
MATERIAL_INDEX_CONFIG = Path(__file__).resolve().parents[3] / "config" / "material_index_api.json"



def _default_material_index_config() -> dict:
    """资料索引 API 的独立默认配置；不属于任何模型档案。"""
    return {
        "enabled": False,
        "provider": "custom_openai",
        "api_base": "",
        "api_key": "",
        "model": "DeepSeek-V4-Flash",
        "updated_at": "",
    }



def _load_material_index_config() -> dict:
    """读取独立资料索引 API 配置；读取失败时回退为空配置且不触碰模型档案。"""
    MATERIAL_INDEX_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    defaults = _default_material_index_config()
    if not MATERIAL_INDEX_CONFIG.exists():
        return defaults
    try:
        data = json.loads(MATERIAL_INDEX_CONFIG.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to read material index API config: %s", exc)
        return defaults
    if not isinstance(data, dict):
        return defaults
    merged = {**defaults, **data}
    merged["provider"] = "custom_openai"
    return merged



def _save_material_index_config(config: dict) -> None:
    """保存独立资料索引 API 配置；只写 material_index_api.json。"""
    MATERIAL_INDEX_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    payload = {**_default_material_index_config(), **dict(config or {})}
    payload["provider"] = "custom_openai"
    payload["enabled"] = bool(payload.get("enabled"))
    payload["api_base"] = str(payload.get("api_base", "") or "").rstrip("/")
    payload["api_key"] = str(payload.get("api_key", "") or "")
    payload["model"] = str(payload.get("model", "") or "").strip()
    payload["updated_at"] = datetime.now().isoformat()
    temp_path = MATERIAL_INDEX_CONFIG.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(MATERIAL_INDEX_CONFIG)



def _material_index_config_ready(config: Optional[dict] = None) -> bool:
    """判断资料索引 API 是否已具备调用 /embeddings 的最小配置。"""
    config = _load_material_index_config() if config is None else dict(config or {})
    return bool(config.get("enabled") and str(config.get("api_key", "")).strip() and str(config.get("model", "")).strip())




def _profile_id(provider: str, name: str) -> str:
    base = f"{provider}_{name}".lower().strip()
    safe = "".join(c if c.isalnum() else "_" for c in base).strip("_")
    return safe or f"profile_{uuid.uuid4().hex[:8]}"


def _profile_label(profile: dict) -> str:
    provider = profile.get("provider", "custom")
    provider_name = PROVIDER_DISPLAY_NAMES.get(provider, provider)
    model = profile.get("model", "") or DEFAULT_PROVIDER_MODELS.get(provider, "") or "未设置模型"
    name = profile.get("name", provider_name)
    return f"{name} · {provider_name} · {model}"


def _model_provider_guidance(provider: str, model_name: str = "") -> dict:
    """返回模型配置页的用户引导文案，集中维护不同平台的密钥/模型/端点注意事项。"""
    guidance = dict(PROVIDER_MODEL_GUIDANCE.get(provider) or PROVIDER_MODEL_GUIDANCE["custom"])
    guidance["provider"] = provider
    guidance["display_name"] = PROVIDER_DISPLAY_NAMES.get(provider, provider)
    guidance["current_model"] = model_name or DEFAULT_PROVIDER_MODELS.get(provider, "") or guidance.get("recommended_model", "")
    return guidance


def _should_refresh_official_model_default(profile: dict) -> bool:
    """仅迁移官方空档案/旧内置档案的模型名，避免覆盖用户自定义选择和密钥。"""
    provider = profile.get("provider", "custom") or "custom"
    if provider == "custom" or profile.get("source") != "official":
        return False
    model = str(profile.get("model", "")).strip()
    if not model:
        return True
    if model in LEGACY_DEFAULT_PROVIDER_MODELS.get(provider, set()):
        return True
    return not profile.get("api_key") and not profile.get("updated_at") and model != DEFAULT_PROVIDER_MODELS.get(provider, model)


def _default_model_profiles() -> list[dict]:
    settings = Settings()
    defaults = []
    env_keys = {
        "openai": settings.openai_api_key,
        "claude": settings.claude_api_key,
        "google_ai_studio": settings.google_ai_studio_api_key,
        "deepseek": settings.deepseek_api_key,
        "mistral": settings.mistral_api_key,
        "openrouter": settings.openrouter_api_key,
    }
    for provider in LLM_PROVIDERS:
        api_base = ""
        if provider == "openrouter":
            api_base = settings.openrouter_base_url
        profile = {
            "id": _profile_id(provider, PROVIDER_DISPLAY_NAMES.get(provider, provider)),
            "name": PROVIDER_DISPLAY_NAMES.get(provider, provider),
            "provider": provider,
            "api_base": api_base,
            "api_key": env_keys.get(provider, ""),
            "model": DEFAULT_PROVIDER_MODELS.get(provider, ""),
            "enabled": bool(env_keys.get(provider, "")) if provider != "custom" else False,
            "source": "official" if provider != "custom" else "custom",
            "updated_at": "",
        }
        if provider == "custom":
            profile["name"] = "自定义第三方平台"
        defaults.append(profile)
    return defaults


def _dedupe_model_profiles(profiles: list[dict]) -> list[dict]:
    """按档案 ID/模型端点去重，并补齐字段，避免重复保存或异常中断造成脏数据。"""
    normalized: list[dict] = []
    seen_ids: set[str] = set()
    seen_signatures: set[tuple[str, str, str, str]] = set()
    for raw in profiles:
        if not isinstance(raw, dict):
            continue
        profile = dict(raw)
        provider = profile.get("provider", "custom") or "custom"
        profile.setdefault("id", _profile_id(provider, profile.get("name", provider)))
        profile.setdefault("name", PROVIDER_DISPLAY_NAMES.get(provider, provider))
        profile.setdefault("api_base", "")
        profile.setdefault("api_key", "")
        profile.setdefault("model", DEFAULT_PROVIDER_MODELS.get(provider, ""))
        profile.setdefault("enabled", bool(profile.get("api_key")))
        profile.setdefault("source", "official" if provider != "custom" else "custom")
        profile.setdefault("updated_at", "")
        if _should_refresh_official_model_default(profile):
            profile["model"] = DEFAULT_PROVIDER_MODELS.get(provider, profile.get("model", ""))
        signature = (
            provider,
            str(profile.get("name", "")).strip().lower(),
            str(profile.get("api_base", "")).rstrip("/").lower(),
            str(profile.get("model", "")).strip().lower(),
        )
        if profile["id"] in seen_ids or signature in seen_signatures:
            normalized = [
                p for p in normalized
                if p.get("id") != profile["id"] and (
                    p.get("provider", "custom"),
                    str(p.get("name", "")).strip().lower(),
                    str(p.get("api_base", "")).rstrip("/").lower(),
                    str(p.get("model", "")).strip().lower(),
                ) != signature
            ]
        seen_ids.add(profile["id"])
        seen_signatures.add(signature)
        normalized.append(profile)
    return normalized


def _load_model_profiles() -> list[dict]:
    """从本地 JSON 永久配置读取模型档案。

    读取时不再无条件回写，避免页面刷新/Streamlit rerun 把用户配置覆盖掉；
    只有配置文件不存在或需要修复损坏 JSON 时才写入磁盘。
    """
    MODEL_PROFILE_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    should_persist = False
    if not MODEL_PROFILE_CONFIG.exists():
        profiles = _default_model_profiles()
        _save_model_profiles(profiles)
        return profiles
    try:
        raw_text = MODEL_PROFILE_CONFIG.read_text(encoding="utf-8")
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            # 兼容异常中断/手工编辑导致的相邻对象漏逗号，尽量恢复而不是丢失用户密钥配置。
            repaired_text = re.sub(r"}\s*\n\s*{", "},\n    {", raw_text)
            data = json.loads(repaired_text)
            logger.warning("Recovered malformed model profile config by repairing missing separators")
            MODEL_PROFILE_CONFIG.with_suffix(".json.bak").write_text(raw_text, encoding="utf-8")
            should_persist = True
        profiles = data.get("profiles", []) if isinstance(data, dict) else []
    except Exception:
        logger.exception("Failed to load model profiles")
        # 读取失败时返回默认项用于页面兜底，但不覆盖磁盘上的用户配置文件。
        return _default_model_profiles()

    defaults_by_provider = {p["provider"]: p for p in _default_model_profiles()}
    existing_providers = {p.get("provider") for p in profiles if isinstance(p, dict)}
    for provider, profile in defaults_by_provider.items():
        if provider not in existing_providers:
            profiles.append(profile)
    normalized = _dedupe_model_profiles(profiles)
    if normalized != profiles:
        should_persist = True
    if should_persist:
        _save_model_profiles(normalized)
    return normalized


def _save_model_profiles(profiles: list[dict]) -> None:
    """将模型档案永久保存到本地 JSON；先备份再原子替换，确保下次启动继续读取。"""
    MODEL_PROFILE_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"profiles": _dedupe_model_profiles(profiles)}, ensure_ascii=False, indent=2)
    if MODEL_PROFILE_CONFIG.exists():
        MODEL_PROFILE_CONFIG.with_suffix(".json.bak").write_text(
            MODEL_PROFILE_CONFIG.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    temp_path = MODEL_PROFILE_CONFIG.with_suffix(".json.tmp")
    temp_path.write_text(payload, encoding="utf-8")
    temp_path.replace(MODEL_PROFILE_CONFIG)


def _available_model_profiles(require_ready: bool = False) -> list[dict]:
    profiles = _load_model_profiles()
    if require_ready:
        profiles = [p for p in profiles if p.get("enabled") and p.get("api_key") and p.get("model")]
    return profiles


def _find_model_profile(profile_id: str) -> Optional[dict]:
    for profile in _load_model_profiles():
        if profile.get("id") == profile_id:
            return profile
    return None


def _resolve_project_model_profile(project: Optional[ProjectKnowledgeBase]) -> Optional[dict]:
    profiles = _available_model_profiles(require_ready=True)
    if not profiles:
        return None
    if project is not None:
        selected_id = getattr(project, "model_profile_id", "")
        for profile in profiles:
            if profile.get("id") == selected_id:
                return profile
        for profile in profiles:
            if profile.get("provider") == getattr(project, "llm_provider", ""):
                return profile
    return profiles[0]


def _create_llm_client_from_profile(profile: dict) -> LLMClient:
    provider = profile.get("provider", "custom")
    api_base = (profile.get("api_base", "") or "").strip()
    if provider == "custom" and api_base and not api_base.rstrip("/").endswith("/v1"):
        api_base = api_base.rstrip("/") + "/v1"
    return LLMClient(
        llm_provider=provider,
        api_base=api_base,
        api_key=profile.get("api_key", ""),
        model=profile.get("model", ""),
    )


def _profile_connection_result(profile: dict, test_prompt: str) -> tuple[bool, str]:
    try:
        if not profile.get("api_key"):
            return False, "未填写 API 密钥"
        if not profile.get("model"):
            return False, "未填写模型名称"
        client = _create_llm_client_from_profile(profile)
        probe_prompt = (test_prompt or "请只回复两个大写字母：OK，不要输出其它内容。").strip()
        response = client.generate_content(probe_prompt, max_tokens=80, temperature=0.0)
        if not response:
            details = (getattr(client, "last_error", "") or getattr(client, "last_response_preview", "") or "无可用响应预览").strip()
            return False, f"模型接口已调用，但应用未提取到正文。诊断信息：{details[:800]}"
        response_text = str(response).strip()
        if LLMClient._is_role_marker_only(response_text):
            preview = response_text[:120]
            return False, (
                f"接口只返回了 chat 角色标记“{preview}”，没有真实正文，不能判定为在线可用。"
                "请检查 API Base、模型名称和中转平台的 OpenAI-compatible /chat/completions 配置。"
            )
        lowered = response_text.lower()
        if any(sig in lowered for sig in ("<!doctype html", "<html", "</html>", "<title>", "hublinuxdo")):
            preview = response_text[:500]
            return False, f"接口返回了网页/错误页，不是有效模型响应。请检查 API Base 是否填到了模型接口地址。响应预览：{preview}"
        return True, response_text[:500]
    except Exception as e:
        return False, str(e)


def _sync_project_model_fields(project: ProjectKnowledgeBase, profile: dict) -> ProjectKnowledgeBase:
    data = project.model_dump()
    data["model_profile_id"] = profile.get("id", "")
    data["llm_provider"] = profile.get("provider", "openai")
    data["custom_api_base"] = profile.get("api_base", "")
    data["custom_api_key"] = profile.get("api_key", "")
    data["custom_model"] = profile.get("model", "")
    return ProjectKnowledgeBase.model_validate(data)

# ══════════════════════════════════════════════════════════════════════
#  辅助函数
# ══════════════════════════════════════════════════════════════════════

def init_session_state() -> None:
    """初始化所有 session_state 变量（仅在首次访问时设置默认值）"""
    defaults = {
        "project_data": None,          # ProjectKnowledgeBase | None
        "current_page": "Dashboard",   # 当前导航页面
        "llm_client": None,            # LLMClient | None
        "project_dir": None,           # str | None — 项目目录路径
        "project_file": None,          # str | None — knowledge_base.json 路径
        "chat_history": [],            # 聊天记录
        "floating_chat_history": [],   # 页面悬浮 AI 对话记录
        "notification": None,          # 临时通知消息
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    # 检测旧数据兼容性：如果已加载的项目缺少新字段，强制重新加载
    project = st.session_state.get("project_data")
    if project is not None:
        try:
            _ = project.custom_api_base
            _ = project.model_profile_id
        except (AttributeError, ValueError):
            project_file = st.session_state.get("project_file")
            if project_file:
                logger.info("Detected old project data, reloading from file: %s", project_file)
                reloaded = ProjectKnowledgeBase.load_from_file(project_file)
                if reloaded is not None:
                    st.session_state["project_data"] = reloaded
                    st.session_state["llm_client"] = None  # 重置 LLM 客户端


def load_project(project_path: str) -> Optional[ProjectKnowledgeBase]:
    """
    从 JSON 文件加载项目。

    Args:
        project_path: knowledge_base.json 的完整路径

    Returns:
        ProjectKnowledgeBase 实例，加载失败返回 None
    """
    path = Path(project_path)
    if not path.exists():
        st.error(t('project_file_not_found', path=project_path))
        return None

    try:
        project = ProjectKnowledgeBase.load_from_file(str(path))
        if project is None:
            st.error(t('project_parse_error'))
            return None

        # 更新 session state
        st.session_state["project_data"] = project
        st.session_state["project_file"] = str(path)
        st.session_state["project_dir"] = str(path.parent)
        st.session_state["llm_client"] = None  # 重置，后续按项目配置重建

        st.success(t('project_loaded', title=project.title))
        return project

    except Exception as e:
        st.error(t('project_load_error', e=e))
        logger.exception("Failed to load project")
        return None


def save_project() -> bool:
    """
    将当前项目保存到 JSON 文件。

    Returns:
        保存是否成功
    """
    project: Optional[ProjectKnowledgeBase] = st.session_state.get("project_data")
    project_file: Optional[str] = st.session_state.get("project_file")

    if project is None:
        st.warning(t('no_project_to_save'))
        return False

    if not project_file:
        st.warning(t('no_project_path'))
        return False

    try:
        Path(project_file).parent.mkdir(parents=True, exist_ok=True)
        project.save_to_file(project_file)
        st.success(t('project_saved'))
        return True
    except Exception as e:
        st.error(t('project_save_error', e=e))
        logger.exception("Failed to save project")
        return False


def _clean_project_display_text(value: Any) -> str:
    """清理旧版默认占位文本，避免进入专著检索词、提示词和页面展示。"""
    text = str(value or "").strip()
    legacy_placeholders = {
        "No description provided.",
        "No logline available",
        "Unknown Genre",
        "Unknown Category",
        "Untitled",
        "None",
        "null",
    }
    return "" if text in legacy_placeholders else text


def _join_project_context_parts(parts: list[Any], *, separator: str = " ", limit: int = 0) -> str:
    """拼接项目上下文，自动过滤旧小说模式遗留占位值。"""
    text = separator.join(_clean_project_display_text(part) for part in parts if _clean_project_display_text(part))
    return text[:limit] if limit else text


def _is_usable_evidence_text(text: str) -> bool:
    """资料库 UI 展示前的最后一道乱码过滤。"""
    try:
        from libriscribe.rag.document_loader import DocumentLoader
        return DocumentLoader().is_usable_text(text or "")
    except Exception:
        sample = (text or "")[:8000]
        compact = re.sub(r"[\x00\s�\ufffd]+", "", sample).lower()
        bad_markers = ("rootentry", "worddocument", "normal.dotm", "wpsoffice", "compobj")
        return not (sum(1 for marker in bad_markers if marker in compact) >= 2 or sample.startswith("ÐÏ"))


def _purge_bad_rag_state(project: ProjectKnowledgeBase, *, persist: bool = False) -> tuple[int, int]:
    """清理项目内已经进入 session_state/JSON 的二进制乱码资料与证据。"""
    evidence_chunks = list(getattr(project, "evidence_chunks", []) or [])
    bad_document_ids = {
        getattr(chunk, "document_id", "")
        for chunk in evidence_chunks
        if not _is_usable_evidence_text(getattr(chunk, "text", ""))
    }
    bad_document_ids.discard("")

    original_chunks = len(evidence_chunks)
    project.evidence_chunks = [
        chunk for chunk in evidence_chunks
        if getattr(chunk, "document_id", "") not in bad_document_ids
        and _is_usable_evidence_text(getattr(chunk, "text", ""))
    ]

    source_documents = list(getattr(project, "source_documents", []) or [])
    original_sources = len(source_documents)
    project.source_documents = [
        doc for doc in source_documents
        if getattr(doc, "id", "") not in bad_document_ids
    ]

    removed_sources = original_sources - len(project.source_documents)
    removed_chunks = original_chunks - len(project.evidence_chunks)
    if (removed_sources or removed_chunks) and persist:
        st.session_state["project_data"] = project
        save_project()
    return removed_sources, removed_chunks


def _purge_bad_vector_results(results: list[dict]) -> list[dict]:
    """过滤检索结果中的历史乱码向量，防止旧 ChromaDB 残留继续显示。"""
    return [result for result in results if _is_usable_evidence_text(result.get("content", ""))]


def get_llm_client() -> Optional[LLMClient]:
    """
    获取或创建 LLMClient 实例（缓存在 session_state 中）。

    Returns:
        LLMClient 实例，创建失败返回 None
    """
    project: Optional[ProjectKnowledgeBase] = st.session_state.get("project_data")
    profile = _resolve_project_model_profile(project)
    if profile is None:
        st.warning("请先到「模型配置」页面配置并启用一个模型档案。")
        return None

    # Streamlit 会保留 session_state；代码热更新或配置修改后，旧 LLMClient 可能仍停留在内存里，
    # 导致网页继续使用未修复的 SDK 调用路径。用配置签名强制刷新客户端。
    profile_signature = json.dumps(
        {
            "provider": profile.get("provider", ""),
            "api_base": profile.get("api_base", ""),
            "model": profile.get("model", ""),
            "api_key_tail": (profile.get("api_key", "") or "")[-8:],
            # 每次代码更新后自动刷新客户端，避免热更新时沿用旧类实例；无需手动重启。
            "client_code_version": "custom-openai-raw-http-v4-writing-retry-no-sdk-stream",
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    cached_client = st.session_state.get("llm_client")
    cached_signature = st.session_state.get("llm_client_signature")
    if cached_client is not None and cached_signature == profile_signature:
        return cached_client

    try:
        client = _create_llm_client_from_profile(profile)
        st.session_state["llm_client"] = client
        st.session_state["llm_client_signature"] = profile_signature
        return client
    except ValueError as e:
        st.error(t('llm_create_error', e=e))
        logger.error("LLM client creation failed: %s", e)
        return None
    except Exception as e:
        st.error(t('llm_unknown_error', e=e))
        logger.exception("Unexpected error creating LLM client")
        return None


def create_new_project(
    project_name: str,
    title: str,
    category: str,
    genre: str,
    language: str = "English",
    model_profile_id: str = "",
) -> Optional[ProjectKnowledgeBase]:
    """
    创建新项目并保存到磁盘。

    Args:
        project_name: 项目内部名称（用作目录名）
        title: 书名
        category: 分类
        genre: 类型/风格
        language: 语言
        model_profile_id: 统一模型配置页中的模型档案 ID

    Returns:
        新建的 ProjectKnowledgeBase，失败返回 None
    """
    settings = Settings()
    projects_dir = Path(settings.projects_dir)
    project_dir = projects_dir / project_name
    project_file = project_dir / "knowledge_base.json"

    if project_dir.exists():
        st.error(t('project_dir_exists', dir=project_dir))
        return None

    try:
        project_dir.mkdir(parents=True, exist_ok=True)

        profile = _find_model_profile(model_profile_id) or _resolve_project_model_profile(None)
        if profile is None:
            st.error("请先到「模型配置」页面配置并启用一个模型档案。")
            return None

        project = ProjectKnowledgeBase(
            project_name=project_name,
            title=title,
            category=category,
            genre=genre,
            language=language,
            llm_provider=profile.get("provider", "openai"),
            model_profile_id=profile.get("id", ""),
            custom_api_base=profile.get("api_base", ""),
            custom_api_key=profile.get("api_key", ""),
            custom_model=profile.get("model", ""),
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
        )
        project.save_to_file(str(project_file))

        # 更新 session state
        st.session_state["project_data"] = project
        st.session_state["project_file"] = str(project_file)
        st.session_state["project_dir"] = str(project_dir)
        st.session_state["llm_client"] = None

        st.success(t('project_created', title=title))
        return project

    except Exception as e:
        st.error(t('project_create_error', e=e))
        logger.exception("Failed to create project")
        return None


PROJECT_DELETE_PASSWORD = "hbj123"


def _safe_project_import_name(name: str) -> str:
    """把导入项目名清理为安全目录名。"""
    safe_name = str(name or "imported_project").strip().replace(" ", "_").lower()
    safe_name = "".join(c for c in safe_name if c.isalnum() or c in ("_", "-"))
    return safe_name or "imported_project"


def _unique_project_dir(base_dir: Path, desired_name: str) -> Path:
    """返回不覆盖现有项目的唯一目录。"""
    safe_name = _safe_project_import_name(desired_name)
    candidate = base_dir / safe_name
    index = 2
    while candidate.exists():
        candidate = base_dir / f"{safe_name}_{index}"
        index += 1
    return candidate


def _build_project_export_zip(project_path: str) -> bytes:
    """把项目目录打包为 zip bytes，供加载已有项目页下载。"""
    import io
    import zipfile

    project_file = Path(project_path)
    project_dir = project_file.parent
    if not project_file.exists() or not project_dir.exists():
        raise FileNotFoundError("项目文件不存在，无法导出。")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path in project_dir.rglob("*"):
            if file_path.is_file():
                archive.write(file_path, arcname=str(Path(project_dir.name) / file_path.relative_to(project_dir)))
    return buffer.getvalue()


def _import_project_zip(uploaded_file) -> tuple[bool, str]:
    """从 zip 导入项目目录，要求压缩包内包含 knowledge_base.json。"""
    import zipfile

    settings = Settings()
    projects_dir = Path(settings.projects_dir)
    projects_dir.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(uploaded_file) as archive:
            names = [name for name in archive.namelist() if not name.endswith("/") and "__MACOSX" not in name]
            kb_candidates = [name for name in names if Path(name).name == "knowledge_base.json"]
            if not kb_candidates:
                return False, "导入失败：压缩包内没有 knowledge_base.json。"

            kb_member = kb_candidates[0]
            prefix = str(Path(kb_member).parent).replace("\\", "/")
            if prefix == ".":
                prefix = ""
            project_name = Path(prefix).name if prefix else Path(getattr(uploaded_file, "name", "imported_project")).stem
            target_dir = _unique_project_dir(projects_dir, project_name)
            target_dir.mkdir(parents=True, exist_ok=False)

            for member in names:
                normalized = member.replace("\\", "/")
                if prefix:
                    if not normalized.startswith(prefix.rstrip("/") + "/"):
                        continue
                    relative = normalized[len(prefix.rstrip("/")) + 1:]
                else:
                    relative = normalized
                if not relative or relative.startswith("../") or "/../" in relative:
                    continue
                target_path = target_dir / relative
                if not str(target_path.resolve()).startswith(str(target_dir.resolve())):
                    continue
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as src, open(target_path, "wb") as dst:
                    dst.write(src.read())

            kb_path = target_dir / "knowledge_base.json"
            if not kb_path.exists():
                return False, "导入失败：项目结构不完整，未能还原 knowledge_base.json。"
            try:
                data = json.loads(kb_path.read_text(encoding="utf-8"))
                data["project_name"] = target_dir.name
                data["project_dir"] = str(target_dir)
                data["updated_at"] = datetime.now().isoformat()
                kb_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                logger.warning("Imported project metadata could not be normalized: %s", kb_path)
            return True, f"已导入项目：{target_dir.name}"
    except zipfile.BadZipFile:
        return False, "导入失败：请上传有效的 zip 项目包。"
    except Exception as exc:
        logger.exception("Project import failed")
        return False, f"导入失败：{exc}"


def _delete_project_by_path(project_path: str) -> bool:
    """按 knowledge_base.json 路径删除项目目录。"""
    import shutil

    project_dir = Path(project_path).parent
    if not project_dir.exists() or not (project_dir / "knowledge_base.json").exists():
        return False
    shutil.rmtree(project_dir)
    if st.session_state.get("project_file") == str(project_dir / "knowledge_base.json"):
        st.session_state["project_data"] = None
        st.session_state["project_file"] = None
        st.session_state["project_dir"] = None
        st.session_state["llm_client"] = None
    return True


def list_existing_projects() -> list[dict]:
    """
    扫描 projects 目录，返回已有项目列表。

    Returns:
        [{"name": str, "path": str, "title": str}, ...]
    """
    settings = Settings()
    projects_dir = Path(settings.projects_dir)
    if not projects_dir.exists():
        return []

    projects = []
    for item in sorted(projects_dir.iterdir()):
        kb_file = item / "knowledge_base.json"
        if item.is_dir() and kb_file.exists():
            try:
                with open(kb_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                projects.append({
                    "name": item.name,
                    "path": str(kb_file),
                    "title": data.get("title", item.name),
                    "category": data.get("category", ""),
                    "updated_at": data.get("updated_at", ""),
                })
            except Exception:
                # 即使某个项目解析失败，也继续扫描其他项目
                projects.append({
                    "name": item.name,
                    "path": str(kb_file),
                    "title": item.name,
                    "category": "",
                    "updated_at": "",
                })
    return projects


# ══════════════════════════════════════════════════════════════════════
#  侧边栏 / 移动端导航
# ══════════════════════════════════════════════════════════════════════

def _nav_page_label(page: str) -> str:
    """返回用户可读导航名，避免移动端缺少“首页”。"""
    return t(NAV_PAGE_LABELS.get(page, page))


def render_mobile_navigation() -> None:
    """移动端兜底导航：即使侧边栏折叠打不开，也能切换首页/流程页。"""
    current_page = LEGACY_PAGE_ALIASES.get(st.session_state.get("current_page", "Workspace"), st.session_state.get("current_page", "Workspace"))
    default_index = MOBILE_NAV_PAGES.index(current_page) if current_page in MOBILE_NAV_PAGES else 0
    # 关键修复：移动端兜底 selectbox 是全局组件，Streamlit 会在任何按钮/表单提交后
    # 用它自己的旧 widget state 参与 rerun。之前它常停留在“首页”，导致用户在
    # 大纲页点击“章节解析”、在悬浮 AI 点“发送”后，被这里误判为切换到首页。
    # 这里用当前路由参与 key，让页面切换后重建移动端导航控件，而不是复用旧值。
    st.markdown(
        """
        <div class="hb-mobile-nav-card">
            <strong>手机快速导航</strong><br>
            <span>侧边栏打不开时，可直接在这里进入首页、资料、大纲和写章节。</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    selected_page = st.selectbox(
        "手机快速导航",
        MOBILE_NAV_PAGES,
        index=default_index,
        format_func=_nav_page_label,
        key=f"mobile_nav_select_{current_page}",
        label_visibility="collapsed",
    )
    if selected_page != current_page:
        st.session_state["current_page"] = selected_page
        st.rerun()


def render_sidebar() -> None:
    """渲染侧边栏：Logo、导航、项目信息、导出按钮"""
    with st.sidebar:
        # ── 品牌区：点击左上角隐藏入口进入全局设置 ──
        global_settings = GlobalSettingsService().load()
        site_name = str(global_settings.get("site_name") or "好编辑")
        site_subtitle = str(global_settings.get("site_subtitle") or "按顺序完成：项目 → 资料 → 大纲 → 写章节 → 审校 → 导出。")
        st.markdown(
            f"""
            <div class="hb-brand-card">
                <div class="hb-brand-logo" aria-label="好编辑图形标识">
                    <svg viewBox="0 0 64 64" role="img" aria-hidden="true" xmlns="http://www.w3.org/2000/svg">
                        <path d="M14 12.5c8.9.2 15.1 2.2 18 6.3 2.9-4.1 9.1-6.1 18-6.3 1.6 0 3 1.3 3 2.9v33.2c0 1.5-1.1 2.7-2.6 2.9-7.2.7-12.7 2.5-16.4 5.4a3.1 3.1 0 0 1-4 0c-3.7-2.9-9.2-4.7-16.4-5.4-1.5-.2-2.6-1.4-2.6-2.9V15.4c0-1.6 1.4-2.9 3-2.9Z" fill="rgba(255,250,240,.96)"/>
                        <path d="M32 19.6v31.2M18.5 23.5c5.3.5 9.4 1.9 13.5 5.1M45.5 23.5c-5.3.5-9.4 1.9-13.5 5.1M18.5 33.5c5.3.5 9.4 1.9 13.5 5.1M45.5 33.5c-5.3.5-9.4 1.9-13.5 5.1" stroke="#2f5940" stroke-width="3.4" stroke-linecap="round" fill="none"/>
                        <path d="M47.5 13.8 52 8.5l4.5 5.3-4.5 5.4-4.5-5.4Z" fill="#b9863d"/>
                    </svg>
                </div>
                <div class="hb-brand-name">{site_name}</div>
                <div class="hb-brand-subtitle">{site_subtitle}</div>
                <div class="hb-brand-pills">
                    <span class="hb-brand-pill">写书主线</span>
                    <span class="hb-brand-pill">少点按钮</span>
                    <span class="hb-brand-pill">直接生成</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        # ── 语言切换 ──
        lang_options = {"zh": "简体中文", "en": "English"}
        current_lang = get_lang()
        selected_lang = st.selectbox(
            t('ui_language'),
            options=list(lang_options.keys()),
            format_func=lambda x: lang_options[x],
            index=list(lang_options.keys()).index(current_lang),
            key="lang_select",
        )
        if selected_lang != current_lang:
            st.session_state["ui_language"] = selected_lang
            st.rerun()

        st.divider()

        # ── 导航 ──
        current_page = LEGACY_PAGE_ALIASES.get(st.session_state.get("current_page", "Workspace"), st.session_state.get("current_page", "Workspace"))

        st.markdown("<div class='hb-sidebar-nav-title'>写书流程</div><div class='hb-sidebar-nav-list'></div>", unsafe_allow_html=True)
        for nav_page in NAV_PAGES:
            nav_label = t(NAV_PAGE_LABELS.get(nav_page, nav_page))
            if st.button(
                nav_label,
                key=f"sidebar_nav_button_{nav_page}",
                use_container_width=True,
                type="primary" if nav_page == current_page else "secondary",
            ):
                st.session_state["current_page"] = nav_page
                st.rerun()

        st.divider()

        # ── 项目信息 ──
        project: Optional[ProjectKnowledgeBase] = st.session_state.get("project_data")
        if project is not None:
            st.markdown(t('current_project'))
            st.markdown(f"**{project.title}**")
            st.caption(f"{t('category')}: {project.category} | {t('genre')}: {project.genre}")
            st.caption(f"{t('language')}: {project.language}")
            profile = _resolve_project_model_profile(project)
            st.caption(f"{t('provider')}: {_profile_label(profile) if profile else project.llm_provider}")

            chapter_count = len(project.chapters) if project.chapters else 0
            source_count = len(getattr(project, "source_documents", []) or []) or len(getattr(project, "rag_documents", []) or [])
            evidence_count = len(getattr(project, "evidence_chunks", []) or [])
            st.caption(f"章节 {chapter_count} | 资料 {source_count} | 证据片段 {evidence_count}")

            if project.updated_at:
                st.caption(f"更新时间 {project.updated_at[:19]}")

            st.divider()

            # ── 项目快捷操作 ──
            if st.button("保存当前项目", use_container_width=True):
                save_project()

            st.divider()

            # ── 导出按钮 ──
            st.markdown(t('export_label'))
            export_dir = Path(st.session_state.get("project_dir", ".")) / "exports"
            export_dir.mkdir(parents=True, exist_ok=True)

            col1, col2, col3, col4 = st.columns(4)
            with col1:
                if st.button("DOCX", use_container_width=True, key="export_docx_sidebar"):
                    _export_docx(project, export_dir)
            with col2:
                if st.button("PDF", use_container_width=True, key="export_pdf_sidebar"):
                    _export_pdf(project, export_dir)
            with col3:
                if st.button("PPTX", use_container_width=True, key="export_pptx_sidebar"):
                    _export_pptx(project, export_dir)
            with col4:
                if st.button("LaTeX", use_container_width=True, key="export_latex_sidebar"):
                    _export_latex(project, export_dir)
            if st.button("Word（带格式）导出", use_container_width=True, key="export_formatted_word_sidebar"):
                _export_formatted_word(project, export_dir)

        else:
            st.info("先从「① 项目」创建或打开一个写书项目。")


def _export_pptx(project: ProjectKnowledgeBase, export_dir: Path) -> None:
    """导出 PPTX 汇报稿，并在页面上提供直接下载按钮。"""
    try:
        from libriscribe.export.pptx_export import PptxExporter
        chapters = _collect_chapters(project)
        if not chapters:
            st.warning(t('no_chapters_export'))
            return
        output_path = export_dir / f"{project.project_name}.pptx"
        exporter = PptxExporter()
        exporter.export(
            chapters=chapters,
            output_path=str(output_path),
            title=project.title,
            author=_project_author_text(project),
            genre=project.genre,
            language=project.language,
        )
        st.success(t('export_success', fmt='PPTX', path=str(output_path)))
        _render_download_button(output_path, "下载 PPTX 汇报稿", "application/vnd.openxmlformats-officedocument.presentationml.presentation")
    except ImportError:
        st.error("PPTX 导出需要安装 python-pptx：pip install python-pptx")
    except Exception as e:
        st.error(t('export_fail', fmt='PPTX', e=e))
        logger.exception("PPTX export failed")



def _export_docx(project: ProjectKnowledgeBase, export_dir: Path) -> None:
    """导出 DOCX，并在页面上提供直接下载按钮。"""
    try:
        from libriscribe.export.docx_export import DocxExporter
        chapters = _collect_chapters(project)
        if not chapters:
            st.warning(t('no_chapters_export'))
            return
        before_words = _export_word_count_from_chapters(chapters)
        _render_export_word_count_check("DOCX", before_words)
        output_path = export_dir / f"{project.project_name}.docx"
        exporter = DocxExporter()
        exporter.export(
            chapters=chapters,
            output_path=str(output_path),
            title=project.title,
            author=_project_author_text(project),
            genre=project.genre,
            language=project.language,
        )
        after_words = _docx_visible_word_count(output_path)
        _render_export_word_count_check("DOCX", before_words, after_words)
        st.success(t('export_success', fmt='DOCX', path=str(output_path)))
        _render_download_button(output_path, "下载 DOCX 书稿", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    except ImportError:
        st.error(t('export_docx_need'))
    except Exception as e:
        st.error(t('export_fail', fmt='DOCX', e=e))
        logger.exception("DOCX export failed")


def _markdown_blocks_to_paragraphs(markdown: str) -> list[str]:
    """把 Markdown 正文块转换为结构化 Word 导出脚本可消费的纯段落列表。"""
    blocks = re.split(r"\n\s*\n", str(markdown or "").strip())
    return [block.strip() for block in blocks if block.strip()]


def _markdown_content_to_structured_chapter(content: str, fallback_heading: str) -> dict:
    """将项目内 Markdown 章节正文转换为结构化 JSON 章节。

    保留中文专著四级目录层级：# 章、## 节、### 三级、#### 四级。
    旧版导出曾把所有 >=### 标题压平成 section.subsections，导致“（一）（二）”
    无法作为四级标题写入专业 Word；这里改为同时输出 level3/level4，并保留
    subsections 作为旧测试和旧调用方的兼容别名。
    """
    chapter = {"heading": fallback_heading, "content": [], "sections": []}
    current_section: Optional[dict] = None
    current_level3: Optional[dict] = None
    current_level4: Optional[dict] = None

    def _ensure_section() -> dict:
        nonlocal current_section
        if current_section is None:
            current_section = {"heading": "", "content": [], "level3": [], "subsections": []}
            chapter["sections"].append(current_section)
        return current_section

    def _ensure_level3() -> dict:
        nonlocal current_level3, current_level4
        section = _ensure_section()
        if current_level3 is None:
            current_level3 = {"heading": "", "content": [], "level4": []}
            section["level3"].append(current_level3)
            section["subsections"].append(current_level3)
        current_level4 = None
        return current_level3

    for block in _markdown_blocks_to_paragraphs(content):
        heading_match = re.match(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$", block)
        if heading_match:
            level = len(heading_match.group(1))
            heading = heading_match.group(2).strip()
            if level <= 1:
                chapter["heading"] = heading or fallback_heading
                current_section = None
                current_level3 = None
                current_level4 = None
            elif level == 2:
                current_section = {"heading": heading, "content": [], "level3": [], "subsections": []}
                chapter["sections"].append(current_section)
                current_level3 = None
                current_level4 = None
            elif level == 3:
                section = _ensure_section()
                current_level3 = {"heading": heading, "content": [], "level4": []}
                section["level3"].append(current_level3)
                section["subsections"].append(current_level3)
                current_level4 = None
            else:
                level3 = _ensure_level3()
                current_level4 = {"heading": heading, "content": []}
                level3.setdefault("level4", []).append(current_level4)
            continue

        if current_level4 is not None:
            current_level4["content"].append(block)
        elif current_level3 is not None:
            current_level3["content"].append(block)
        elif current_section is not None:
            current_section["content"].append(block)
        else:
            chapter["content"].append(block)

    return chapter


def _project_to_formatted_word_json(project: ProjectKnowledgeBase) -> dict:
    """把当前项目书稿转换为“Word（带格式）”导出脚本要求的结构化 JSON。"""
    structured = {
        "title": project.title or project.project_name,
        "author": _project_author_text(project),
        "genre": project.genre,
        "preface": [],
        "chapters": [],
        "conclusion": [],
        "global_references": [],
    }
    for item in _collect_chapters(project):
        part_key = item.get("part_key")
        content = item.get("content", "")
        if part_key == "preface":
            structured["preface"] = _markdown_blocks_to_paragraphs(content)
        elif part_key == "conclusion":
            structured["conclusion"] = _markdown_blocks_to_paragraphs(content)
        elif part_key == "references":
            structured["global_references"] = [
                paragraph for paragraph in _markdown_blocks_to_paragraphs(content)
                if not re.fullmatch(r"\s*#*\s*参考文献\s*", paragraph.strip())
            ]
        elif item.get("number") or item.get("chapter_number"):
            structured["chapters"].append(
                _markdown_content_to_structured_chapter(content, item.get("display_title") or item.get("title") or "未命名章节")
            )
    return structured


def _export_formatted_word(project: ProjectKnowledgeBase, export_dir: Path) -> None:
    """导出带封面、目录、页码、页眉页脚和固定样式的专业 Word 文档。"""
    try:
        from scripts.export_structured_json_to_docx import export_json_data_to_docx
        data = _project_to_formatted_word_json(project)
        if not data.get("chapters") and not data.get("preface") and not data.get("conclusion"):
            st.warning(t('no_chapters_export'))
            return
        chapters = _collect_chapters(project)
        before_words = _export_word_count_from_chapters(chapters)
        _render_export_word_count_check("Word（带格式）", before_words)
        output_path = export_dir / f"{project.project_name}_格式强控.docx"
        export_json_data_to_docx(data, output_path)
        after_words = _docx_visible_word_count(output_path)
        _render_export_word_count_check("Word（带格式）", before_words, after_words)
        st.success(t('export_success', fmt='Word（带格式）', path=str(output_path)))
        _render_download_button(output_path, "下载 Word（带格式）书稿", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    except ImportError:
        st.error(t('export_docx_need'))
    except Exception as e:
        st.error(t('export_fail', fmt='Word（带格式）', e=e))
        logger.exception("Formatted Word export failed")


def _export_latex(project: ProjectKnowledgeBase, export_dir: Path) -> None:
    """导出 LaTeX，并在页面上提供直接下载按钮。"""
    try:
        from libriscribe.export.latex_export import LatexExporter
        chapters = _collect_chapters(project)
        if not chapters:
            st.warning(t('no_chapters_export'))
            return
        output_path = export_dir / f"{project.project_name}.tex"
        exporter = LatexExporter()
        exporter.export(
            chapters=chapters,
            output_path=str(output_path),
            title=project.title,
            author=_project_author_text(project),
            genre=project.genre,
            language=project.language,
        )
        st.success(t('export_success', fmt='LaTeX', path=str(output_path)))
        _render_download_button(output_path, "下载 LaTeX 源文件", "application/x-tex")
    except Exception as e:
        st.error(t('export_fail', fmt='LaTeX', e=e))
        logger.exception("LaTeX export failed")


def _export_pdf(project: ProjectKnowledgeBase, export_dir: Path) -> None:
    """直接导出已编译 PDF，不再只返回 LaTeX 源文件。"""
    try:
        from libriscribe.export.pdf_export import PdfExporter
        chapters = _collect_chapters(project)
        if not chapters:
            st.warning(t('no_chapters_export'))
            return
        output_path = export_dir / f"{project.project_name}.pdf"
        exporter = PdfExporter()
        exporter.export(
            chapters=chapters,
            output_path=str(output_path),
            title=project.title,
            author=_project_author_text(project),
            genre=project.genre,
            language=project.language,
        )
        st.success(t('export_success', fmt='PDF', path=str(output_path)))
        _render_download_button(output_path, "下载 PDF 书稿", "application/pdf")
    except Exception as e:
        st.error(f"PDF 直接生成失败：{e}")
        logger.exception("PDF export failed")


def _render_download_button(file_path: Path, label: str, mime: str) -> None:
    """渲染导出文件下载按钮。"""
    try:
        with open(file_path, "rb") as f:
            st.download_button(
                label=label,
                data=f.read(),
                file_name=file_path.name,
                mime=mime,
                use_container_width=True,
            )
    except Exception as e:
        st.warning(f"导出文件已生成，但无法创建下载按钮：{e}")


def _project_author_text(project: ProjectKnowledgeBase) -> str:
    """从项目动态问题中尽量提取作者/单位信息，导出封面使用。"""
    dynamic = getattr(project, "dynamic_questions", {}) or {}
    author = ""
    unit = ""
    for key, value in dynamic.items():
        key_text = str(key).lower()
        value_text = str(value).strip()
        if not value_text:
            continue
        if not author and any(token in key_text for token in ["author", "作者", "主编", "撰写者"]):
            author = value_text
        if not unit and any(token in key_text for token in ["unit", "affiliation", "单位", "机构", "学校", "学院"]):
            unit = value_text
    parts = [p for p in [author, unit] if p]
    return " / ".join(parts)


def _count_manuscript_words(text: str) -> int:
    """统计中英混排书稿字数：中文按字计，英文/数字按词计。"""
    if not text:
        return 0
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", text)
    english_words = re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)?", text)
    return len(chinese_chars) + len(english_words)


def _plain_export_text_from_chapters(chapters: list[dict], *, include_titles: bool = False) -> str:
    """把待导出的章节列表合并为可统计文本，默认只统计正文内容。"""
    parts: list[str] = []
    for chapter in chapters or []:
        if include_titles:
            parts.append(str(chapter.get("display_title") or chapter.get("title") or ""))
        parts.append(str(chapter.get("content") or ""))
    return "\n\n".join(part for part in parts if part.strip())


def _export_word_count_from_chapters(chapters: list[dict]) -> int:
    """统计导出前正文内容字数。"""
    return _count_manuscript_words(_plain_export_text_from_chapters(chapters, include_titles=False))


def _docx_visible_word_count(output_path: Path) -> int:
    """读取已生成 DOCX 中可见段落文本字数，用于导出后完整性校验。"""
    from docx import Document

    doc = Document(str(output_path))
    visible_text = "\n".join(paragraph.text for paragraph in doc.paragraphs if paragraph.text.strip())
    return _count_manuscript_words(visible_text)


def _render_export_word_count_check(label: str, before_words: int, after_words: Optional[int] = None) -> None:
    """在导出按钮后展示导出前/导出后字数，并提示正文疑似丢失风险。"""
    if after_words is None:
        st.info(f"{label}导出前正文约 {before_words:,} 字。")
        return
    delta = after_words - before_words
    st.info(f"{label}导出前正文约 {before_words:,} 字；导出后可见文本约 {after_words:,} 字；差值 {delta:+,} 字。")
    # 导出后包含封面、目录、标题和页眉域占位，正常会略高于正文。若明显低于导出前，基本可以判定正文丢失。
    if before_words >= 100 and after_words < int(before_words * 0.95):
        st.error(f"{label}导出后字数低于导出前 95%，疑似正文丢失；请勿使用该文件作为最终稿。")
    else:
        st.success(f"{label}字数完整性校验通过。")


def _safe_int(value: Any, default: int) -> int:
    """把网页控件/会话值安全转换为整数。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _strip_manuscript_part_title(content: str, title: str) -> str:
    """移除前言/结语/参考文献正文开头自带标题，避免生成和导出重复。"""
    text = (content or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ""
    title_pattern = re.escape(title)
    patterns = [
        rf"^\s*#{{1,6}}\s*{title_pattern}\s*\n+",
        rf"^\s*{title_pattern}\s*[:：]?\s*\n+",
        rf"^\s*{title_pattern}\s*[:：]\s*",
    ]
    for pattern in patterns:
        text = re.sub(pattern, "", text, count=1)
    return text.strip()


def _target_word_count_for_part(part_key: str, options: Optional[dict[str, Any]] = None) -> int:
    """读取前言/结语目标字数；其他组成部分不做字数硬控。"""
    options = options or {}
    if part_key == "preface":
        return int(options.get("forewordWordCount") or options.get("prefaceWordCount") or 1500)
    if part_key == "conclusion":
        return int(options.get("conclusionWordCount") or 1600)
    return 0


def _manuscript_part_generation_options_from_state(part_key: str, fallback: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """从 Streamlit 当前控件状态读取生成参数，避免按钮点击时使用旧默认值。"""
    options = dict(fallback or {})
    state = getattr(st, "session_state", {})
    if part_key == "preface":
        options["forewordWordCount"] = _safe_int(state.get("manuscript_part_preface_word_count") or options.get("forewordWordCount"), 1500)
    elif part_key == "conclusion":
        options["conclusionWordCount"] = _safe_int(state.get("manuscript_part_conclusion_word_count") or options.get("conclusionWordCount"), 1600)
    elif part_key == "references":
        options["refStartYear"] = _safe_int(state.get("manuscript_part_ref_start_year") or options.get("refStartYear"), 2019)
        options["refEndYear"] = _safe_int(state.get("manuscript_part_ref_end_year") or options.get("refEndYear"), 2026)
        options["refCount"] = max(15, min(35, _safe_int(state.get("manuscript_part_ref_count") or options.get("refCount"), 30)))
        options["languageDistribution"] = state.get("manuscript_part_ref_language_distribution") or options.get("languageDistribution") or "以中文文献为主，可含少量权威英文文献"
        options["citationStyle"] = state.get("manuscript_part_ref_citation_style") or options.get("citationStyle") or "GB/T 7714-2015"
    return options


def _truncate_manuscript_part_to_max_words(content: str, max_words: int) -> str:
    """按内部字数统计硬截断超长前言/结语，优先在句末收束。"""
    text = (content or "").strip()
    if not text or max_words <= 0 or _count_manuscript_words(text) <= max_words:
        return text
    result: list[str] = []
    count = 0
    i = 0
    while i < len(text) and count < max_words:
        char = text[i]
        if re.match(r"[\u4e00-\u9fff]", char):
            count += 1
            result.append(char)
            i += 1
            continue
        word_match = re.match(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)?", text[i:])
        if word_match:
            token = word_match.group(0)
            count += 1
            if count <= max_words:
                result.append(token)
            i += len(token)
            continue
        result.append(char)
        i += 1
    truncated = "".join(result).strip()
    sentence_end = max(truncated.rfind(mark) for mark in "。！？；.!?;")
    if sentence_end >= 0 and sentence_end >= len(truncated) * 0.72:
        truncated = truncated[:sentence_end + 1].strip()
    if truncated and truncated[-1] not in "。！？.!?":
        truncated = truncated.rstrip("，,；;、：:") + "。"
    return truncated


def _sanitize_generated_manuscript_part(part_key: str, content: str) -> str:
    """清理 AI 生成的专著组成部分：去自检字数报告；参考文献保留规定标题。"""
    cleaned = _sanitize_export_manuscript_content(content)
    if part_key == "preface":
        cleaned = _strip_manuscript_part_title(cleaned, "前言")
    elif part_key == "conclusion":
        cleaned = _strip_manuscript_part_title(cleaned, "结语")
    elif part_key == "references":
        stripped = _strip_manuscript_part_title(cleaned, "参考文献")
        cleaned = "参考文献\n\n" + stripped if stripped else "参考文献"
    cleaned = re.sub(r"【\s*实际字数\s*[：:]\s*\d+\s*】", "", cleaned)
    cleaned = re.sub(r"^\s*实际字数\s*[：:]\s*\d+\s*$", "", cleaned, flags=re.MULTILINE)
    return cleaned.strip()


MANUSCRIPT_PARTS = {
    "preface": {
        "kind": "front_matter",
        "title": "前言",
        "file": "front_matter_preface.md",
        "description": "说明本书写作缘起、研究背景、核心问题、内容安排与阅读对象，不写成第一章导论。",
    },
    "conclusion": {
        "kind": "back_matter",
        "title": "结语",
        "file": "back_matter_conclusion.md",
        "description": "总结全书核心观点、理论价值、实践启示与研究展望，不重复输出章节目录。",
    },
    "references": {
        "kind": "back_matter",
        "title": "参考文献",
        "file": "back_matter_references.md",
        "description": "整理全书参考文献，只使用项目已有 citation 记录、资料库来源或用户已输入文献，不编造 DOI、作者、期刊和年份。",
    },
}


def _manuscript_part_path(project: ProjectKnowledgeBase, part_key: str) -> Optional[Path]:
    meta = MANUSCRIPT_PARTS.get(part_key)
    if not meta or not project.project_dir:
        return None
    return Path(project.project_dir) / str(meta["file"])


def _read_manuscript_part(project: ProjectKnowledgeBase, part_key: str) -> str:
    path = _manuscript_part_path(project, part_key)
    if not path or not path.exists():
        return ""
    try:
        from libriscribe.utils.file_utils import read_markdown_file
        return read_markdown_file(str(path)) or ""
    except Exception:
        logger.exception("Failed to read manuscript part: %s", part_key)
        return ""


def _write_manuscript_part(project: ProjectKnowledgeBase, part_key: str, content: str) -> None:
    path = _manuscript_part_path(project, part_key)
    if not path:
        raise ValueError("当前项目目录不可用，无法保存专著组成部分。")
    from libriscribe.utils.file_utils import write_markdown_file
    write_markdown_file(str(path), content.strip())


def _manuscript_part_entry(project: ProjectKnowledgeBase, part_key: str) -> Optional[dict]:
    meta = MANUSCRIPT_PARTS.get(part_key)
    content = _read_manuscript_part(project, part_key)
    if not meta or not content.strip():
        return None
    return {
        "kind": meta["kind"],
        "part_key": part_key,
        "title": meta["title"],
        "display_title": meta["title"],
        "content": _sanitize_generated_manuscript_part(part_key, content),
    }


def _strip_export_chapter_heading(content: str, chapter_num: int, title: str) -> str:
    """移除章节正文开头自带的一级章标题，避免导出器再加章标题后重复。"""
    return strip_leading_chapter_heading(content, chapter_num, title)


def _sanitize_export_manuscript_content(content: str) -> str:
    """导出前清理评分、自检、过程说明等非正文信息。"""
    if not content:
        return ""
    lines = str(content).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cleaned: list[str] = []
    skip_heading_block = False
    banned_heading_re = re.compile(r"^\s{0,3}#{1,6}\s*.*(?:评分|AI\s*评分|自检|质量自检|评审|审核结果|过程记录|生成说明|元数据).*$", re.IGNORECASE)
    next_heading_re = re.compile(r"^\s{0,3}#{1,6}\s+")
    banned_line_re = re.compile(
        r"(?:^\s*(?:AI\s*)?评分\s*[：:]|^\s*得分\s*[：:]|^\s*总分\s*[：:]|^\s*本章实际字数\s*[：:]|目标字数\s*[：:].*偏差|质量自检|自检评分|评分表|评审结果|审核结果|过程元数据|生成过程)",
        re.IGNORECASE,
    )
    score_table_re = re.compile(r"^\s*\|.*(?:评分|得分|分值|扣分|评价|自检).*[|｜]\s*$", re.IGNORECASE)
    table_sep_re = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")

    for line in lines:
        stripped = line.strip()
        if banned_heading_re.match(line):
            skip_heading_block = True
            continue
        if skip_heading_block:
            if next_heading_re.match(line) and not banned_heading_re.match(line):
                skip_heading_block = False
            else:
                continue
        if banned_line_re.search(stripped):
            continue
        if score_table_re.match(line) or table_sep_re.match(line) and cleaned and score_table_re.match(cleaned[-1]):
            continue
        cleaned.append(line)

    text = "\n".join(cleaned)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _ensure_export_academic_back_matter(content: str, chapter_num: int, chapter) -> str:
    """导出兜底仅补齐本章小结；不把字数偏差、评分等过程信息写进最终正文。"""
    text = (content or "").strip()
    if "本章小结" not in text:
        title = getattr(chapter, "title", "本章主题") or "本章主题"
        summary = (
            "## 本章小结\n\n"
            f"本章围绕{title}展开论述，按当前章节目录完成了核心概念、关键问题和相关分析的梳理。"
            "本章小结仅概括本章内容，不预告后续章节，不补造全书性参考文献或术语附录。"
        )
        text = text.rstrip() + "\n\n" + summary
    return text.strip()


def _collect_chapters(project: ProjectKnowledgeBase) -> list[dict]:
    """从项目目录收集完整书稿（供导出使用）。

    顺序固定为：前言（如已生成）→ 正文章节 → 结语（如已生成）→ 参考文献（如已生成）。
    正文章节优先读取 AI 生成的 `chapter_{n}.md` 完整正文；导出前统一清理重复章标题，
    并同时提供 `number` / `chapter_number` 字段，避免导出器回退成“第0章”。
    """
    chapters = []
    preface = _manuscript_part_entry(project, "preface")
    if preface:
        chapters.append(preface)
    project_dir = Path(project.project_dir) if project.project_dir else None
    for ch_num in sorted(project.chapters.keys()):
        if not isinstance(ch_num, int) or ch_num < 1:
            continue
        ch = project.chapters[ch_num]
        content = ""
        chapter_file = project_dir / f"chapter_{ch_num}.md" if project_dir else None
        if chapter_file and chapter_file.exists():
            from libriscribe.utils.file_utils import read_markdown_file
            content = read_markdown_file(str(chapter_file)) or ""
        elif ch.summary:
            content = ch.summary
        elif getattr(ch, "sections", None):
            outline_lines = []
            for sec in ch.sections:
                level = max(1, min(getattr(sec, "level", 1), 3))
                heading = "#" * (level + 1)
                display_title = _format_outline_section_label(sec.section_number, sec.title)
                outline_lines.append(f"{heading} {display_title}\n\n{getattr(sec, 'summary', '') or ''}")
            content = "\n\n".join(outline_lines)

        if content.strip():
            raw_title = ch.title or f"Chapter {ch_num}"
            normalized_content = _sanitize_export_manuscript_content(content)
            normalized_content = _strip_export_chapter_heading(normalized_content, ch_num, raw_title)
            normalized_content = _ensure_export_academic_back_matter(normalized_content, ch_num, ch)
            chapters.append({
                "number": ch_num,
                "chapter_number": ch_num,
                "title": raw_title,
                "display_title": _format_chapter_label(ch_num, raw_title),
                "content": normalized_content,
            })
    for part_key in ("conclusion", "references"):
        part = _manuscript_part_entry(project, part_key)
        if part:
            chapters.append(part)
    return chapters


# ══════════════════════════════════════════════════════════════════════
#  页面路由
# ══════════════════════════════════════════════════════════════════════

def render_dashboard() -> None:
    """渲染 Dashboard 页面：项目加载/创建"""
    st.markdown(
        f"""
        <div class="hb-hero">
            <div class="hb-hero-badge">商业化自动写作工作台 · 好编辑</div>
            <h1>{t('dashboard_title')}</h1>
            <p>{t('dashboard_welcome')} 从选题、大纲、资料库、章节生成、审校到 DOCX/PDF 导出，形成可持续运营的专著生产流水线。</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    project: Optional[ProjectKnowledgeBase] = st.session_state.get("project_data")

    if project is not None:
        # ── 已加载项目：显示概览 ──
        _render_project_overview(project)
    else:
        # ── 未加载项目：创建或加载 ──
        tab_create, tab_load = st.tabs([t('tab_create'), t('tab_load')])

        with tab_create:
            _render_create_project_form()

        with tab_load:
            _render_load_project_section()


def _render_project_overview(project: ProjectKnowledgeBase) -> None:
    """渲染已加载项目的概览"""
    profile = _resolve_project_model_profile(project)
    st.markdown(
        f"""
        <div class="hb-action-grid">
            <div class="hb-action-card"><strong>当前项目</strong><span>{project.title}</span></div>
            <div class="hb-action-card"><strong>写作模型</strong><span>{_profile_label(profile) if profile else project.llm_provider}</span></div>
            <div class="hb-action-card"><strong>运营流程</strong><span>大纲规划 → 资料增强 → 批量生成 → 审校导出</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(f"<div class='hb-section-title'>{t('project_overview', title=project.title)}</div>", unsafe_allow_html=True)

    # 基本信息卡片
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric(t('metric_chapters'), len(project.chapters))
    with col2:
        st.metric(t('metric_characters'), len(project.characters))
    with col3:
        st.metric(t('metric_terminology'), len(project.terminology))
    with col4:
        st.metric(t('metric_citations'), len(project.citations))

    st.divider()

    # 项目描述
    if project.description:
        st.markdown(t('project_desc'))
        st.write(project.description)

    # 大纲预览
    if project.outline:
        with st.expander(t('outline_preview'), expanded=False):
            st.markdown(project.outline)

    # 章节列表
    if project.chapters:
        st.markdown(t('chapter_list'))
        for ch_num in sorted(project.chapters.keys()):
            ch = project.chapters[ch_num]
            title = ch.title or _format_chapter_label(ch_num)
            summary_preview = (ch.summary[:100] + "...") if ch.summary and len(ch.summary) > 100 else (ch.summary or t('no_summary'))
            with st.expander(f"{_format_chapter_label(ch_num)} — {title}"):
                st.write(summary_preview)
                if ch.scenes:
                    st.caption(t('scene_count', n=len(ch.scenes)))

    # 角色列表
    if project.characters:
        st.markdown(t('character_list'))
        for name, char in project.characters.items():
            with st.expander(f"角色：{name}"):
                if char.role:
                    st.write(f"**{t('role')}:** {char.role}")
                if char.personality_traits:
                    st.write(f"**{t('personality')}:** {char.personality_traits}")
                if char.background:
                    st.write(f"**{t('background')}:** {char.background}")

    # 操作按钮
    st.divider()
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button(t('switch_project'), use_container_width=True):
            st.session_state["project_data"] = None
            st.session_state["project_file"] = None
            st.session_state["project_dir"] = None
            st.session_state["llm_client"] = None
            st.rerun()
    with col_b:
        if st.button(t('close_project'), use_container_width=True):
            st.session_state["project_data"] = None
            st.session_state["project_file"] = None
            st.session_state["project_dir"] = None
            st.session_state["llm_client"] = None
            st.rerun()


def _render_create_project_form() -> None:
    """渲染创建新项目表单"""
    st.markdown(t('create_form_hint'))

    with st.form("create_project_form", clear_on_submit=False):
        project_name = st.text_input(
            t('project_name_label'),
            placeholder=t('project_name_placeholder'),
        )
        title = st.text_input(
            t('book_title_label'),
            placeholder=t('book_title_placeholder'),
        )
        col1, col2 = st.columns(2)
        with col1:
            category = st.selectbox(t('category_label'), CATEGORIES, index=0)
        with col2:
            genre = st.text_input(t('genre_label'), placeholder=t('genre_placeholder'))

        col3, col4 = st.columns(2)
        with col3:
            language = st.selectbox(
                t('language_label'),
                PROJECT_LANGUAGES,
                index=0,
            )
        with col4:
            ready_profiles = _available_model_profiles(require_ready=True)
            if ready_profiles:
                selected_profile_id = st.selectbox(
                    "写作模型",
                    [p["id"] for p in ready_profiles],
                    format_func=lambda pid: _profile_label(next((p for p in ready_profiles if p["id"] == pid), {})),
                )
            else:
                selected_profile_id = ""
                st.warning("还没有可用模型。请先到「模型配置」页面填写密钥、模型并启用。")

        submitted = st.form_submit_button(t('create_btn'), use_container_width=True)

        if submitted:
            if not project_name.strip():
                st.error(t('name_empty_error'))
            elif not title.strip():
                st.error(t('title_empty_error'))
            elif not genre.strip():
                st.error(t('genre_empty_error'))
            elif not selected_profile_id:
                st.error("请先在「模型配置」页面配置并启用一个写作模型。")
            else:
                # 清理项目名称（只保留安全字符）
                safe_name = project_name.strip().replace(" ", "_").lower()
                safe_name = "".join(c for c in safe_name if c.isalnum() or c in ("_", "-"))
                create_new_project(
                    project_name=safe_name,
                    title=title.strip(),
                    category=category,
                    genre=genre.strip(),
                    language=language,
                    model_profile_id=selected_profile_id,
                )
                st.rerun()


def _render_load_project_section() -> None:
    """渲染加载已有项目区域"""
    projects = list_existing_projects()

    st.markdown("### 导入项目")
    imported_project_zip = st.file_uploader("上传项目 zip 包", type=["zip"], key="project_import_zip")
    if imported_project_zip and st.button("导入项目", key="import_project_zip_btn", use_container_width=True):
        ok, message = _import_project_zip(imported_project_zip)
        if ok:
            st.success(message)
            st.rerun()
        else:
            st.error(message)

    if not projects:
        st.info(t('no_projects_found'))
        return

    st.markdown(t('found_projects', n=len(projects)))

    for proj in projects:
        with st.container(border=True):
            col1, col2, col3, col4, col5 = st.columns([3, 2, 1, 1, 1.4])
            with col1:
                st.markdown(f"**📖 {proj['title']}**")
                st.caption(f"`{proj['name']}`")
            with col2:
                if proj["category"]:
                    st.caption(f"{t('category')}: {proj['category']}")
                if proj["updated_at"]:
                    st.caption(f"{proj['updated_at'][:19]}")
            with col3:
                if st.button(t('load_btn'), key=f"load_{proj['name']}", use_container_width=True):
                    load_project(proj["path"])
                    st.rerun()
            with col4:
                try:
                    export_bytes = _build_project_export_zip(proj["path"])
                    st.download_button(
                        "导出",
                        data=export_bytes,
                        file_name=f"{proj['name']}.zip",
                        mime="application/zip",
                        key=f"export_project_{proj['name']}",
                        use_container_width=True,
                    )
                except Exception as exc:
                    st.caption(f"导出不可用：{exc}")
            with col5:
                delete_password = st.text_input(
                    "删除密码",
                    type="password",
                    key=f"delete_project_password_{proj['name']}",
                    placeholder="密码",
                    label_visibility="collapsed",
                )
                if st.button("删除", key=f"delete_project_{proj['name']}", use_container_width=True):
                    if delete_password != PROJECT_DELETE_PASSWORD:
                        st.error("删除密码错误。")
                    elif _delete_project_by_path(proj["path"]):
                        st.success(f"已删除项目：{proj['title']}")
                        st.rerun()
                    else:
                        st.error("删除失败：项目目录不存在或结构异常。")

    st.divider()

    # 手动输入路径加载
    st.markdown(t('manual_load'))
    manual_path = st.text_input(
        t('manual_path_label'),
        placeholder=t('manual_path_placeholder'),
        key="manual_project_path",
    )
    if st.button(t('load_manual_btn'), key="load_manual"):
        if manual_path.strip():
            load_project(manual_path.strip())
            st.rerun()
        else:
            st.warning(t('path_empty_warning'))


def render_outline_page() -> None:
    """渲染大纲管理页面"""
    st.title(t('outline_title'))

    project: Optional[ProjectKnowledgeBase] = st.session_state.get("project_data")
    if project is None:
        st.warning(t('load_project_first'))
        return

    st.info("大纲生成已升级为中文专著策划流程：先做全书价值定位与章际逻辑，再按“章—节—一、—（一）—写作思路”生成目录。支持全书生成、分章生成、单章生成和单章修改。")
    with st.container(border=True):
        col_mode, col_preface = st.columns([2, 1])
        with col_mode:
            outline_mode = st.radio(
                "AI 大纲生成模式",
                ["全文一次生成", "分章生成（更稳）", "单章生成/修改", "二次改进现有大纲"],
                horizontal=True,
                key="outline_generation_mode",
            )
        with col_preface:
            include_preface = st.checkbox(
                "包含序言（全书逻辑起点与最终归宿）",
                value=True,
                key="outline_include_preface",
            )

        inferred_chapters = _infer_outline_chapter_count(project)
        stored_chapters = _safe_outline_chapter_count(getattr(project, "num_chapters", 0), default=inferred_chapters)
        count_mode_options = ["AI 根据主题和资料自动建议", "我指定章数"]
        default_count_mode = count_mode_options[1] if stored_chapters != inferred_chapters and stored_chapters > 1 else count_mode_options[0]
        col_count_mode, col_count_value = st.columns([2, 1])
        with col_count_mode:
            chapter_count_mode = st.radio(
                "全书章数规划",
                count_mode_options,
                index=count_mode_options.index(st.session_state.get("outline_chapter_count_mode", default_count_mode)),
                horizontal=True,
                key="outline_chapter_count_mode",
                help="自动建议会综合书名、项目描述、篇幅、已上传资料、证据片段和现有大纲；也可以切到手动指定章数。",
            )
        with col_count_value:
            manual_chapter_count = st.number_input(
                "目标章数",
                min_value=3,
                max_value=24,
                value=int(stored_chapters if chapter_count_mode == "我指定章数" else inferred_chapters),
                step=1,
                key="outline_manual_chapter_count",
            )
        selected_chapter_count = int(manual_chapter_count if chapter_count_mode == "我指定章数" else inferred_chapters)
        if chapter_count_mode == "AI 根据主题和资料自动建议":
            st.caption(f"已根据当前主题、篇幅与资料量自动建议：{selected_chapter_count} 章。生成前会写入项目，分章生成将按该章数逐章展开。")
        else:
            st.caption(f"已指定全书分为 {selected_chapter_count} 章。AI 将围绕这个章数重排全书结构。")

        improve_instruction = ""
        single_chapter_number = 1
        if outline_mode == "二次改进现有大纲":
            improve_instruction = st.text_area(
                "二次改进要求",
                value="补齐全书章节，强化章际递进、术语一致、字数均衡、研究逻辑闭环；必要时增加序言。",
                height=90,
                key="outline_improve_instruction",
            )
        elif outline_mode == "单章生成/修改":
            chapter_options = sorted(project.chapters.keys()) or list(range(1, selected_chapter_count + 1))
            single_chapter_number = st.selectbox(
                "选择要单独生成或修改的章节",
                chapter_options,
                format_func=lambda n: f"第{_cn_chapter_num(int(n))}章 — {project.chapters.get(int(n)).title if int(n) in project.chapters else '新章节'}",
                key="outline_single_chapter_number",
            )
            improve_instruction = st.text_area(
                "本章生成/修改要求",
                value="严格按全书上下文定位本章职责，补充节、一、（一）和写作思路，避免与其他章节重复。",
                height=90,
                key="outline_single_chapter_instruction",
            )
        if st.button("AI 生成/改进大纲（自动创建章节目录）", type="primary", use_container_width=True, key="outline_primary_ai_generate"):
            project.num_chapters = selected_chapter_count
            project.num_chapters_str = f"{selected_chapter_count}章（{'自动建议' if chapter_count_mode == 'AI 根据主题和资料自动建议' else '用户指定'}）"
            st.session_state["project_data"] = project
            save_project()
            if outline_mode == "二次改进现有大纲":
                count_instruction = f"请将全书调整为 {selected_chapter_count} 章，保持专著逻辑闭环，不要只保留第一章。"
                merged_instruction = f"{count_instruction}\n{improve_instruction}" if improve_instruction else count_instruction
                _improve_outline_with_ai(project, merged_instruction, include_preface=include_preface)
            elif outline_mode == "单章生成/修改":
                _generate_single_chapter_outline_with_ai(project, int(single_chapter_number), improve_instruction, include_preface=include_preface)
            else:
                mode = "chapter_by_chapter" if outline_mode == "分章生成（更稳）" else "full"
                _generate_outline_with_ai(project, mode=mode, include_preface=include_preface)

    st.divider()

    # 显示当前大纲
    if project.outline:
        st.markdown(t('current_outline'))
        st.markdown(project.outline)
        st.divider()

    # 编辑大纲
    st.markdown(t('edit_outline'))
    new_outline = st.text_area(
        t('outline_content_label'),
        value=project.outline or "",
        height=400,
        placeholder=t('outline_placeholder'),
    )

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if st.button(t('save_outline'), use_container_width=True):
            project.outline = new_outline
            st.session_state["project_data"] = project
            st.session_state["current_page"] = "Outline"
            save_project()
            st.rerun()
    with col2:
        if st.button("按当前大纲重建章节", type="primary", use_container_width=True, key="outline_reparse_current"):
            source_outline = (new_outline or project.outline or "").strip()
            if source_outline:
                st.session_state["current_page"] = "Outline"
                _parse_outline_text(project, source_outline, replace_all=True)
            else:
                st.warning(t('parse_outline_fail'))
    with col3:
        if st.button(t('ai_generate_outline'), use_container_width=True, key="outline_edit_ai_generate"):
            st.session_state["current_page"] = "Outline"
            _generate_outline_with_ai(project, mode="chapter_by_chapter", include_preface=True)
    with col4:
        if st.button(t('paste_outline_hint'), use_container_width=True):
            st.session_state["show_paste_outline"] = True
            st.session_state["current_page"] = "Outline"

    # 粘贴大纲解析
    if st.session_state.get("show_paste_outline"):
        st.divider()
        st.markdown(f"### {t('paste_outline_hint')}")
        pasted_text = st.text_area(
            t('paste_outline_hint'),
            height=300,
            placeholder=t('paste_outline_placeholder'),
            key="pasted_outline_text",
        )
        col_parse, col_cancel = st.columns(2)
        with col_parse:
            if st.button(t('parse_outline_btn'), use_container_width=True):
                if pasted_text and pasted_text.strip():
                    st.session_state["current_page"] = "Outline"
                    _parse_outline_text(project, pasted_text)
                else:
                    st.warning(t('parse_outline_fail'))
        with col_cancel:
            if st.button(t('cancel'), use_container_width=True):
                st.session_state["show_paste_outline"] = False
                st.rerun()

    # 章节管理
    st.divider()
    st.markdown(t('chapter_management'))

    # 一键粘贴解析（始终可见）
    with st.expander(t('paste_outline_hint'), expanded=not project.chapters):
        if not project.chapters:
            st.info(t('no_chapters_hint'))
        else:
            st.caption("重新粘贴将覆盖现有章节数据。")
        paste_text = st.text_area(
            t('paste_outline_hint'),
            height=200,
            placeholder=t('paste_outline_placeholder'),
            key="chapter_paste_text",
        )
        parse_cols = st.columns(2)
        with parse_cols[0]:
            if st.button(t('parse_outline_btn'), key="parse_chapters_btn", use_container_width=True):
                if paste_text and paste_text.strip():
                    st.session_state["current_page"] = "Outline"
                    _parse_outline_text(project, paste_text)
                else:
                    st.warning(t('parse_outline_fail'))
        with parse_cols[1]:
            if st.button("用当前大纲重建章节", key="parse_saved_outline_btn", use_container_width=True):
                source_outline = (project.outline or new_outline or "").strip()
                if source_outline:
                    st.session_state["current_page"] = "Outline"
                    _parse_outline_text(project, source_outline, replace_all=True)
                else:
                    st.warning(t('parse_outline_fail'))

    parse_feedback = st.session_state.pop("outline_parse_feedback", None)
    if parse_feedback:
        chapters = parse_feedback.get("chapters", [])
        st.success(f"已按当前大纲重建 {parse_feedback.get('count', 0)} 章。当前章节：" + "；".join(chapters[:12]))
        if len(chapters) > 12:
            st.caption(f"其余 {len(chapters) - 12} 章已省略显示，可在下方章节列表查看。")

    if project.chapters:
        danger_cols = st.columns([2, 1])
        with danger_cols[0]:
            st.caption("如果重构结果不符合预期，可删除单章，或清空后重新按当前大纲解析。")
        with danger_cols[1]:
            if st.button("清空全部章节", key="delete_all_chapters", use_container_width=True):
                project.chapters = {}
                st.session_state["project_data"] = project
                save_project()
                st.success("已清空全部章节。可继续点击“用当前大纲重建章节”。")
                st.rerun()

    def _fill_missing_section_words_for_display(sections):
        """为旧会话/旧项目兜底补齐小节目标字数，避免网页控件继续显示 0。"""
        if not sections:
            return False
        changed = False
        section_numbers = {str(sec.section_number) for sec in sections if getattr(sec, "section_number", "")}

        def _is_descendant(child_number: str, parent_number: str) -> bool:
            return child_number != parent_number and child_number.startswith(parent_number + ".")

        def _is_leaf(section_number: str) -> bool:
            return not any(_is_descendant(other_number, section_number) for other_number in section_numbers)

        def _direct_children(parent_number):
            expected_level = parent_number.count(".") + 1
            return [
                sec
                for sec in sections
                if _is_descendant(str(sec.section_number), parent_number)
                and str(sec.section_number).count(".") == expected_level
            ]

        def _distribute(parent_words, children):
            nonlocal changed
            missing = [sec for sec in children if int(getattr(sec, "word_count", 0) or 0) <= 0]
            if not missing:
                return
            explicit = sum(int(getattr(sec, "word_count", 0) or 0) for sec in children if int(getattr(sec, "word_count", 0) or 0) > 0)
            remaining = parent_words - explicit
            if remaining <= 0:
                remaining = parent_words
            targets = _semantic_word_targets([getattr(sec, "title", "") or getattr(sec, "summary", "") for sec in missing], remaining)
            for child, target in zip(missing, targets):
                child.word_count = int(target)
                changed = True

        parents = sorted(
            [sec for sec in sections if int(getattr(sec, "word_count", 0) or 0) > 0 and not _is_leaf(str(sec.section_number))],
            key=lambda sec: str(sec.section_number).count("."),
        )
        for parent in parents:
            children = _direct_children(str(parent.section_number))
            if children:
                _distribute(int(getattr(parent, "word_count", 0) or 0), children)
        return changed

    # 章节列表
    if project.chapters:
        filled_words = False
        for ch in project.chapters.values():
            filled_words = _fill_missing_section_words_for_display(getattr(ch, "sections", []) or []) or filled_words
        if filled_words:
            st.session_state["project_data"] = project
            st.session_state["outline_parse_version"] = int(st.session_state.get("outline_parse_version", 0) or 0) + 1
            save_project()
        outline_form_version = int(st.session_state.get("outline_parse_version", 0) or 0)
        for ch_num in sorted(project.chapters.keys()):
            ch = project.chapters[ch_num]
            # 显示字数信息（防御性访问，兼容旧数据）
            wc = getattr(ch, 'word_count', 0)
            secs = getattr(ch, 'sections', [])
            wc_info = f" | {wc}字" if wc > 0 else " | 未设置字数"
            sec_info = f" | {len(secs)}小节" if secs else ""
            with st.expander(f"{_format_chapter_label(ch_num)} — {ch.title or t('unnamed')}{wc_info}{sec_info}"):
                new_title = st.text_input(
                    t('chapter_title_label'),
                    value=ch.title,
                    key=f"ch_title_{ch_num}",
                )
                new_summary = st.text_area(
                    t('chapter_summary_label'),
                    value=ch.summary or "",
                    key=f"ch_summary_{ch_num}",
                    height=100,
                )
                # 小节管理：只展示大纲原始中文层级，内部 1.1/1.1.1 仅作为稳定 ID 使用；支持直接修改标题、写作目标与字数。
                edited_sections = []
                if secs:
                    st.markdown("**小节管理：**")
                    st.caption("可直接修改每个小节标题、写作目标/写作思路和目标字数；保存本章后生效。")
                    for sec_idx, sec in enumerate(secs):
                        indent = "　" * (getattr(sec, 'level', 1) - 1)
                        display_label = _format_outline_section_label(sec.section_number, sec.title)
                        with st.expander(f"{indent}{display_label}", expanded=False):
                            sec_title = st.text_input(
                                "小节标题",
                                value=getattr(sec, "title", "") or "",
                                key=f"outline_sec_title_{outline_form_version}_{ch_num}_{sec.section_number}_{sec_idx}",
                            )
                            sec_summary = st.text_area(
                                "写作目标 / 写作思路（仅提交给 AI，不直接作为正文预览）",
                                value=getattr(sec, "summary", "") or "",
                                height=90,
                                key=f"outline_sec_summary_{outline_form_version}_{ch_num}_{sec.section_number}_{sec_idx}",
                            )
                            sec_wc = st.number_input(
                                "目标字数",
                                min_value=0,
                                max_value=200000,
                                value=int(getattr(sec, "word_count", 0) or 0),
                                step=100,
                                key=f"outline_sec_wc_{outline_form_version}_{ch_num}_{sec.section_number}_{sec_idx}",
                            )
                            sec.title = sec_title.strip() or getattr(sec, "title", "")
                            sec.summary = sec_summary.strip()
                            sec.word_count = int(sec_wc or 0)
                        edited_sections.append(sec)
                action_cols = st.columns([1, 1])
                with action_cols[0]:
                    if st.button(t('update'), key=f"update_ch_{ch_num}", use_container_width=True):
                        ch.title = new_title
                        ch.summary = new_summary
                        if edited_sections:
                            ch.sections = edited_sections
                        project.chapters[ch_num] = ch
                        st.session_state["project_data"] = project
                        save_project()
                        st.success(f"{_format_chapter_label(ch_num)} {t('success')}")
                with action_cols[1]:
                    confirm_delete = st.checkbox("确认删除本章", key=f"confirm_delete_ch_{ch_num}")
                    if st.button("删除本章", key=f"delete_ch_{ch_num}", use_container_width=True, disabled=not confirm_delete):
                        project.chapters.pop(ch_num, None)
                        if project.project_dir:
                            chapter_path = Path(project.project_dir) / f"chapter_{ch_num}.md"
                            try:
                                if chapter_path.exists():
                                    chapter_path.unlink()
                            except Exception as e:
                                st.warning(f"章节记录已删除，但正文文件删除失败：{e}")
                        st.session_state["project_data"] = project
                        save_project()
                        st.success(f"已删除{_format_chapter_label(ch_num)}。")
                        st.rerun()

    # 添加新章节
    st.divider()
    with st.form("add_chapter_form"):
        new_ch_num = st.number_input(t('chapter_number'), min_value=1, value=len(project.chapters) + 1, step=1)
        new_ch_title = st.text_input(t('chapter_title_label'), placeholder=t('chapter_title_placeholder'))
        if st.form_submit_button(t('add_chapter')):
            from libriscribe.knowledge_base import Chapter
            project.chapters[int(new_ch_num)] = Chapter(
                chapter_number=int(new_ch_num),
                title=new_ch_title,
            )
            st.session_state["project_data"] = project
            save_project()
            st.rerun()


def _semantic_outline_weight(text: str, position: int = 0, total: int = 1) -> float:
    """根据标题与写作思路估算强对比语义权重，避免父级字数机械平均分配。"""
    raw = str(text or "").strip()
    if not raw:
        return 1.0

    normalized = re.sub(r"\s+", "", raw)
    normalized = re.sub(r"[（(]\s*(?:约\s*)?(?:总字数\s*)?\d+\s*字?\s*[）)]", "", normalized)
    normalized = re.sub(r"写作思路[：:]", "", normalized)
    length_weight = min(0.72, max(0.0, len(normalized) - 4) / 28)
    score = 1.0 + length_weight

    # 字数分配要让“机制/治理/路径/风险/实证”等正文承重单元明显高于概念性铺垫。
    high_value_keywords = {
        "机制": 0.42,
        "机理": 0.42,
        "体系": 0.40,
        "模型": 0.38,
        "治理": 0.38,
        "评价": 0.36,
        "评估": 0.34,
        "路径": 0.34,
        "策略": 0.34,
        "方案": 0.32,
        "实施": 0.32,
        "应用": 0.30,
        "实践": 0.30,
        "转化": 0.30,
        "数据": 0.30,
        "数字": 0.28,
        "实证": 0.34,
        "案例": 0.26,
        "问题": 0.30,
        "困境": 0.30,
        "瓶颈": 0.30,
        "原因": 0.26,
        "影响": 0.28,
        "协同": 0.28,
        "风险": 0.32,
        "安全": 0.28,
        "质量": 0.26,
        "创新": 0.24,
        "演进": 0.20,
        "比较": 0.20,
        "偏好": 0.18,
        "课外": 0.16,
    }
    light_keywords = {
        "概念": 0.18,
        "定义": 0.18,
        "概述": 0.18,
        "导论": 0.22,
        "简介": 0.22,
        "基本内涵": 0.16,
        "背景": 0.10,
        "基础": 0.10,
        "小结": 0.28,
        "结语": 0.28,
    }
    for keyword, bonus in high_value_keywords.items():
        if keyword in normalized:
            score += bonus
    for keyword, penalty in light_keywords.items():
        if keyword in normalized:
            score -= penalty

    if total > 1:
        # 仅用于同质短标题打破完全均分，不允许位置覆盖语义。
        score += min(0.04, max(0, position) * 0.012)
    return max(0.42, score)


def _semantic_word_targets(items: Sequence[str], total_words: int) -> list[int]:
    """按语义权重把 total_words 分配给若干小节，并保证整数结果总和严格守恒。"""
    count = len(items or [])
    total_words = int(total_words or 0)
    if count <= 0:
        return []
    if total_words <= 0:
        return [0 for _ in range(count)]

    base_weights = [_semantic_outline_weight(item, idx, count) for idx, item in enumerate(items)]
    # 对语义分值做非线性放大，让复杂承重小节与概念铺垫之间拉开 20%~60% 的差距。
    weights = [max(0.18, weight) ** 1.42 for weight in base_weights]
    weight_sum = sum(weights) or float(count)
    raw_targets = [total_words * weight / weight_sum for weight in weights]
    targets = [int(value) for value in raw_targets]
    remainder = total_words - sum(targets)
    if remainder > 0:
        ranked = sorted(range(count), key=lambda idx: (raw_targets[idx] - targets[idx], weights[idx]), reverse=True)
        for idx in ranked[:remainder]:
            targets[idx] += 1
    elif remainder < 0:
        ranked = sorted(range(count), key=lambda idx: (raw_targets[idx] - targets[idx], weights[idx]))
        for idx in ranked[:abs(remainder)]:
            if targets[idx] > 0:
                targets[idx] -= 1
    return targets


def _normalize_outline_text(text: str) -> str:
    """规范化 AI/粘贴大纲：把一整段输出切成可解析的章-节行。"""
    if not text:
        return ""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"^```(?:markdown|md)?\s*", "", normalized.strip(), flags=re.IGNORECASE)
    normalized = re.sub(r"\s*```$", "", normalized).strip()
    cn_nums = r"一二三四五六七八九十百千零〇两\d"
    normalized = re.sub(r"[ \t]*(#{1,6}|[-*•]+|\d+[、.)])\s*(?=第[" + cn_nums + r"]+章)", "\n", normalized)
    # 只在“章标题明显带字数/总字数”时，把同一行中的下一章切到新行；
    # 不再对正文里任意“第X章”强制断行，避免“与第二章衔接……”被误识别成新章节。
    normalized = re.sub(
        r"(?<!\n)\s+(?=(?:第[" + cn_nums + r"]+章|Chapter\s*\d+)\s*[^\n]{0,80}(?:总字数|约\s*\d+\s*字|\d+\s*字))",
        "\n",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(r"(?<!\n)\s+(?=第[" + cn_nums + r"]+节\b)", "\n", normalized)
    normalized = re.sub(r"(?<!\n)\s+(?=[" + cn_nums + r"]+[、.．]\s*)", "\n", normalized)
    normalized = re.sub(r"(?<!\n)\s+(?=[（(][" + cn_nums + r"]+[）)]\s*)", "\n", normalized)
    normalized = re.sub(r"(?<!\n)\s+(?=写作思路[：:])", "\n", normalized)
    normalized = re.sub(r"(?<!\n)\s+(?=\d+(?:\.\d+)+\s*[：:\s])", "\n", normalized)
    normalized = re.sub(r"\n\s*(?:#{1,6}|[-*•]+)\s*", "\n", normalized)
    normalized = re.sub(r"\n{2,}", "\n", normalized)
    return normalized.strip()


def _parse_outline_text(project: ProjectKnowledgeBase, text: str, *, persist: bool = True, rerun: bool = True, show_messages: bool = True, replace_all: bool = True) -> int:
    """
    解析粘贴的大纲文本，自动创建章节和子节。
    支持多级格式（不要求严格格式）：
      第一章 医疗诊断与AI概述（总字数 8000字）
      1.1 医疗诊断的现状与挑战（2000字）
      1.1.1 传统医疗诊断流程（800字）
      1.1.2 误诊率与医疗资源分布（700字）
      1.2 人工智能技术发展脉络（3000字）
      第二章 医学影像智能分析（总字数 12000字）
      2.1 影像数据特性与预处理（3000字）
    """
    import re
    from libriscribe.knowledge_base import Chapter, ChapterSection

    text = _normalize_outline_text(text)
    lines = text.strip().split("\n")
    chapters_created = 0
    if replace_all:
        project.chapters = {}
    current_ch_num = None
    current_ch_title = ""
    current_ch_word_count = 0
    current_ch_summary_parts = []
    current_ch_sections = []

    # 字数提取：匹配（约2000字）、(总字数 8000字)、（8000）等多种格式；清理时必须连同“约”和括号一起去掉，避免污染标题正文。
    word_count_pattern = re.compile(r'[（(]?\s*(?:约\s*)?(?:总字数\s*)?(\d+)\s*字?\s*[）)]?')

    def _clean_outline_title(text_part: str) -> str:
        """去掉大纲标题中的字数标注和残留括号，避免“（约”进入小节标题。"""
        cleaned = word_count_pattern.sub('', text_part).strip()
        cleaned = re.sub(r'[（(]\s*(?:约|总字数)?\s*[）)]?\s*$', '', cleaned).strip()
        cleaned = re.sub(r'\s*[（(]\s*$', '', cleaned).strip()
        return cleaned

    def _extract_word_count(text_part: str) -> int:
        """从文本中提取字数"""
        matches = word_count_pattern.findall(text_part)
        if matches:
            return int(matches[-1])  # 取最后一个数字
        return 0

    def _assign_parent_word_counts_to_leaf_sections(sections: list[ChapterSection]) -> None:
        """将带字数的父级节按标题语义权重分配给后代小节，避免机械平均。"""
        if not sections:
            return

        section_by_number = {str(sec.section_number): sec for sec in sections if getattr(sec, "section_number", "")}

        def _is_descendant(child_number: str, parent_number: str) -> bool:
            return child_number != parent_number and child_number.startswith(parent_number + ".")

        def _direct_children(parent_number: str) -> list[ChapterSection]:
            expected_level = parent_number.count(".") + 1
            return [
                sec
                for sec in sections
                if _is_descendant(str(sec.section_number), parent_number)
                and str(sec.section_number).count(".") == expected_level
            ]

        def _is_leaf(section_number: str) -> bool:
            return not any(_is_descendant(other_number, section_number) for other_number in section_by_number)

        def _distribute(parent_word_count: int, children: list[ChapterSection]) -> None:
            missing_children = [sec for sec in children if int(getattr(sec, "word_count", 0) or 0) <= 0]
            if not missing_children:
                return
            explicit_child_words = sum(
                int(getattr(sec, "word_count", 0) or 0)
                for sec in children
                if int(getattr(sec, "word_count", 0) or 0) > 0
            )
            remaining_words = parent_word_count - explicit_child_words
            if remaining_words <= 0:
                remaining_words = parent_word_count
            targets = _semantic_word_targets(
                [getattr(sec, "title", "") or getattr(sec, "summary", "") for sec in missing_children],
                remaining_words,
            )
            for child, target in zip(missing_children, targets):
                child.word_count = int(target)

        # 自上而下给直接子级补齐字数：这样“第一节”下的“一、”在大纲管理 UI 中也不再显示 0。
        parent_sections = sorted(
            [sec for sec in sections if int(getattr(sec, "word_count", 0) or 0) > 0 and not _is_leaf(str(sec.section_number))],
            key=lambda sec: str(sec.section_number).count("."),
        )
        for parent in parent_sections:
            parent_number = str(parent.section_number)
            parent_word_count = int(getattr(parent, "word_count", 0) or 0)
            direct_children = _direct_children(parent_number)
            if direct_children:
                _distribute(parent_word_count, direct_children)

        # 再处理仍然没有直接子级字数的极端结构，把父级字数兜底分给后代叶子。
        parent_sections = sorted(
            [sec for sec in sections if int(getattr(sec, "word_count", 0) or 0) > 0 and not _is_leaf(str(sec.section_number))],
            key=lambda sec: str(sec.section_number).count("."),
            reverse=True,
        )
        for parent in parent_sections:
            parent_number = str(parent.section_number)
            parent_word_count = int(getattr(parent, "word_count", 0) or 0)
            descendant_leaves = [
                sec
                for sec in sections
                if _is_descendant(str(sec.section_number), parent_number) and _is_leaf(str(sec.section_number))
            ]
            if descendant_leaves:
                _distribute(parent_word_count, descendant_leaves)

    def _flush_chapter():
        nonlocal current_ch_num, current_ch_title, current_ch_word_count
        nonlocal current_ch_summary_parts, current_ch_sections, chapters_created
        if current_ch_num is not None:
            _assign_parent_word_counts_to_leaf_sections(current_ch_sections)
            summary = "\n".join(current_ch_summary_parts)
            project.chapters[current_ch_num] = Chapter(
                chapter_number=current_ch_num,
                title=current_ch_title,
                summary=summary,
                word_count=current_ch_word_count,
                sections=current_ch_sections,
            )
            chapters_created += 1
            current_ch_summary_parts = []
            current_ch_sections = []

    # 匹配章节标题：第一章、第二章、Chapter 1 等
    # 支持"第一章智慧城市"（无分隔符）、"第一章 智慧城市"（空格）、"第一章：智慧城市"（冒号）
    ch_pattern = re.compile(
        r'^(?:第([一二三四五六七八九十百千零〇两\d]+)章|Chapter\s*(\d+))\s*[：:、.．]*\s*(.+)',
        re.IGNORECASE,
    )
    # 匹配多级小节：1.1、1.1.1、1.1.2.3 等（支持任意深度）
    section_pattern = re.compile(r'^(\d+(?:\.\d+)+)\s*[：:\s]\s*(.+)')
    cn_section_pattern = re.compile(r'^第([一二三四五六七八九十百千零〇两\d]+)节\s*[：:、.．]*\s*(.+)')
    cn_level3_pattern = re.compile(r'^([一二三四五六七八九十百千零〇两\d]+)[、.．]\s*(.+)')
    cn_level4_pattern = re.compile(r'^[（(]([一二三四五六七八九十百千零〇两\d]+)[）)]\s*(.+)')
    writing_idea_pattern = re.compile(r'^写作思路[：:]\s*(.+)')
    chapter_word_count_signal = re.compile(r'(?:总字数|约\s*\d+\s*字|\d+\s*字)')
    non_heading_signals = re.compile(
        r'(?:资料依据|证据边界|后续需补充|本节|本处|衔接|重点放在|可参考|可包括|需要结合|形成衔接|不再展开|不再重复|但重在|本处重在|可围绕|风险清单|数据异常|应急预案)'
    )

    cn_num_map = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
                  "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
                  "十一": 11, "十二": 12, "十三": 13, "十四": 14, "十五": 15,
                  "十六": 16, "十七": 17, "十八": 18, "十九": 19, "二十": 20,
                  "二十一": 21, "二十二": 22, "二十三": 23, "二十四": 24, "二十五": 25,
                  "二十六": 26, "二十七": 27, "二十八": 28, "二十九": 29, "三十": 30}

    def _cn_to_int(value: str, fallback: int = 1) -> int:
        """兼容一、十一、二十六、三十一和阿拉伯数字。"""
        raw = str(value or "").strip()
        if raw.isdigit():
            return int(raw)
        if raw in cn_num_map:
            return cn_num_map[raw]
        if "十" in raw:
            left, _, right = raw.partition("十")
            tens = cn_num_map.get(left, 1) if left else 1
            ones = cn_num_map.get(right, 0) if right else 0
            return tens * 10 + ones
        return fallback

    def _looks_like_chapter_heading(title_part: str) -> bool:
        """判断“第X章...”是否真是章标题，而不是正文里的跨章节说明。"""
        raw = str(title_part or "").strip()
        cleaned = _clean_outline_title(raw)
        if not cleaned:
            return False
        # 严格按当前专著大纲标准识别：章标题必须是带“总字数/约xx字/xx字”的完整标题句。
        # 不再兼容无字数章标题，避免正文里的“第二章/第三章……”被误建为章节。
        if not chapter_word_count_signal.search(raw):
            return False
        if len(cleaned) > 80:
            return False
        if non_heading_signals.search(cleaned):
            return False
        if re.search(r"[。；;]", cleaned):
            return False
        return True

    current_section_index = 0
    current_level3_index = 0
    current_level4_index = 0
    current_last_section = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # 尝试匹配章节标题；必须像完整章标题，避免正文里的“第二章/第三章……”误建新章。
        ch_match = ch_pattern.match(line)
        if ch_match and _looks_like_chapter_heading(ch_match.group(3)):
            _flush_chapter()
            current_section_index = 0
            current_level3_index = 0
            current_level4_index = 0
            current_last_section = None
            cn_num, ar_num, title_part = ch_match.group(1), ch_match.group(2), ch_match.group(3)
            if ar_num:
                current_ch_num = int(ar_num)
            elif cn_num:
                current_ch_num = _cn_to_int(cn_num, 1)
            # 提取标题（去掉字数部分）
            title_clean = _clean_outline_title(title_part)
            current_ch_title = title_clean
            current_ch_word_count = _extract_word_count(title_part)
            current_ch_summary_parts = [line]
            current_ch_sections = []
            continue

        # 中文专著格式：第一节 / 一、 / （一） / 写作思路
        idea_match = writing_idea_pattern.match(line)
        if idea_match and current_last_section is not None:
            idea = idea_match.group(1).strip()
            current_last_section.summary = f"写作思路：{idea}"
            current_last_section.rag_query = f"{current_last_section.title} {idea}"
            current_ch_summary_parts.append(line)
            continue

        cn_sec_match = cn_section_pattern.match(line)
        if cn_sec_match and current_ch_num is not None:
            current_section_index = _cn_to_int(cn_sec_match.group(1), current_section_index + 1)
            current_level3_index = 0
            current_level4_index = 0
            sec_number = f"{current_ch_num}.{current_section_index}"
            sec_title_part = cn_sec_match.group(2)
            sec_title_clean = _clean_outline_title(sec_title_part)
            section = ChapterSection(section_number=sec_number, parent_number=str(current_ch_num), title=sec_title_clean, summary=sec_title_clean, word_count=_extract_word_count(sec_title_part), level=1, status="pending", rag_query=sec_title_clean)
            current_ch_sections.append(section)
            current_last_section = section
            current_ch_summary_parts.append(line)
            continue

        cn_l3_match = cn_level3_pattern.match(line)
        if cn_l3_match and current_ch_num is not None and current_section_index:
            current_level3_index = _cn_to_int(cn_l3_match.group(1), current_level3_index + 1)
            current_level4_index = 0
            sec_number = f"{current_ch_num}.{current_section_index}.{current_level3_index}"
            sec_title_part = cn_l3_match.group(2)
            sec_title_clean = _clean_outline_title(sec_title_part)
            section = ChapterSection(section_number=sec_number, parent_number=f"{current_ch_num}.{current_section_index}", title=sec_title_clean, summary=sec_title_clean, word_count=_extract_word_count(sec_title_part), level=2, status="pending", rag_query=sec_title_clean)
            current_ch_sections.append(section)
            current_last_section = section
            current_ch_summary_parts.append(line)
            continue

        cn_l4_match = cn_level4_pattern.match(line)
        if cn_l4_match and current_ch_num is not None and current_section_index and current_level3_index:
            current_level4_index = _cn_to_int(cn_l4_match.group(1), current_level4_index + 1)
            sec_number = f"{current_ch_num}.{current_section_index}.{current_level3_index}.{current_level4_index}"
            sec_title_part = cn_l4_match.group(2)
            sec_title_clean = _clean_outline_title(sec_title_part)
            section = ChapterSection(section_number=sec_number, parent_number=f"{current_ch_num}.{current_section_index}.{current_level3_index}", title=sec_title_clean, summary=sec_title_clean, word_count=_extract_word_count(sec_title_part), level=3, status="pending", rag_query=sec_title_clean)
            current_ch_sections.append(section)
            current_last_section = section
            current_ch_summary_parts.append(line)
            continue

        # 尝试匹配小节（1.1、1.1.1、1.1.2 等）
        sec_match = section_pattern.match(line)
        if sec_match:
            sec_number = sec_match.group(1)
            sec_title_part = sec_match.group(2)
            sec_title_clean = _clean_outline_title(sec_title_part)
            sec_word_count = _extract_word_count(sec_title_part)
            # 计算层级：1.1=1(节), 1.1.1=2(三级标题), 1.1.1.1=3(四级标题)
            dot_count = sec_number.count('.')
            level = min(dot_count, 3)
            parent_number = sec_number.rsplit('.', 1)[0] if '.' in sec_number else str(current_ch_num)

            section = ChapterSection(
                section_number=sec_number,
                parent_number=parent_number,
                title=sec_title_clean,
                summary=sec_title_clean,
                word_count=sec_word_count,
                actual_word_count=0,
                level=level,
                status="pending",
                rag_query=sec_title_clean,
            )
            current_ch_sections.append(section)
            current_last_section = section
            current_ch_summary_parts.append(line)
            continue

        # 其他行作为补充信息
        if current_ch_num is not None:
            current_ch_summary_parts.append(line)

    _flush_chapter()

    if chapters_created > 0:
        # 更新大纲文本
        if replace_all or not (project.outline or "").strip():
            project.outline = text
        else:
            existing_lines = _normalize_outline_text(project.outline or "").splitlines()
            new_chapter_numbers = set(project.chapters.keys())
            merged_lines: list[str] = []
            skip = False
            for old_line in existing_lines:
                old_match = ch_pattern.match(old_line.strip())
                if old_match:
                    old_cn, old_ar = old_match.group(1), old_match.group(2)
                    old_num = int(old_ar) if old_ar else (int(old_cn) if old_cn and old_cn.isdigit() else cn_num_map.get(old_cn, 0))
                    skip = old_num in new_chapter_numbers
                if not skip:
                    merged_lines.append(old_line)
            project.outline = _normalize_outline_text("\n".join(merged_lines + text.splitlines()))
        st.session_state["project_data"] = project
        # 大纲重解析后强制刷新写章节页的章节选择控件，避免旧 selectbox 选项缓存导致不同步。
        st.session_state["outline_parse_version"] = int(st.session_state.get("outline_parse_version", 0) or 0) + 1
        for key in list(st.session_state.keys()):
            if str(key).startswith("editor_selected_idx"):
                st.session_state.pop(key, None)
        if persist:
            save_project()
        st.session_state["outline_parse_feedback"] = {
            "count": chapters_created,
            "chapters": [f"{_format_chapter_label(n, '《' + (project.chapters[n].title or '未命名') + '》')}/{len(getattr(project.chapters[n], 'sections', []) or [])}个写作单元" for n in sorted(project.chapters.keys())],
        }
        if show_messages:
            st.success(t('parse_outline_success', n=chapters_created))
        st.session_state["show_paste_outline"] = False
        if rerun:
            st.rerun()
    else:
        if show_messages:
            st.warning(t('parse_outline_fail'))
    return chapters_created



def _safe_outline_chapter_count(value: Any, *, default: int = 8) -> int:
    """将项目章数字段规范化；旧项目默认 0/1 视为未规划，由自动建议接管。"""
    try:
        if isinstance(value, tuple):
            raw = int(value[-1] or value[0] or default)
        else:
            raw = int(value or 0)
    except Exception:
        raw = 0
    if raw <= 1:
        return int(default)
    return max(3, min(raw, 24))


def _parse_outline_target_words(project: ProjectKnowledgeBase) -> int:
    """从篇幅、字数范围等字段推断目标总字数。"""
    target_words = 0
    try:
        if isinstance(project.book_length, str):
            match = re.search(r"(\d+)\s*(?:万|w|W)?", project.book_length)
            if match:
                value = int(match.group(1))
                target_words = value * 10000 if re.search(r"万|w|W", project.book_length) else value
    except Exception:
        target_words = 0
    if target_words <= 0:
        try:
            raw_chars = getattr(project, "num_characters", 0)
            if isinstance(raw_chars, tuple):
                target_words = int(raw_chars[-1] or raw_chars[0] or 0)
            else:
                target_words = int(raw_chars or 0)
        except Exception:
            target_words = 0
    return max(0, target_words)


def _infer_outline_chapter_count(project: ProjectKnowledgeBase) -> int:
    """按专著主题、篇幅、资料量和现有大纲自动建议章数。"""
    existing_count = _count_outline_chapters(getattr(project, "outline", ""))
    if existing_count >= 3:
        return max(3, min(existing_count, 24))

    target_words = _parse_outline_target_words(project)
    if target_words <= 0:
        context_text = _join_project_context_parts(
            [getattr(project, "title", ""), getattr(project, "description", ""), getattr(project, "category", ""), getattr(project, "genre", "")],
            separator="\n",
        )
        if len(context_text) >= 260:
            target_words = 120000
        elif len(context_text) >= 120:
            target_words = 90000
        else:
            target_words = 80000

    if target_words <= 60000:
        chapters = 6
    elif target_words <= 100000:
        chapters = 8
    elif target_words <= 160000:
        chapters = 10
    elif target_words <= 240000:
        chapters = 12
    else:
        chapters = 14

    source_count = len(getattr(project, "source_documents", []) or [])
    evidence_count = len(getattr(project, "evidence_chunks", []) or [])
    if source_count >= 8 or evidence_count >= 30:
        chapters += 1
    if source_count >= 16 or evidence_count >= 60:
        chapters += 1

    return max(4, min(chapters, 16))


def _outline_target_settings(project: ProjectKnowledgeBase) -> tuple[int, int, int]:
    """返回目标章数、总字数、每章字数。"""
    inferred_chapters = _infer_outline_chapter_count(project)
    target_chapters = _safe_outline_chapter_count(getattr(project, "num_chapters", 0), default=inferred_chapters)
    target_words = _parse_outline_target_words(project)
    if target_words <= 0:
        target_words = max(target_chapters, 1) * 10000
    words_per_chapter = max(3000, target_words // max(target_chapters, 1))
    return target_chapters, target_words, words_per_chapter


def _count_outline_chapters(text: str) -> int:
    """统计大纲中可解析章节数量。"""
    normalized = _normalize_outline_text(text or "")
    pattern = re.compile(r"^(?:第[一二三四五六七八九十百千\d]+章|Chapter\s*\d+)\b", re.IGNORECASE)
    return sum(1 for line in normalized.splitlines() if pattern.match(line.strip()))


from libriscribe.agents.chapter_writer import ChapterWriterAgent as _OutlineLabelFormatter


def _cn_chapter_num(n: int) -> str:
    return chinese_number(n)


def _format_chapter_label(chapter_num: int, title: str = "") -> str:
    """把内部数字章号显示为第一章/第二章。"""
    return format_chapter_label(chapter_num, title)


def _format_outline_section_label(section_number: str, title: str = "") -> str:
    """把内部 1.1/1.1.1/1.1.1.1 编号显示为中文大纲层级。"""
    return _OutlineLabelFormatter.format_outline_section_label(section_number, title)


def _preface_block(project: ProjectKnowledgeBase, target_words: int) -> str:
    preface_words = max(1200, min(5000, target_words // 20))
    return f"序言 全书的逻辑起点与最终归宿（建议 {preface_words}字）\n序言需说明研究背景、核心问题、全书主线、章节递进关系、预期贡献与最终归宿。"


def _outline_brainstorm_context(project: ProjectKnowledgeBase, limit: int = 5000) -> str:
    """读取第二步资料页沉淀的大纲前头脑风暴，供后续大纲生成优先吸收。"""
    brainstorm = _clean_project_display_text(getattr(project, "outline_brainstorm", ""))
    return brainstorm[:limit].strip()


def _material_library_context(project: ProjectKnowledgeBase, limit: int = 8000, max_chunks: int = 12) -> str:
    """把资料库中用户上传/导入的证据片段整理为大纲和正文可直接引用的兜底上下文。

    向量索引不可用时，资料仍应作为写作参考来源进入提示词；这里按片段顺序截取，
    避免 embedding 初始化失败导致资料完全无法参与大纲和正文生成。
    """
    if project is None:
        return ""
    documents_by_id = {
        str(getattr(doc, "id", "")): doc
        for doc in (getattr(project, "source_documents", []) or [])
        if str(getattr(doc, "id", "")).strip()
    }
    parts = []
    used = 0
    for chunk in getattr(project, "evidence_chunks", []) or []:
        text = _clean_project_display_text(getattr(chunk, "text", ""))
        if not _is_usable_evidence_text(text):
            continue
        doc = documents_by_id.get(str(getattr(chunk, "document_id", "")))
        source_name = (
            getattr(doc, "file_name", "")
            or getattr(doc, "title", "")
            or getattr(chunk, "source", "")
            or "资料库片段"
        )
        source_type = getattr(doc, "source_type", "") if doc else ""
        status = getattr(doc, "status", "") if doc else ""
        parts.append(
            f"[来源: {source_name} | 类型: {source_type or 'material'} | 状态: {status or 'library'} | evidence_id={getattr(chunk, 'id', '')}]\n"
            f"{text[:1200]}"
        )
        used += 1
        if used >= max_chunks:
            break
    return "\n\n".join(parts).strip()[:limit]


SOURCES_AI_WORKFLOW_TASKS = [
    {
        "task": "生成检索词",
        "label": "1. 生成检索词",
        "goal": "把书名、项目描述和大纲意图转成后续检索必须使用的关键词组。",
        "output": "中文检索式、英文检索式、同义词、排除词、百度/API 可用短词和下一步检索顺序。",
    },
    {
        "task": "整理检索结果",
        "label": "2. 根据检索词整理检索结果",
        "goal": "严格依据上一步检索词，整理 OpenAlex、百度/API、已上传资料和引用记录中的结果。",
        "output": "检索词命中情况、主题归类、可信度、来源年份、可支撑章节和待核验风险。",
    },
    {
        "task": "分析资料缺口",
        "label": "3. 结合检索结果与大纲分析资料缺口",
        "goal": "根据第二步结果和大纲各章节，判断资料能支撑什么、不能直接支撑什么。",
        "output": "按章节列出资料状态：可支撑主题方向；不可直接支撑政策依据、发展历程、权威定义、行业数据等缺口。",
    },
    {
        "task": "AI检索资料入库",
        "label": "4. AI检索资料并保存到资料库",
        "goal": "基于第三步缺口优先调用 AI 模型自身搜索；若模型反馈不支持搜索，则自动调用已配置的百度搜索 API。",
        "output": "AI/百度检索结果、网页或文献线索、补充资料摘要，并全部沉淀到资料来源库。",
    },
    {
        "task": "资料库头脑风暴",
        "label": "5. 基于全资料库头脑风暴并自动补全",
        "goal": "综合第四步新增资料和资料库所有资料进行头脑风暴；若仍缺资料，自动回到第四步补检并入库。",
        "output": "最终资料状态、研究问题、章节支撑矩阵、资料补全记录和可提交给大纲生成的结果。",
    },
]

SOURCES_AI_WORKFLOW_TASK_NAMES = [step["task"] for step in SOURCES_AI_WORKFLOW_TASKS]

SOURCES_AI_TASK_SLUGS = {
    "生成检索词": "search_terms",
    "整理检索结果": "search_digest",
    "大纲前头脑风暴": "outline_brainstorm",
    "资料库头脑风暴": "outline_brainstorm",
    "根据上传资料写作": "evidence_draft",
    "分析资料缺口": "source_gap",
    "AI补充资料入库": "supplemental_sources",
    "AI检索资料入库": "supplemental_sources",
    "生成文献核查计划": "verification_plan",
}


def _sources_ai_task_slug(task: str) -> str:
    """将资料助手任务名转成稳定 ID 后缀，便于同一任务反复更新同一资料。"""
    if task in SOURCES_AI_TASK_SLUGS:
        return SOURCES_AI_TASK_SLUGS[task]
    slug = re.sub(r"[^0-9A-Za-z_\-]+", "_", str(task or "assistant")).strip("_").lower()
    return slug or "assistant"


def _sources_ai_result_ids(task: str) -> tuple[str, str]:
    slug = _sources_ai_task_slug(task)
    return f"sources_ai_{slug}", f"sources_ai_{slug}_chunk"


def _sources_ai_saved_text(project: ProjectKnowledgeBase, task: str, session_results: Optional[dict] = None, limit: int = 20000) -> str:
    """读取某个资料助手步骤的已保存内容；优先用当前会话编辑结果，其次读取资料库证据片段。"""
    if session_results and str(session_results.get(task, "")).strip():
        return str(session_results.get(task, "")).strip()[:limit]
    document_id, chunk_id = _sources_ai_result_ids(task)
    for chunk in getattr(project, "evidence_chunks", []) or []:
        if getattr(chunk, "id", "") == chunk_id or getattr(chunk, "document_id", "") == document_id:
            return str(getattr(chunk, "text", "") or "").strip()[:limit]
    return ""


def _sources_ai_workflow_context(project: ProjectKnowledgeBase, session_results: Optional[dict] = None, limit_per_step: int = 2500) -> str:
    """汇总资料助手五步工作流的已保存记录，供下一步和大纲生成持续引用。"""
    parts = []
    for step in SOURCES_AI_WORKFLOW_TASKS:
        task = step["task"]
        text = _sources_ai_saved_text(project, task, session_results, limit=limit_per_step)
        if text:
            parts.append(f"【{step['label']}】\n{text}")
    return "\n\n".join(parts).strip()


def _sources_ai_max_tokens(task: str) -> int:
    """资料助手使用紧凑输出，避免第三方中转因 6k/7k 输出请求长时间 524。"""
    if task in {"大纲前头脑风暴", "资料库头脑风暴"}:
        return 4200
    if task == "根据上传资料写作":
        return 3600
    if task in {"AI补充资料入库", "AI检索资料入库"}:
        return 3000
    return 3200


def _sources_ai_model_search_unsupported(text: str) -> bool:
    """判断模型是否明确反馈当前不支持联网/实时搜索。"""
    normalized = str(text or "").lower()
    markers = [
        "不支持联网", "无法联网", "不能联网", "没有联网", "无法实时搜索", "不能实时搜索",
        "不具备搜索", "无法访问互联网", "不能访问互联网", "无法浏览网页", "不能浏览网页",
        "no internet", "can't browse", "cannot browse", "unable to browse", "web browsing is not available",
    ]
    return any(marker in normalized for marker in markers)


def _sources_ai_needs_more_sources(text: str) -> bool:
    """判断头脑风暴结果是否仍在提示资料不足，需要自动回到第四步补检。"""
    normalized = str(text or "")
    markers = ["资料缺口", "缺少", "不足", "不可直接支撑", "需要补充", "待补充", "证据不足", "缺乏", "需进一步检索"]
    return any(marker in normalized for marker in markers)


def _extract_sources_ai_search_queries(text: str, *, limit: int = 6) -> list[str]:
    """从检索词/缺口分析/头脑风暴文本中提取可给搜索 API 使用的短查询。"""
    candidates: list[str] = []
    for raw_line in str(text or "").splitlines():
        line = re.sub(r"^[\s\-\*\d一二三四五六七八九十、\.（）()：:]+", "", raw_line).strip(" ；;，,。")
        if not line:
            continue
        line = re.sub(r"^(中文检索式|英文检索式|检索词|建议检索词|下一轮检索词|补充检索词)\s*[:：]", "", line).strip()
        for piece in re.split(r"[；;|｜]", line):
            query = re.sub(r"\s+", " ", piece).strip(" ；;，,。")
            if 4 <= len(query) <= 120 and not query.startswith(("可支撑", "不可直接支撑", "资料状态")):
                candidates.append(query)
    deduped: list[str] = []
    seen = set()
    for query in candidates:
        key = query.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(query[:120])
        if len(deduped) >= limit:
            break
    return deduped


def _sources_ai_screening_keep(text: str) -> bool:
    """解析 AI 筛选结论；只有明确保留/可入库时才写入资料库。"""
    normalized = str(text or "").strip().lower()
    if not normalized:
        return False
    reject_markers = ["keep: false", '"keep": false', "保留：否", "是否保留：否", "不入库", "剔除", "不建议入库"]
    accept_markers = ["keep: true", '"keep": true', "保留：是", "是否保留：是", "建议入库", "可以入库", "可入库"]
    if any(marker in normalized for marker in reject_markers):
        return False
    return any(marker in normalized for marker in accept_markers)


def _screen_web_page_with_ai(
    project: ProjectKnowledgeBase,
    client: Optional[LLMClient],
    *,
    query: str,
    item: dict,
    page: dict,
    gap_context: str,
) -> dict:
    """把已打开网页交给 AI 筛选，返回是否入库、摘要和证据片段。"""
    title = str(item.get("title") or "网页资料").strip()
    url = str(item.get("url") or "").strip()
    final_url = str(page.get("final_url") or url).strip()
    page_text = str(page.get("text") or "").strip()
    if not page.get("ok") or len(page_text) < 120:
        return {"keep": False, "screening": f"网页未入库：{page.get('error') or '无法抽取有效正文'}"}
    if client is None:
        return {
            "keep": True,
            "screening": "保留：是\n理由：已成功打开网页并抽取正文；当前无 AI 客户端，仅作为待核验网页资料入库。",
            "summary": page_text[:900],
            "evidence": page_text[:1800],
        }
    prompt = f"""你是中文专著资料筛选员。百度/搜索 API 只提供标题和链接，下面内容是系统已经打开链接后抽取的网页正文。
请判断该网页是否能作为本项目资料库的补充材料。必须谨慎：广告页、商品页、无关页、正文太泛、来源不可靠或无法支撑资料缺口的页面，一律不入库。

【项目】
书名：{project.title}
类型：{project.genre}
描述：{project.description or '无'}
大纲：
{str(getattr(project, 'outline', '') or '')[:3000]}

【资料缺口/补检依据】
{str(gap_context or '')[:5000]}

【搜索词】{query}
【网页标题】{title}
【原始链接】{url}
【最终链接】{final_url}

【网页正文节选】
{page_text[:12000]}

请按以下固定格式输出，不要输出其它闲聊：
保留：是/否
可信度：高/中/低
可支撑章节：列出章节或“无”
入库标题：适合作为资料库标题的名称
摘要：150-300字概括网页中与专著相关的内容
证据片段：摘录网页中最能支撑写作的原文片段，保留关键数据/政策/定义/观点
风险：说明来源权威性、发布时间、广告/转载/待核验风险
"""
    result = client.generate_content(prompt, max_tokens=1800, temperature=0.15, language=project.language)
    screening = (result if isinstance(result, str) else str(result or "")).strip()
    keep = _sources_ai_screening_keep(screening)
    return {
        "keep": keep,
        "screening": screening,
        "summary": screening[:1000] if keep else "",
        "evidence": f"AI筛选结果：\n{screening}\n\n网页正文节选：\n{page_text[:6000]}" if keep else "",
    }


def _import_screened_web_pages_as_sources(
    project: ProjectKnowledgeBase,
    screened_pages: list[dict],
    *,
    assistant_task: str = "AI检索资料入库",
) -> tuple[list[SourceDocument], list[EvidenceChunk]]:
    """只把已打开网页且经 AI 筛选通过的材料保存为资料来源和证据片段。"""
    imported_docs: list[SourceDocument] = []
    imported_chunks: list[EvidenceChunk] = []
    generated_at = datetime.now().isoformat()
    for record in screened_pages or []:
        if not record.get("keep"):
            continue
        query = str(record.get("query") or "").strip()
        item = record.get("item") or {}
        page = record.get("page") or {}
        screening = str(record.get("screening") or "").strip()
        title = str(item.get("title") or query or "网页筛选资料").strip()
        url = str(item.get("url") or "").strip()
        final_url = str(page.get("final_url") or url).strip()
        raw_key = final_url or url or f"{query}:{title}"
        digest = hashlib.sha1(raw_key.encode("utf-8")).hexdigest()[:12]
        document_id = f"web-src-{digest}"
        chunk_id = f"web-src-{digest}_chunk"
        metadata = {
            "origin": "sources_ai_search_screened",
            "assistant_task": assistant_task,
            "external_provider": item.get("provider") or "baidu_search_api",
            "search_query": query,
            "url": url,
            "final_url": final_url,
            "page": item.get("page"),
            "http_status": page.get("status_code"),
            "content_type": page.get("content_type"),
            "generated_at": generated_at,
            "verification_status": "ai_screened_web_page_pending_human_verification",
            "usage_warning": "该资料来自搜索结果网页正文，已由 AI 初筛；正式引用前仍需人工核验网页权威性、发布时间和原文准确性。",
            "ai_screening": screening[:4000],
            "raw_search_item": item.get("raw", {}),
        }
        document = SourceDocument(
            id=document_id,
            title=title[:240],
            source_type="web_page_ai_screened",
            file_name=f"web-page-{document_id}.txt",
            file_path=final_url or url,
            url=final_url or url,
            chunk_count=1,
            indexed_at=generated_at,
            status="pending",
            summary=(record.get("summary") or screening or str(page.get("text") or ""))[:1000],
            metadata=metadata,
        )
        chunk_text = (record.get("evidence") or f"检索词：{query}\n标题：{title}\n链接：{final_url or url}\n\nAI筛选：\n{screening}")[:20000]
        chunk = EvidenceChunk(
            id=chunk_id,
            document_id=document_id,
            source=document.title,
            text=chunk_text,
            chunk_index=0,
            chunk_hash=f"{document_id}:{len(chunk_text)}:{generated_at}",
            metadata=metadata,
        )
        project.source_documents = [doc for doc in getattr(project, "source_documents", []) if getattr(doc, "id", "") != document_id]
        project.evidence_chunks = [old for old in getattr(project, "evidence_chunks", []) if getattr(old, "id", "") != chunk_id]
        project.add_source_document(document)
        project.add_evidence_chunk(chunk)
        imported_docs.append(document)
        imported_chunks.append(chunk)
    return imported_docs, imported_chunks


def _run_sources_ai_gap_search(
    project: ProjectKnowledgeBase,
    search_seed_text: str,
    *,
    literature_service: LiteratureSearchService,
    web_search_api_url: str = "",
    web_search_id: str = "",
    web_search_key: str = "",
    web_search_tn: str = "",
    web_search_cookie: str = "",
    tavily_api_key: str = "",
    tavily_base_url: str = "",
    tavily_max_results: int = 10,
    tavily_search_depth: str = "advanced",
    max_queries: int = 6,
    client: Optional[LLMClient] = None,
) -> str:
    """根据资料缺口补检：优先 Tavily，失败/未配置时回退百度/API；所有候选都先打开网页并经 AI 筛选后入库。"""
    queries = _extract_sources_ai_search_queries(search_seed_text, limit=max_queries)
    if not queries:
        queries = literature_service.outline_search_queries(project, max_queries=max_queries)
    if not queries:
        return "未提取到可执行补检词，未调用 Tavily 或百度搜索 API。"

    has_tavily = bool(str(tavily_api_key or "").strip())
    has_baidu = bool(str(web_search_id or "").strip() and str(web_search_key or "").strip())
    if not has_tavily and not has_baidu:
        return "模型反馈不支持搜索，但 Tavily API Key 与百度搜索 API 开发者 ID/KEY 均未配置，无法自动补检。"

    grouped_results: list[dict] = []
    screened_pages: list[dict] = []
    api_failures: list[str] = []
    fetch_failures: list[str] = []
    total_candidates = 0
    provider_counts = {"tavily": 0, "baidu": 0}

    def _screen_result_items(query: str, result: dict, *, provider_label: str, candidate_limit: int = 8) -> None:
        nonlocal total_candidates
        page_errors = [str(page.get("msg") or "") for page in (result.get("pages") or []) if page.get("code") not in (None, 200, "200") and page.get("msg")]
        if page_errors:
            api_failures.append(f"{query}（{provider_label}）：{'；'.join(page_errors[:3])}")
        for item in (result.get("items") or [])[:candidate_limit]:
            total_candidates += 1
            url = str(item.get("url") or "").strip()
            if not url:
                fetch_failures.append(f"{query}：候选结果缺少 URL（{item.get('title') or '无标题'}）")
                continue
            fetcher = getattr(literature_service, "fetch_web_page_text", None)
            page = fetcher(url) if callable(fetcher) else {"ok": False, "url": url, "text": "", "error": "当前检索服务没有网页打开能力"}
            if not page.get("ok"):
                fetch_failures.append(f"{query}：{item.get('title') or url} 打开失败：{page.get('error') or '未知错误'}")
            screened = _screen_web_page_with_ai(project, client, query=query, item=item, page=page, gap_context=search_seed_text)
            screened_pages.append({"query": query, "item": item, "page": page, **screened})

    for query in queries[:max_queries]:
        tavily_used = False
        if has_tavily:
            try:
                tavily_result = literature_service.tavily_search(
                    query,
                    api_key=tavily_api_key,
                    base_url=tavily_base_url,
                    max_results=tavily_max_results,
                    search_depth=tavily_search_depth,
                )
                grouped_results.append({"query": query, "provider": "tavily", "result": tavily_result})
                provider_counts["tavily"] += 1
                tavily_used = bool(tavily_result.get("items"))
                _screen_result_items(query, tavily_result, provider_label="Tavily")
            except Exception as exc:
                api_failures.append(f"{query}（Tavily）：{exc}")

        if (not tavily_used) and has_baidu:
            try:
                baidu_result = literature_service.web_search(
                    query,
                    api_url=web_search_api_url,
                    developer_id=web_search_id,
                    developer_key=web_search_key,
                    tn=web_search_tn,
                    cookie=web_search_cookie,
                    pages=3,
                )
                grouped_results.append({"query": query, "provider": "baidu", "result": baidu_result})
                provider_counts["baidu"] += 1
                _screen_result_items(query, baidu_result, provider_label="百度/API")
            except Exception as exc:
                api_failures.append(f"{query}（百度/API）：{exc}")

    documents, chunks = _import_screened_web_pages_as_sources(project, screened_pages, assistant_task="AI检索资料入库")
    rejected = len([record for record in screened_pages if not record.get("keep")])
    provider_parts = []
    if provider_counts["tavily"]:
        provider_parts.append(f"Tavily {provider_counts['tavily']} 组")
    if provider_counts["baidu"]:
        provider_parts.append(f"百度/API {provider_counts['baidu']} 组")
    provider_text = "、".join(provider_parts) or "未成功调用任何搜索渠道"
    message = (
        f"已调用{provider_text}按 {len(queries[:max_queries])} 个检索词补检，获得 {total_candidates} 条标题/链接候选；"
        f"已尝试打开网页并交给 AI 筛选，最终保存 {len(documents)} 条资料来源、{len(chunks)} 条证据片段到资料库。"
        f"未入库/剔除 {rejected} 条。"
    )
    if api_failures:
        message += f" 搜索渠道诊断：{'；'.join(api_failures[:5])}。"
    if fetch_failures:
        message += f" 网页打开诊断：{'；'.join(fetch_failures[:5])}。"
    return message


def _persist_sources_ai_result(
    project: ProjectKnowledgeBase,
    task: str,
    result_text: str,
    instruction: str = "",
    context_summary: str = "",
) -> tuple[SourceDocument, EvidenceChunk]:
    """把资料助手输出保存成内部资料和证据片段。

    注意：这些内容是 AI 生成的分析资料，不等同于已核验真实引用；正文可参考其分析，
    但正式参考文献仍必须来自 citation / 上传原文 / 已核验外部来源。
    """
    cleaned = str(result_text or "").strip()
    if not cleaned:
        raise ValueError("没有可保存的 AI 资料助手结果。")

    document_id, chunk_id = _sources_ai_result_ids(task)
    generated_at = datetime.now().isoformat()
    metadata = {
        "origin": "sources_ai_assistant",
        "assistant_task": task,
        "instruction": str(instruction or "")[:2000],
        "context_summary": str(context_summary or "")[:2000],
        "generated_at": generated_at,
        "verification_status": "ai_analysis_not_verified_citation",
        "can_use_for_outline": True,
        "can_use_for_draft": True,
        "usage_warning": "AI资料助手输出只能作为内部分析/写作线索，不可直接当作已核验参考文献。",
    }
    document = SourceDocument(
        id=document_id,
        title=f"AI资料助手：{task}",
        source_type="ai_assistant",
        chunk_count=1,
        indexed_at=generated_at,
        status="indexed",
        summary=cleaned[:600],
        metadata=metadata,
    )
    chunk = EvidenceChunk(
        id=chunk_id,
        document_id=document_id,
        source=document.title,
        text=cleaned[:20000],
        chunk_index=0,
        chunk_hash=f"{document_id}:{len(cleaned)}:{generated_at}",
        metadata=metadata,
    )
    project.add_source_document(document)
    project.add_evidence_chunk(chunk)
    if task in {"大纲前头脑风暴", "资料库头脑风暴"}:
        project.outline_brainstorm = cleaned
    return document, chunk


def _outline_global_constraints(project: ProjectKnowledgeBase, target_chapters: int, target_words: int, words_per_chapter: int, include_preface: bool) -> str:
    chapter_names = "、".join(f"第{_cn_chapter_num(i)}章" for i in range(1, target_chapters + 1))
    preface_rule = "开头必须先输出“序言 全书的逻辑起点与最终归宿（建议 xxxx字）”一行及一句说明；序言不编号为章节。" if include_preface else "不要输出序言、前言或说明文字。"
    brainstorm = _outline_brainstorm_context(project)
    material_context = _material_library_context(project, limit=9000, max_chunks=14)
    brainstorm_block = f"\n\n大纲前资料头脑风暴（来自第二步资料页，优先用于确定研究问题、资料边界和章节模块）：\n{brainstorm}" if brainstorm else ""
    material_block = f"\n\n资料库用户上传/导入资料片段（必须作为大纲内容和后续正文引用参考的重要来源）：\n{material_context}" if material_context else ""
    brainstorm_rule = "必须优先吸收“大纲前资料头脑风暴”和资料库片段中的研究问题、资料线索、证据边界、章节模块建议和待核验风险；若资料不足，只在写作思路中标明资料补充方向，不得编造未核验文献。" if (brainstorm or material_context) else "如果没有资料头脑风暴，也要基于项目描述、资料数量和引用状态自行判断章节职责与资料缺口。"
    return f"""书名：{project.title}
学科/类型：{project.genre}
分类：{project.category}
语言：{project.language}
项目描述：{project.description or '无'}
目标章数：{target_chapters}
总目标字数：约 {target_words} 字{brainstorm_block}{material_block}

全书结构强制规范：
1. 必须先在内部完成整体框架思考：为什么写、全书价值定位、研究对象、主线逻辑、章节递进关系；但最终不要把思考过程输出到正文目录外。
2. {brainstorm_rule}
3. 必须输出完整全书目录，且必须包含：{chapter_names}，不得只输出第一章。
4. {preface_rule}
5. 章节标题格式必须是：第一章 标题（总字数 {words_per_chapter}字）。
6. 二级标题用“第一节 标题”，三级标题用“一、标题”，四级标题用“（一）标题”。
7. 每个四级标题后必须紧跟一行“写作思路：……”，说明切入角度、展开路径、与上下文衔接、资料依据和证据边界。
8. 全书要体现“背景价值—对象基础—关键技术/机制—场景应用—实施路径—监管评价—持续优化”的递进逻辑，可按主题调整但不能重复堆砌。
9. 保持术语、研究对象、分析尺度、政策语汇和字数颗粒度一致；各章深度均衡、质量统一。
10. 只输出目录正文，不输出解释、Markdown 代码块、闲聊或免责声明。"""


def _format_outline_prompt(template: str, project: ProjectKnowledgeBase, *, target_chapters: int, target_words: int, words_per_chapter: int, include_preface: bool, existing_outline: str = "", instruction: str = "") -> str:
    """用全局 outliner 提示词组装后端实际生效的大纲提示。"""
    values = {
        "book_title": project.title,
        "genre": project.genre,
        "category": project.category,
        "language": project.language,
        "description": project.description or "无",
        "outline_brainstorm": _join_project_context_parts(
            [_outline_brainstorm_context(project), _material_library_context(project, limit=7000, max_chunks=10)],
            separator="\n\n",
            limit=10000,
        ) or "暂无",
        "target_chapters": target_chapters,
        "target_words": target_words,
        "words_per_chapter": words_per_chapter,
        "include_preface": "是" if include_preface else "否",
        "existing_outline": existing_outline or "暂无",
        "instruction": instruction or "生成完整中文专著大纲，保持章际逻辑一致。",
    }
    try:
        return template.format(**values)
    except KeyError as exc:
        missing = exc.args[0]
        raise ValueError(f"全局大纲提示词缺少或写错变量：{{{missing}}}。请进入全局设置，恢复 outliner 默认提示词或修正变量。") from exc


def _call_outline_model(client: LLMClient, prompt: str, project: ProjectKnowledgeBase, max_tokens: int = 8000) -> str:
    """统一调用大纲模型并规范化输出。"""
    result = client.generate_content(prompt, max_tokens=max_tokens, temperature=0.35, language=project.language)
    return _normalize_outline_text((result or "").strip())


def _generate_outline_chapter_by_chapter(client: LLMClient, project: ProjectKnowledgeBase, include_preface: bool) -> str:
    """先生成全书章纲，再逐章生成小节，避免模型只展开第一章。"""
    target_chapters, target_words, words_per_chapter = _outline_target_settings(project)
    constraints = _outline_global_constraints(project, target_chapters, target_words, words_per_chapter, include_preface=False)
    architecture_prompt = f"""请先为中文专著生成全书章级架构，只输出 {target_chapters} 行章节标题。
{constraints}

额外要求：
1. 先在内部判断为什么写、全书价值定位、已有资料/证据能支撑哪些内容、适合分成多少个逻辑模块，但不要输出思考过程。
2. 若存在“大纲前资料头脑风暴”，必须优先用其中的研究问题、资料线索、证据边界和章节模块建议来确定全书架构。
3. 用户当前目标是 {target_chapters} 章；必须围绕这个章数完成全书结构策划，不得只生成第一章，也不得只展开局部章节。
4. 每行只写“第X章 标题（总字数 {words_per_chapter}字）”，不得输出小节。
5. 章节之间必须形成连续逻辑，避免每章重复“背景、意义、对策”。"""
    architecture = _call_outline_model(client, architecture_prompt, project, max_tokens=2500)
    chapter_lines = [line.strip() for line in architecture.splitlines() if re.match(r"^第[一二三四五六七八九十百千\d]+章", line.strip())]
    if len(chapter_lines) < target_chapters:
        chapter_lines = [f"第{_cn_chapter_num(i)}章 {project.title}专题研究第{i}部分（总字数 {words_per_chapter}字）" for i in range(1, target_chapters + 1)]

    parts = [_preface_block(project, target_words)] if include_preface else []
    full_architecture = "\n".join(chapter_lines[:target_chapters])
    progress = st.progress(0, text="正在分章生成大纲…")
    for idx, chapter_line in enumerate(chapter_lines[:target_chapters], start=1):
        chapter_prompt = f"""请只为下面这一章生成中文专著目录，不要生成其它章节。

全书章级架构：
{full_architecture}

当前章节：{chapter_line}
当前章号：{idx}

输出格式必须参考：
{chapter_line}
第一节 二级标题（约 {max(1200, words_per_chapter // 3)}字）
一、三级标题（约 {max(600, words_per_chapter // 6)}字）
（一）四级标题（约 {max(300, words_per_chapter // 12)}字）
写作思路：从什么背景切入、展开什么机制、与前后章节如何衔接。

强制要求：
1. 本章 2-3 个“第X节”；每节 2-3 个“一、”；每个“一、”下 1-2 个“（一）”。
2. 每个“（一）”后必须有“写作思路：”。
3. 与全书架构和第二步资料头脑风暴保持衔接，不重复其它章节职责。
4. 写作思路要体现资料依据、证据边界和后续需补充的资料方向。
5. 只输出当前章目录。"""
        chapter_outline = _call_outline_model(client, chapter_prompt, project, max_tokens=3500)
        parts.append(chapter_outline or chapter_line)
        progress.progress(idx / max(target_chapters, 1), text=f"已生成第 {idx}/{target_chapters} 章大纲")
    progress.empty()
    return _normalize_outline_text("\n".join(parts))


def _generate_outline_with_ai(project: ProjectKnowledgeBase, mode: str = "full", include_preface: bool = True) -> None:
    """使用 AI 生成专著大纲，并直接解析为章-节-三级-四级写作单元。"""
    client = get_llm_client()
    if client is None:
        return

    target_chapters, target_words, words_per_chapter = _outline_target_settings(project)
    constraints = _outline_global_constraints(project, target_chapters, target_words, words_per_chapter, include_preface)
    outline_template = PromptService.load_outline_prompt()
    prompt = _format_outline_prompt(
        outline_template,
        project,
        target_chapters=target_chapters,
        target_words=target_words,
        words_per_chapter=words_per_chapter,
        include_preface=include_preface,
        instruction=f"{constraints}\n请立即输出完整全书目录，从{'序言开始，然后从' if include_preface else ''}第一章一直到第{_cn_chapter_num(target_chapters)}章。",
    )

    with st.spinner("AI 正在生成全书大纲…分章模式会更慢但更稳定"):
        try:
            profile = _resolve_project_model_profile(project)
            if mode == "chapter_by_chapter":
                outline = _generate_outline_chapter_by_chapter(client, project, include_preface)
            else:
                outline = _call_outline_model(client, prompt, project, max_tokens=9000)

            # 如果当前页面仍拿到旧缓存客户端，立即重建后再试一次，避免要求用户手动重启网页。
            if not outline and profile is not None:
                st.session_state["llm_client"] = _create_llm_client_from_profile(profile)
                st.session_state["llm_client_signature"] = "force-refreshed-after-empty-outline"
                client = st.session_state["llm_client"]
                outline = _call_outline_model(client, prompt, project, max_tokens=9000)

            if not outline:
                detail = getattr(client, "last_error", "") or getattr(client, "last_response_preview", "")
                st.error(f"AI 未返回可用大纲。当前模型：{_profile_label(profile) if profile else client.model}。接口诊断：{detail[:1200] if detail else '无响应正文。'}")
                return

            actual_chapters = _count_outline_chapters(outline)
            if mode == "full" and actual_chapters < target_chapters:
                st.warning(f"模型一次生成只返回 {actual_chapters}/{target_chapters} 章，已自动切换为分章生成补全全书。")
                outline = _generate_outline_chapter_by_chapter(client, project, include_preface)
                actual_chapters = _count_outline_chapters(outline)

            project.outline = outline
            parsed_count = _parse_outline_text(project, outline, rerun=False)
            if parsed_count:
                st.success(f"已生成并解析 {parsed_count}/{target_chapters} 章。{'已包含序言。' if include_preface else ''}")
                save_project()
                st.rerun()
            else:
                st.error("AI 已返回文本，但未解析出章节。已保留原始大纲到编辑框，请检查模型输出格式或手动点击解析。")
                with st.expander("查看 AI 原始大纲", expanded=True):
                    st.code(outline, language="markdown")
        except Exception as e:
            st.error(f"{t('error')} {e}")
            logger.exception("Outline generation failed")


def _generate_single_chapter_outline_with_ai(project: ProjectKnowledgeBase, chapter_number: int, instruction: str = "", include_preface: bool = True) -> None:
    """选择某一章单独生成或修改，并合并回现有全书大纲。"""
    client = get_llm_client()
    if client is None:
        return

    target_chapters, target_words, words_per_chapter = _outline_target_settings(project)
    current_chapter = project.chapters.get(chapter_number)
    chapter_title = current_chapter.title if current_chapter else f"{project.title}第{chapter_number}部分"
    full_architecture = project.outline or "\n".join(
        f"第{_cn_chapter_num(i)}章 {project.title}专题研究第{i}部分（总字数 {words_per_chapter}字）"
        for i in range(1, target_chapters + 1)
    )
    brainstorm = _outline_brainstorm_context(project)
    brainstorm_block = f"\n第二步资料头脑风暴：\n{brainstorm}\n" if brainstorm else ""
    prompt = f"""请根据全书上下文，只生成或修改第{_cn_chapter_num(chapter_number)}章目录。

全书上下文大纲：
{full_architecture}{brainstorm_block}

当前章节：第{_cn_chapter_num(chapter_number)}章 {chapter_title}（总字数 {words_per_chapter}字）
用户要求：{instruction or '补全本章节、一、（一）和写作思路，保持与前后章节逻辑一致，并吸收第二步资料头脑风暴。'}

输出格式必须严格如下：
第{_cn_chapter_num(chapter_number)}章 {chapter_title}（总字数 {words_per_chapter}字）
第一节 二级标题（约 {max(1200, words_per_chapter // 3)}字）
一、三级标题（约 {max(600, words_per_chapter // 6)}字）
（一）四级标题（约 {max(300, words_per_chapter // 12)}字）
写作思路：说明本小目如何切入、展开什么内容、与前后章节如何衔接。

强制要求：
1. 只输出第{_cn_chapter_num(chapter_number)}章，不要输出其他章节。
2. 先在内部判断本章在全书中的职责与边界，但不要输出分析过程。
3. 本章必须有 2-3 个“第X节”，每节 2-3 个“一、”，每个“一、”下 1-2 个“（一）”。
4. 每个“（一）”后必须紧跟“写作思路：”。
5. 写作思路要吸收第二步资料头脑风暴中的证据线索和边界，不得编造未核验文献。
6. 不得与其他章节重复承担同一写作职责。"""
    with st.spinner(f"AI 正在生成/修改第{_cn_chapter_num(chapter_number)}章大纲…"):
        try:
            outline = _call_outline_model(client, prompt, project, max_tokens=4500)
            if not outline or _count_outline_chapters(outline) < 1:
                st.error("AI 未返回可解析的单章大纲。")
                if outline:
                    st.code(outline, language="markdown")
                return
            parsed_count = _parse_outline_text(project, outline, rerun=False, replace_all=False)
            if parsed_count:
                st.success(f"第{_cn_chapter_num(chapter_number)}章已单独生成/修改，并合并回全书大纲。")
                save_project()
                st.rerun()
            else:
                st.error("单章大纲返回了文本，但未解析出章节。")
                st.code(outline, language="markdown")
        except Exception as e:
            st.error(f"单章生成/修改失败：{e}")
            logger.exception("Single chapter outline generation failed")


def _improve_outline_with_ai(project: ProjectKnowledgeBase, instruction: str = "", include_preface: bool = True) -> None:
    """二次改进现有大纲：补全章节、统一质量、保持可解析格式。"""
    client = get_llm_client()
    if client is None:
        return
    if not (project.outline or "").strip():
        st.warning("当前没有可改进的大纲，请先生成或粘贴大纲。")
        return

    target_chapters, target_words, words_per_chapter = _outline_target_settings(project)
    constraints = _outline_global_constraints(project, target_chapters, target_words, words_per_chapter, include_preface)
    outline_template = PromptService.load_outline_prompt()
    prompt = _format_outline_prompt(
        outline_template,
        project,
        target_chapters=target_chapters,
        target_words=target_words,
        words_per_chapter=words_per_chapter,
        include_preface=include_preface,
        existing_outline=project.outline,
        instruction=f"""{constraints}
用户改进要求：{instruction or '补齐全书章节，强化上下文结构一致性、章节递进、每章写作思路和字数均衡。'}
改进重点：
1. 如果现有大纲只有第一章，必须扩展为完整 {target_chapters} 章。
2. 保留合理内容，但修复重复、断裂、章号缺失、编号错位、字数不均。
3. {'保留或新增序言，序言不计入章节。' if include_preface else '不要输出序言。'}
4. 输出必须使用：第X章、第一节、一、（一）、写作思路。""",
    )
    with st.spinner("AI 正在二次改进全书大纲…"):
        try:
            outline = _call_outline_model(client, prompt, project, max_tokens=9000)
            if _count_outline_chapters(outline) < target_chapters:
                st.warning("二次改进结果仍不完整，已自动改用分章生成补齐。")
                outline = _generate_outline_chapter_by_chapter(client, project, include_preface)
            project.outline = outline
            parsed_count = _parse_outline_text(project, outline, rerun=False)
            if parsed_count:
                st.success(f"二次改进完成，已解析 {parsed_count}/{target_chapters} 章。")
                save_project()
                st.rerun()
            else:
                st.error("二次改进返回了文本，但未解析出章节。已保留到大纲编辑框。")
        except Exception as e:
            st.error(f"二次改进失败：{e}")
            logger.exception("Outline improvement failed")

def render_editor_page() -> None:
    """渲染章节编辑器页面"""
    st.title(t('editor_title'))

    project: Optional[ProjectKnowledgeBase] = st.session_state.get("project_data")
    if project is None:
        st.warning(t('load_project_first'))
        return

    if not project.chapters:
        st.info(t('no_chapters_editor'))
        return

    # 章节选择：key 带章节签名和解析版本，确保大纲重解析后写章节页立即同步新章节列表。
    chapter_numbers = sorted(project.chapters.keys())
    chapter_labels = [
        f"{_format_chapter_label(n)} — {project.chapters[n].title or t('unnamed')}"
        for n in chapter_numbers
    ]
    outline_version = int(st.session_state.get("outline_parse_version", 0) or 0)
    chapter_signature = "_".join(str(n) for n in chapter_numbers)
    editor_select_key = f"editor_selected_idx_{outline_version}_{chapter_signature}"
    if int(st.session_state.get(editor_select_key, 0) or 0) >= len(chapter_numbers):
        st.session_state[editor_select_key] = 0
    selected_idx = st.selectbox(
        t('select_chapter'),
        range(len(chapter_numbers)),
        format_func=lambda i: chapter_labels[i],
        key=editor_select_key,
    )
    selected_ch_num = chapter_numbers[selected_idx]
    chapter = project.chapters[selected_ch_num]

    st.divider()

    with st.container(border=True):
        st.markdown("### 章节管理")
        st.caption("这里可直接删除写章节页中的错误章节；如果刚在“大纲”页重建，章节列表会按最新大纲同步刷新。")
        delete_cols = st.columns([1, 1, 2])
        with delete_cols[0]:
            confirm_delete_current = st.checkbox("确认删除当前章", key=f"editor_confirm_delete_ch_{selected_ch_num}")
            if st.button("删除当前章", key=f"editor_delete_ch_{selected_ch_num}", use_container_width=True, disabled=not confirm_delete_current):
                project.chapters.pop(selected_ch_num, None)
                if project.project_dir:
                    chapter_path = Path(project.project_dir) / f"chapter_{selected_ch_num}.md"
                    try:
                        if chapter_path.exists():
                            chapter_path.unlink()
                    except Exception as e:
                        st.warning(f"章节记录已删除，但正文文件删除失败：{e}")
                st.session_state["project_data"] = project
                st.session_state["outline_parse_version"] = int(st.session_state.get("outline_parse_version", 0) or 0) + 1
                save_project()
                st.success(f"已删除{_format_chapter_label(selected_ch_num)}。")
                st.rerun()
        with delete_cols[1]:
            confirm_delete_all = st.checkbox("确认清空全部", key="editor_confirm_delete_all_chapters")
            if st.button("清空全部章节", key="editor_delete_all_chapters", use_container_width=True, disabled=not confirm_delete_all):
                if project.project_dir:
                    for old_ch_num in list(project.chapters.keys()):
                        chapter_path = Path(project.project_dir) / f"chapter_{old_ch_num}.md"
                        try:
                            if chapter_path.exists():
                                chapter_path.unlink()
                        except Exception as e:
                            st.warning(f"{_format_chapter_label(old_ch_num)}正文文件删除失败：{e}")
                project.chapters = {}
                st.session_state["project_data"] = project
                st.session_state["outline_parse_version"] = int(st.session_state.get("outline_parse_version", 0) or 0) + 1
                save_project()
                st.success("已清空全部章节。请回到“大纲”页重新解析或生成章节。")
                st.rerun()
        with delete_cols[2]:
            st.info(f"当前共 {len(chapter_numbers)} 章；当前选择{_format_chapter_label(selected_ch_num, '《' + (chapter.title or '未命名') + '》')}。")

    st.divider()

    # 章节信息
    col1, col2 = st.columns([2, 1])
    with col1:
        st.subheader(f"{_format_chapter_label(selected_ch_num)} — {chapter.title or t('unnamed')}")
    with col2:
        section_count = len(chapter.sections) if chapter.sections else 0
        st.metric(t('writing_unit_count', n='').strip(': '), section_count)

    # 章节内容编辑 / 完整预览
    st.markdown(t('chapter_content'))
    chapter_file = Path(project.project_dir or "") / f"chapter_{selected_ch_num}.md" if project.project_dir else None
    full_chapter_content = ""
    if chapter_file and chapter_file.exists():
        try:
            from libriscribe.utils.file_utils import read_markdown_file
            full_chapter_content = read_markdown_file(str(chapter_file))
        except Exception:
            full_chapter_content = ""

    view_mode = st.radio(
        "章节显示方式",
        ["完整预览", "编辑原文"],
        horizontal=True,
        key=f"chapter_view_mode_{selected_ch_num}",
    )
    chapter_preview_placeholder = st.empty()
    st.session_state["editor_live_preview_chapter_num"] = selected_ch_num
    st.session_state["editor_live_preview_placeholder"] = chapter_preview_placeholder
    if view_mode == "完整预览":
        st.caption(f"当前章节约 {_count_manuscript_words(full_chapter_content)} 字。这里仅显示正文文件内容，不再把大纲摘要当作正文。")
        with chapter_preview_placeholder.container(border=True):
            st.markdown(full_chapter_content or "暂无章节正文。")
        content = full_chapter_content
        if full_chapter_content:
            st.download_button(
                "下载本章 Markdown 全文",
                data=full_chapter_content.encode("utf-8"),
                file_name=f"chapter_{selected_ch_num}.md",
                mime="text/markdown",
                use_container_width=True,
            )
    else:
        content = st.text_area(
            t('edit_content_label'),
            value=full_chapter_content,
            height=900,
            placeholder=t('content_placeholder'),
            key=f"editor_content_{selected_ch_num}",
        )

    with st.container(border=True):
        st.markdown("### 商用写作流水线")
        st.caption("建议顺序：① 先在“大纲”生成并二次改进全书目录 → ② 单章/小节生成 → ③ AI 审校 → ④ 局部优化 → ⑤ 导出。写作阶段已启用 raw HTTP 兜底、自动重试和空正文保护。")
        material_feedback = _material_usage_feedback(project, f"{chapter.title} {getattr(chapter, 'summary', '')}", max_items=3)
        if material_feedback:
            st.info("资料库可用性证明：\n" + material_feedback)
        else:
            st.warning("当前项目资料库暂无可用证据片段；正文生成将主要依赖大纲、项目描述和提示词。")
        status_items = [
            ("大纲", "已创建" if project.outline and project.chapters else "待完善"),
            ("当前章", getattr(chapter, "status", "pending") or "pending"),
            ("字数", f"{getattr(chapter, 'actual_word_count', 0) or _count_manuscript_words(full_chapter_content)} / {getattr(chapter, 'word_count', 0) or '未设'}"),
            ("写作单元", f"{sum(1 for sec in getattr(chapter, 'sections', []) if getattr(sec, 'status', '') == 'completed')} / {len(getattr(chapter, 'sections', []) or [])}"),
        ]
        st.markdown("　".join(f"**{name}：** {value}" for name, value in status_items))
        chapter_strength_prompt = st.text_area(
            "本章强化提示词（单章/小节生成前生效）",
            height=130,
            key=f"chapter_strength_prompt_{selected_ch_num}",
            placeholder=(
                "可填写本章特别要求，例如：强化职业教育场景、减少政策口号、增加图书馆实践机制分析、"
                "避免泛泛讨论等。该提示词只作用于当前章和本章小节生成。"
            ),
            help="自定义要求会注入章节写作提示词，但不能覆盖资料真实性、正文输出边界和语言规范。",
        )
        if chapter_strength_prompt.strip():
            st.caption("已为当前章启用强化提示词；点击“AI 写作”或“生成此小节”时会一并生效。")

    # 操作按钮
    col_save, col_ai, col_review, col_opt, col_visual, col_book = st.columns(6)
    with col_save:
        if st.button(t('save_chapter'), use_container_width=True, key="save_chapter"):
            if project.project_dir:
                from libriscribe.utils.file_utils import write_markdown_file
                write_markdown_file(str(Path(project.project_dir) / f"chapter_{selected_ch_num}.md"), content)
            chapter.summary = content[:500] + ("..." if len(content) > 500 else "")
            chapter.actual_word_count = _count_manuscript_words(content)
            project.chapters[selected_ch_num] = chapter
            st.session_state["project_data"] = project
            save_project()
    with col_ai:
        if st.button(t('ai_write'), use_container_width=True, key="ai_write"):
            _generate_chapter_with_ai(project, selected_ch_num, chapter_strength_prompt)
    with col_review:
        if st.button(t('ai_review'), use_container_width=True, key="ai_review"):
            _review_chapter_with_ai(project, selected_ch_num)
    with col_opt:
        if st.button(t('optimize_chapter'), use_container_width=True, key="optimize_chapter"):
            st.session_state["show_optimize_dialog"] = True
    with col_visual:
        if st.button("图文优化", use_container_width=True, key="visual_polish"):
            st.session_state["show_visual_polish_dialog"] = True
    with col_book:
        if st.button("生成全书", use_container_width=True, key="ai_write_book"):
            _generate_book_with_ai(project)

    # 二次优化对话框
    if st.session_state.get("show_optimize_dialog"):
        with st.container(border=True):
            st.markdown(f"### {t('optimize_title')}")
            st.caption(t('optimize_desc'))
            opt_location = st.text_input(
                t('optimize_location_label'),
                placeholder=t('optimize_location_placeholder'),
                key=f"opt_location_{selected_ch_num}",
            )
            opt_requirement = st.text_area(
                t('optimize_requirement_label'),
                placeholder=t('optimize_requirement_placeholder'),
                height=150,
                key=f"opt_requirement_{selected_ch_num}",
            )
            col_opt_ok, col_opt_cancel = st.columns(2)
            with col_opt_ok:
                if st.button(t('optimize_submit'), use_container_width=True, key="opt_submit"):
                    if not opt_location.strip() or not opt_requirement.strip():
                        st.warning(t('optimize_empty_warning'))
                    else:
                        st.session_state["show_optimize_dialog"] = False
                        _optimize_chapter_with_ai(project, selected_ch_num, opt_location.strip(), opt_requirement.strip(), full_chapter_content)
            with col_opt_cancel:
                if st.button(t('cancel'), use_container_width=True, key="opt_cancel"):
                    st.session_state["show_optimize_dialog"] = False

    if st.session_state.get("show_visual_polish_dialog"):
        with st.container(border=True):
            st.markdown("### 图文同步生成（可选）")
            st.caption("建议在正文已有内容后使用：从当前章节提炼表格、Mermaid 流程图、技术路线图或对比矩阵，作为二次润色资产。")
            visual_type = st.multiselect(
                "需要生成的图文类型",
                ["章节结构图", "技术路线图", "流程图", "对比矩阵", "指标体系表", "关键概念图"],
                default=["章节结构图", "对比矩阵"],
                key=f"visual_type_{selected_ch_num}",
            )
            visual_instruction = st.text_area(
                "图文优化要求",
                value="请基于当前章节正文生成可直接插入 Markdown 的表格和 Mermaid 图，不新增正文没有依据的事实。",
                height=120,
                key=f"visual_instruction_{selected_ch_num}",
            )
            col_visual_ok, col_visual_cancel = st.columns(2)
            with col_visual_ok:
                if st.button("生成图文优化提示", use_container_width=True, key="visual_submit"):
                    st.session_state["show_visual_polish_dialog"] = False
                    selected_types = "、".join(visual_type) if visual_type else "章节结构图"
                    visual_prompt = (
                        f"请基于{_format_chapter_label(selected_ch_num, '《' + (chapter.title or '未命名') + '》')}已生成正文，生成以下图文资产：{selected_types}。\n\n"
                        f"要求：{visual_instruction}\n\n"
                        "输出格式：\n"
                        "1. 先给出可插入正文的 Markdown 表格；\n"
                        "2. 再给出 Mermaid 图代码块；\n"
                        "3. 最后列出每个图表应插入到章节中的位置建议。\n\n"
                        "当前章节正文：\n"
                        f"{full_chapter_content[:6000]}"
                    )
                    st.session_state[f"visual_prompt_{selected_ch_num}"] = visual_prompt
                    st.success("已生成图文优化提示词，可复制到 AI 对话或后续多模态生成入口。")
            with col_visual_cancel:
                if st.button(t('cancel'), use_container_width=True, key="visual_cancel"):
                    st.session_state["show_visual_polish_dialog"] = False
            if st.session_state.get(f"visual_prompt_{selected_ch_num}"):
                st.text_area(
                    "图文优化提示词",
                    value=st.session_state[f"visual_prompt_{selected_ch_num}"],
                    height=260,
                    key=f"visual_prompt_preview_{selected_ch_num}",
                )

    with st.container(border=True):
        st.markdown("### 专著前后内容与参考文献")
        st.caption("这里单独生成/编辑“前言、结语、参考文献”。保存或生成后会自动进入最终书稿：前言在第一章前，结语在最后一章后，参考文献在结语后。")
        for part_key, meta in MANUSCRIPT_PARTS.items():
            current_part_content = _read_manuscript_part(project, part_key)
            has_effective_content = bool(_reference_entry_lines(current_part_content)) if part_key == "references" else bool(current_part_content.strip())
            with st.expander(f"{meta['title']} · {'已纳入书稿' if has_effective_content else '待生成'}", expanded=False):
                st.caption(meta["description"])
                generation_requirement = st.text_area(
                    f"{meta['title']}生成要求",
                    value="",
                    height=110,
                    key=f"manuscript_part_requirement_{part_key}",
                    placeholder=(
                        f"请写明你希望{meta['title']}重点回应的内容、写作角度、必须包含/避免的事项。"
                        "点击 AI 生成时会和专业提示词一起生效。"
                    ),
                )
                generation_options: dict[str, Any] = {}
                if part_key == "preface":
                    generation_options["forewordWordCount"] = st.number_input(
                        "前言预期字数",
                        min_value=300,
                        max_value=8000,
                        value=1500,
                        step=100,
                        key="manuscript_part_preface_word_count",
                    )
                elif part_key == "conclusion":
                    generation_options["conclusionWordCount"] = st.number_input(
                        "结语预期字数",
                        min_value=300,
                        max_value=8000,
                        value=1600,
                        step=100,
                        key="manuscript_part_conclusion_word_count",
                    )
                elif part_key == "references":
                    ref_col1, ref_col2, ref_col3 = st.columns(3)
                    with ref_col1:
                        generation_options["refStartYear"] = st.number_input(
                            "引用文献起始年份",
                            min_value=1900,
                            max_value=2100,
                            value=2019,
                            step=1,
                            key="manuscript_part_ref_start_year",
                        )
                    with ref_col2:
                        generation_options["refEndYear"] = st.number_input(
                            "引用文献结束年份",
                            min_value=1900,
                            max_value=2100,
                            value=2026,
                            step=1,
                            key="manuscript_part_ref_end_year",
                        )
                    with ref_col3:
                        generation_options["refCount"] = st.number_input(
                            "参考文献总数量（15-35条）",
                            min_value=15,
                            max_value=35,
                            value=30,
                            step=1,
                            key="manuscript_part_ref_count",
                        )
                    ref_col4, ref_col5 = st.columns(2)
                    with ref_col4:
                        generation_options["languageDistribution"] = st.text_input(
                            "文献语种分布",
                            value="以中文文献为主，可含少量权威英文文献",
                            key="manuscript_part_ref_language_distribution",
                        )
                    with ref_col5:
                        generation_options["citationStyle"] = st.text_input(
                            "引用格式",
                            value="GB/T 7714-2015",
                            key="manuscript_part_ref_citation_style",
                        )
                edited_part_content = st.text_area(
                    f"编辑{meta['title']}",
                    value=current_part_content,
                    height=260 if part_key != "references" else 320,
                    key=f"manuscript_part_{part_key}",
                    placeholder=f"可手动粘贴或点击下方按钮生成{meta['title']}。",
                )
                part_cols = st.columns(3)
                with part_cols[0]:
                    if st.button(f"保存{meta['title']}", key=f"save_manuscript_part_{part_key}", use_container_width=True):
                        try:
                            _write_manuscript_part(project, part_key, edited_part_content)
                            st.success(f"{meta['title']}已保存，并会自动纳入最终导出。")
                            st.rerun()
                        except Exception as e:
                            st.error(f"保存{meta['title']}失败：{e}")
                with part_cols[1]:
                    if st.button(f"AI生成{meta['title']}", key=f"generate_manuscript_part_{part_key}", use_container_width=True):
                        live_options = _manuscript_part_generation_options_from_state(part_key, generation_options)
                        _generate_manuscript_part_with_ai(project, part_key, generation_requirement, live_options)
                with part_cols[2]:
                    if current_part_content.strip():
                        st.download_button(
                            f"下载{meta['title']}MD",
                            data=current_part_content.encode("utf-8"),
                            file_name=str(meta["file"]),
                            mime="text/markdown",
                            key=f"download_manuscript_part_{part_key}",
                            use_container_width=True,
                        )
                st.caption(f"当前约 {_count_manuscript_words(edited_part_content)} 字。")

    # 后台任务进度已在 main() 全局渲染，此处不再重复调用

    # 如果有任务完成，重新加载项目数据以显示最新内容
    mgr = _get_task_manager()
    completed_write_tasks = [
        t for t in mgr.get_all_tasks().values()
        if t["status"] == "completed" and t["type"] in ("write_chapter", "write_book")
    ]
    if completed_write_tasks and st.button("刷新章节内容", key="refresh_after_task"):
        # 从文件重新加载项目数据
        project_file = st.session_state.get("project_file")
        if project_file:
            reloaded = ProjectKnowledgeBase.load_from_file(project_file)
            if reloaded:
                st.session_state["project_data"] = reloaded
                mgr.clear_completed()
                st.rerun()

    # 学术写作单元列表（替代旧版小说场景列表）
    st.divider()
    st.markdown(t('writing_unit_list'))
    if chapter.sections:
        # 判断叶子节点：有子节的小节只显示标题，不单独生成
        section_numbers = {sec.section_number for sec in chapter.sections}
        def _is_leaf_section(sn):
            for other in section_numbers:
                if other != sn and other.startswith(sn + "."):
                    return False
            return True

        for sec in chapter.sections:
            indent = "　" * (getattr(sec, 'level', 1) - 1)
            status = getattr(sec, 'status', 'pending') or 'pending'
            actual_wc = getattr(sec, 'actual_word_count', 0)
            is_leaf = _is_leaf_section(sec.section_number)
            status_label = {"completed": "已完成", "failed": "生成异常", "pending": "待写作", "word_count_soft_fail": "字数需复核"}.get(status, status)
            title = f"{indent}{_format_outline_section_label(sec.section_number, sec.title)}"
            meta = status_label if not actual_wc else f"{status_label} · 已生成约 {actual_wc} 字"
            with st.expander(f"{title} — {meta}"):
                if status == "word_count_soft_fail":
                    target_wc = getattr(sec, 'word_count_target', 0) or getattr(sec, 'word_count', 0) or 0
                    note = getattr(sec, 'word_count_note', '') or f"目标约 {target_wc} 字，当前约 {actual_wc} 字；已自动精简，请人工复核。"
                    st.warning(f"字数略超标，已自动精简并放行：{note}")
                st.write(f"**{t('writing_unit_level')}:** {getattr(sec, 'level', 1)}")
                st.write(f"**{t('writing_unit_goal')}:** {getattr(sec, 'summary', '') or sec.title or t('goal_unset')}")
                if getattr(sec, 'rag_query', ''):
                    st.write(f"**RAG Query:** {sec.rag_query}")
                if is_leaf:
                    if st.button("生成此小节", key=f"ai_write_section_{selected_ch_num}_{sec.section_number}"):
                        _generate_section_with_ai(project, selected_ch_num, sec.section_number, chapter_strength_prompt)
                else:
                    st.caption("此标题用于组织下级小节，生成章节时会按目录顺序写作其下内容。")
    else:
        st.info(t('no_writing_units'))
        if chapter.scenes:
            with st.expander(t('legacy_scene_compat')):
                st.caption(t('legacy_scene_compat_desc'))
                for scene in chapter.scenes:
                    st.write(f"- {scene.summary or scene.setting or t('scene_unset')}")

    # 参考文档（章节级别）
    st.divider()
    st.markdown("### 参考文档")
    if project.rag_documents:
        st.caption(f"已索引 {len(project.rag_documents)} 份参考文档")
        for doc_path in project.rag_documents:
            st.caption(str(doc_path))
    else:
        st.caption("暂无参考文档，请在项目设置中上传。")

    # 章节级参考文档上传
    chapter_ref_files = st.file_uploader(
        "为当前章节上传参考文档",
        type=["pdf", "docx", "txt", "md", "markdown", "html", "htm", "xlsx", "xls"],
        accept_multiple_files=True,
        key=f"chapter_ref_{selected_ch_num}",
        help="默认先导入资料库，不主动下载 HuggingFace embedding 模型。",
    )
    chapter_build_vector_index = st.checkbox(
        "同时建立向量索引（可能触发本地 embedding 模型下载）",
        value=False,
        key=f"chapter_build_vector_index_{selected_ch_num}",
    )
    if chapter_ref_files and st.button("📥 导入参考资料", key=f"index_ref_{selected_ch_num}"):
        _index_rag_documents(project, chapter_ref_files, build_vector_index=chapter_build_vector_index)

    # 术语表参考
    if project.terminology:
        st.divider()
        with st.expander(t('terminology_ref')):
            for term, defn in project.terminology.items():
                st.write(f"**{term}**: {defn}")


def _clean_path_text(value: Any) -> str:
    """清理从 session/project JSON 读取的路径文本，兼容误带引号/空白的 Windows 路径。"""
    text = str(value or "").strip().strip("\ufeff")
    quote_pairs = {'"': '"', "'": "'", "“": "”", "‘": "’", "《": "》", "「": "」", "『": "』"}
    changed = True
    while changed and len(text) >= 2:
        changed = False
        for left, right in quote_pairs.items():
            if text.startswith(left) and text.endswith(right):
                text = text[1:-1].strip()
                changed = True
                break
    return text.strip()


def _safe_project_dir_from_paths(project_dir_value: Any, project_file: str = "") -> Path:
    """从项目目录/项目文件推导可写目录，避免把 JSON 文件或带引号路径当成目录。"""
    project_dir_text = _clean_path_text(project_dir_value)
    project_file_text = _clean_path_text(project_file)
    if project_dir_text:
        project_dir = Path(project_dir_text)
        if project_dir.name.lower() == "knowledge_base.json" or project_dir.suffix.lower() == ".json":
            project_dir = project_dir.parent
    elif project_file_text:
        project_dir = Path(project_file_text).parent
    else:
        raise ValueError("项目目录为空，无法构造章节输出路径。")
    return project_dir


def _safe_chapter_number(chapter_num: Any) -> int:
    """将章节号规范化为正整数，避免非法编号进入文件名。"""
    try:
        normalized = int(chapter_num)
    except Exception as exc:
        raise ValueError(f"章节号无效：{chapter_num!r}，请重新选择章节。") from exc
    if normalized <= 0:
        raise ValueError(f"章节号无效：{chapter_num!r}，章节号必须大于 0。")
    return normalized


def _safe_section_filename_part(section_number: str) -> str:
    """把小节编号转换为 Windows/macOS/Linux 都可写入的安全文件名片段。"""
    safe = re.sub(r"[^\w_.-]+", "_", str(section_number or "").strip(), flags=re.UNICODE).strip("._- ")
    safe = re.sub(r"_+", "_", safe)[:80]
    if not safe:
        raise ValueError(f"小节编号无效：{section_number!r}，无法构造输出文件名。")
    reserved_names = {
        "CON", "PRN", "AUX", "NUL",
        "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
        "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
    }
    if safe.upper() in reserved_names:
        safe = f"section_{safe}"
    return safe


def _resolve_chapter_output_paths(project: ProjectKnowledgeBase, project_file: str, chapter_num: Any, section_number: str = "") -> tuple[Path, Path]:
    """统一构造并预检章节输出路径。

    Windows 上的 ``[Errno 22] Invalid argument`` 常来自非法路径/文件名。生成正文前
    先规范化项目目录、章节号和小节临时文件名，可以避免把文件系统错误误判为模型错误。
    """
    normalized_chapter = _safe_chapter_number(chapter_num)
    project_dir = _safe_project_dir_from_paths(getattr(project, "project_dir", ""), project_file)
    project.project_dir = str(project_dir)
    try:
        project_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OSError(
            f"项目目录不可写或路径非法：{project_dir}。请检查项目目录是否包含 Windows 不允许的字符（如 < > : \" | ? *），或重新加载/另存项目。"
        ) from exc

    chapter_path = project_dir / f"chapter_{normalized_chapter}.md"
    output_path = chapter_path
    if section_number:
        safe_section = _safe_section_filename_part(section_number)
        output_path = project_dir / f"chapter_{normalized_chapter}_section_{safe_section}.md"

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists() and output_path.is_dir():
            raise OSError(f"章节输出路径是目录而不是文件：{output_path}")
    except OSError as exc:
        raise OSError(f"章节输出目录不可写：{output_path.parent}。原始错误：{exc}") from exc
    return chapter_path, output_path


def _format_generation_error(error: Exception) -> str:
    """把章节生成异常转换为用户可执行的错误提示。"""
    if isinstance(error, (OSError, ValueError)):
        return (
            f"生成失败：{error}\n\n"
            "错误没有写入章节正文。当前更像是项目目录、章节输出文件或小节编号导致的文件系统错误，"
            "不是普通模型/API 错误。请确认项目目录可写、路径未带多余引号，且未包含 Windows 非法字符。"
        )
    return f"生成失败：{error}\n\n错误没有写入章节正文。请检查模型配置、API Base、模型名称或网络状态。"


def _section_heading_chain(project: ProjectKnowledgeBase, chapter_num: int, section_number: str) -> str:
    """构造章标题到当前叶子小节的完整标题链，用于实时预览和单小节文件合并。"""
    chapter = project.chapters.get(chapter_num) if getattr(project, "chapters", None) else None
    if chapter is None:
        return _format_chapter_label(chapter_num)
    headings = [f"# {_format_chapter_label(chapter_num, getattr(chapter, 'title', '') or '')}".strip()]
    sections = getattr(chapter, "sections", []) or []
    by_number = {str(getattr(sec, "section_number", "")): sec for sec in sections}
    parts = str(section_number or "").split(".")
    # 实时预览下方会单独渲染“当前正在生成的小节标题”，这里故意只保留父级链，
    # 避免出现“（一）标题 / （一）标题”的双标题。
    prefixes = [".".join(parts[:idx]) for idx in range(2, len(parts))]
    for prefix in prefixes:
        sec = by_number.get(prefix)
        if not sec:
            continue
        level = max(1, min(int(getattr(sec, "level", prefix.count(".")) or 1), 3))
        headings.append(f"{'#' * (level + 1)} {_format_outline_section_label(prefix, getattr(sec, 'title', '') or '')}")
    return "\n\n".join(headings).strip()


def _merge_section_content_into_chapter(chapter_path: Path, section_markdown: str, section_number: str, section_title: str = "") -> None:
    """把单独生成的小节内容合并到章节 Markdown；兼容旧数字标题和新中文标题。"""
    from libriscribe.agents.chapter_writer import ChapterWriterAgent
    from libriscribe.utils.file_utils import read_markdown_file, write_markdown_file

    existing = read_markdown_file(str(chapter_path)) if chapter_path.exists() else ""
    section_lines = section_markdown.strip().splitlines()
    while section_lines and section_lines[0].lstrip().startswith("# "):
        section_lines = section_lines[1:]
    new_block = "\n".join(section_lines).strip()
    if not new_block:
        return

    def _ensure_single_section_heading(block: str) -> str:
        lines = block.strip().splitlines()
        display_title = ChapterWriterAgent.format_outline_section_label(section_number, section_title)
        normalized_title = re.sub(r"[\s　]+", "", display_title)
        title_without_prefix = re.sub(r"^（[一二三四五六七八九十百]+）", "", normalized_title)
        while lines:
            first = lines[0].strip()
            heading_text = first.lstrip("#").strip() if first.startswith("#") else first
            normalized_heading = re.sub(r"[\s　]+", "", heading_text)
            heading_without_prefix = re.sub(r"^（[一二三四五六七八九十百]+）", "", normalized_heading)
            if normalized_title and (normalized_title in normalized_heading or normalized_heading in normalized_title or (title_without_prefix and title_without_prefix == heading_without_prefix)):
                lines = lines[1:]
                while lines and not lines[0].strip():
                    lines = lines[1:]
                continue
            break
        return f"#### {display_title}\n\n" + "\n".join(lines).strip()

    new_block = _ensure_single_section_heading(new_block)

    if not existing.strip():
        write_markdown_file(str(chapter_path), new_block + "\n")
        return

    lines = existing.splitlines()
    start_idx = None
    start_level = None
    heading_pattern = ChapterWriterAgent.section_heading_pattern(section_number, section_title)
    for idx, line in enumerate(lines):
        match = heading_pattern.match(line.strip())
        if match:
            start_idx = idx
            start_level = len(match.group(1))
            break

    if start_idx is None:
        merged = existing.rstrip() + "\n\n" + new_block + "\n"
        write_markdown_file(str(chapter_path), merged)
        return

    end_idx = len(lines)
    for idx in range(start_idx + 1, len(lines)):
        stripped = lines[idx].strip()
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            if level <= start_level:
                end_idx = idx
                break

    merged_lines = lines[:start_idx] + new_block.splitlines() + lines[end_idx:]
    write_markdown_file(str(chapter_path), "\n".join(merged_lines).rstrip() + "\n")


def _bg_write_chapter(project_file: str, chapter_num: int, provider: str,
                       api_base: str = "", api_key: str = "", model: str = "",
                       section_number: str = "") -> str:
    """后台线程：AI 撰写章节。从文件重新加载项目数据，完成后保存回文件。"""
    try:
        # 从文件重新加载项目（线程安全）
        project = ProjectKnowledgeBase.load_from_file(project_file)
        if project is None:
            return "ERROR: 无法加载项目数据"

        # 确保 project_dir 存在且不是误写入的 knowledge_base.json 文件路径。
        normalized_project_dir = _safe_project_dir_from_paths(getattr(project, "project_dir", ""), project_file)
        if str(getattr(project, "project_dir", "")) != str(normalized_project_dir):
            project.project_dir = str(normalized_project_dir)
            project.save_to_file(_clean_path_text(project_file))

        # 创建 LLM 客户端：来自统一模型档案的 provider/base/key/model
        client = LLMClient(llm_provider=provider, api_base=api_base, api_key=api_key, model=model)

        from libriscribe.agents.chapter_writer import ChapterWriterAgent
        writer = ChapterWriterAgent(client)

        # ChapterWriterAgent.execute() 返回 None，内容直接写入文件，并会更新内存中的小节状态/字数
        chapter_path, output_path = _resolve_chapter_output_paths(project, project_file, chapter_num, section_number)
        writer.execute(project, _safe_chapter_number(chapter_num), output_path=str(output_path), section_number=section_number or None)

        section_title = ""
        section_display = ""
        if section_number and chapter_num in project.chapters:
            chapter = project.chapters[chapter_num]
            for sec in chapter.sections:
                if sec.section_number == section_number:
                    section_title = sec.title
                    section_display = _format_outline_section_label(section_number, sec.title)
                    break

        if section_number and output_path.exists():
            from libriscribe.utils.file_utils import read_markdown_file
            section_content = read_markdown_file(str(output_path))
            _merge_section_content_into_chapter(chapter_path, section_content, section_number, section_title)
            if chapter_num in project.chapters:
                chapter = project.chapters[chapter_num]
                for sec in chapter.sections:
                    if sec.section_number == section_number:
                        sec.content_path = str(output_path)
                        break
                project.chapters[chapter_num] = chapter

        # 验证文件是否已生成，并在不重新加载项目的情况下持久化小节进度
        if chapter_path.exists():
            from libriscribe.utils.file_utils import read_markdown_file
            content = read_markdown_file(str(chapter_path))
            if content and chapter_num in project.chapters:
                chapter = project.chapters[chapter_num]
                chapter.summary = content[:500] + ("..." if len(content) > 500 else "")
                chapter.actual_word_count = _count_manuscript_words(content)
                chapter.status = "completed"
                project.chapters[chapter_num] = chapter
            project.save_to_file(project_file)
            if section_number:
                return f"{_format_chapter_label(chapter_num)} {section_display or _format_outline_section_label(section_number)} 小节已生成完成"
            return f"{_format_chapter_label(chapter_num)}已生成完成"
        else:
            project.save_to_file(project_file)
            return f"WARNING: {_format_chapter_label(chapter_num)}生成完成，但未找到输出文件"
    except ImportError:
        return "ERROR: ChapterWriter 模块不可用"
    except Exception as e:
        logger.exception("Background chapter generation failed")
        return f"ERROR: {_format_generation_error(e)}"


def _bg_write_book(project_file: str, provider: str, api_base: str = "", api_key: str = "",
                   model: str = "", progress_callback=None) -> str:
    """后台线程：按章节顺序生成全书，并持续更新整体进度。"""
    try:
        project = ProjectKnowledgeBase.load_from_file(project_file)
        if project is None:
            return "ERROR: 无法加载项目数据"

        chapter_numbers = sorted(project.chapters.keys())
        if not chapter_numbers:
            return "ERROR: 当前项目没有可生成的章节"

        total = len(chapter_numbers)
        completed = 0
        results = []
        if progress_callback:
            progress_callback(0.0, f"准备生成全书，共 {total} 章")

        for idx, chapter_num in enumerate(chapter_numbers, 1):
            chapter_label = _format_chapter_label(chapter_num)
            if progress_callback:
                progress_callback((idx - 1) / total, f"正在生成{chapter_label}（{idx}/{total}）")
            result = _bg_write_chapter(project_file, chapter_num, provider, api_base, api_key, model)
            results.append(result)
            if str(result).startswith("ERROR"):
                if progress_callback:
                    progress_callback(idx / total, f"{chapter_label}生成失败")
                return "全书生成中断：" + result
            completed += 1
            if progress_callback:
                progress_callback(idx / total, f"{chapter_label}完成（{idx}/{total}）")

        return f"全书生成完成：已生成 {completed}/{total} 章\n" + "\n".join(results)
    except Exception as e:
        logger.exception("Background book generation failed")
        return f"ERROR: {e}"


def _bg_review_chapter(project_file: str, chapter_num: int, provider: str,
                        api_base: str = "", api_key: str = "", model: str = "") -> str:
    """后台线程：AI 评审章节。"""
    try:
        project = ProjectKnowledgeBase.load_from_file(project_file)
        if project is None:
            return "ERROR: 无法加载项目数据"

        # 确保 project_dir 存在
        if not project.project_dir:
            project.project_dir = str(Path(project_file).parent)
            project.save_to_file(project_file)

        # 构建章节文件路径 — ContentReviewerAgent.execute() 接受 chapter_path: str
        chapter_path = str(Path(project.project_dir) / f"chapter_{chapter_num}.md")
        if not Path(chapter_path).exists():
            return f"ERROR: 章节文件不存在: {chapter_path}，请先撰写该章节"

        client = LLMClient(llm_provider=provider, api_base=api_base, api_key=api_key, model=model)

        from libriscribe.agents.content_reviewer import ContentReviewerAgent
        reviewer = ContentReviewerAgent(client)
        result = reviewer.execute(chapter_path)

        if result:
            # 保存评审结果到项目
            project = ProjectKnowledgeBase.load_from_file(project_file)
            if project is not None:
                review_text = ""
                if isinstance(result, dict):
                    review_text = "\n".join(f"**{k}:** {v}" for k, v in result.items())
                else:
                    review_text = str(result)
                # 保存评审结果到 chapter_reviews
                from libriscribe.knowledge_base import ChapterReview
                review = ChapterReview(
                    suggestions=[review_text],
                    reviewed_at=datetime.now().isoformat(),
                )
                if not hasattr(project, 'chapter_reviews'):
                    project.chapter_reviews = {}
                reviews_list = project.chapter_reviews.get(str(chapter_num), [])
                reviews_list.append(review)
                project.chapter_reviews[str(chapter_num)] = reviews_list
                project.save_to_file(project_file)
                return review_text
            return str(result)
        else:
            return "WARNING: AI 未能完成评审"
    except ImportError:
        return "ERROR: ContentReviewer 模块不可用"
    except Exception as e:
        logger.exception("Background chapter review failed")
        return f"ERROR: {e}"


def _run_live_chapter_generation(project: ProjectKnowledgeBase, chapter_num: int, section_number: str = "", chapter_strength_prompt: str = "") -> None:
    """在当前页面实时生成章节/小节，展示动态正文预览；错误不会写入正文文件。"""
    client = get_llm_client()
    if client is None:
        return

    project_file = _clean_path_text(st.session_state.get("project_file"))
    if not project_file:
        st.error("项目文件路径未找到，请重新加载项目。")
        return

    project.project_dir = str(_safe_project_dir_from_paths(getattr(project, "project_dir", ""), project_file))

    profile = _resolve_project_model_profile(project)
    if profile is None:
        st.warning("请先到「模型配置」页面配置并启用一个模型档案。")
        return

    project = _sync_project_model_fields(project, profile)
    st.session_state["project_data"] = project
    save_project()

    from libriscribe.agents.chapter_writer import ChapterWriterAgent
    from libriscribe.utils.file_utils import read_markdown_file

    try:
        chapter_path, output_path = _resolve_chapter_output_paths(project, project_file, chapter_num, section_number)
    except Exception as e:
        st.error(_format_generation_error(e))
        return

    section_title = ""
    section_display = ""
    if section_number and chapter_num in project.chapters:
        for sec in project.chapters[chapter_num].sections:
            if sec.section_number == section_number:
                section_title = sec.title
                section_display = _format_outline_section_label(section_number, sec.title)
                break
    title = _format_chapter_label(chapter_num) + (f" · {section_display or _format_outline_section_label(section_number)} 小节" if section_number else "")
    status_box = st.empty()
    progress_box = st.empty()
    preview_box = st.session_state.get("editor_live_preview_placeholder") if st.session_state.get("editor_live_preview_chapter_num") == chapter_num else None
    if preview_box is None:
        preview_box = st.empty()
    error_box = st.empty()

    existing_preview_prefix = read_markdown_file(str(chapter_path)) if chapter_path.exists() else ""
    if section_number and not existing_preview_prefix.strip():
        existing_preview_prefix = _section_heading_chain(project, _safe_chapter_number(chapter_num), section_number)
    live_sections: Dict[str, str] = {}
    progress_bar = progress_box.progress(0.0, text=f"准备生成 {title}...")
    writing_material_feedback = _material_usage_feedback(project, f"{title} {section_title}", max_items=5)
    if writing_material_feedback:
        st.info("正文生成资料库调用证明：\n" + writing_material_feedback)
    else:
        st.warning("正文生成前未找到可展示的资料库证据片段；建议先在资料页上传资料。")

    def progress_callback(current: int, total: int, section_title: str, status: str):
        progress = 0.0 if total <= 0 else min(current / total, 1.0)
        label = {
            "start": "正在生成",
            "retrying": "模型调用受阻，正在自动降级重试",
            "completed": "已完成",
            "failed_final": "连续重试失败，已停止写入以保护正文",
            "failed": "生成失败，已停止写入以保护正文",
        }.get(status, status)
        if status in {"failed", "failed_final"}:
            status_box.error(f"{label}：{section_title}（{current}/{total}）")
        elif status == "retrying":
            status_box.warning(f"{label}：{section_title}（{current}/{total}）")
        else:
            status_box.info(f"{label}：{section_title}（{current}/{total}）")
        progress_bar.progress(progress, text=f"{label}：{section_title}（{current}/{total}）")

    def content_callback(partial_text: str, section_title: str, current: int, total: int):
        writer_helper = ChapterWriterAgent(client)
        section_target = 0
        if section_number and chapter_num in project.chapters:
            for sec in getattr(project.chapters[chapter_num], "sections", []) or []:
                if writer_helper.format_outline_section_label(sec.section_number, getattr(sec, "title", "")) == section_title:
                    section_target = int(getattr(sec, "word_count", 0) or 0)
                    break
        cleaned_text = writer_helper._shape_preview_content(str(partial_text or ""), section_title, section_target or 800)
        live_sections[section_title] = cleaned_text
        preview = [existing_preview_prefix.strip()] if existing_preview_prefix.strip() else []
        for sec_title, sec_text in live_sections.items():
            preview.append(f"#### {sec_title}\n\n{sec_text.strip()}")
        with preview_box.container(border=True):
            st.markdown("\n\n".join(part for part in preview if part.strip()) if preview else "正在等待模型返回内容...")

    try:
        writer = ChapterWriterAgent(client)
        writer.execute(
            project,
            _safe_chapter_number(chapter_num),
            output_path=str(output_path),
            section_number=section_number or None,
            progress_callback=progress_callback,
            content_callback=content_callback,
            chapter_strength_prompt=chapter_strength_prompt,
        )

        if section_number and output_path.exists():
            section_content = read_markdown_file(str(output_path))
            _merge_section_content_into_chapter(chapter_path, section_content, section_number, section_title)

        if chapter_path.exists():
            content = read_markdown_file(str(chapter_path))
            if content:
                with preview_box.container(border=True):
                    st.markdown(content)
            if content and chapter_num in project.chapters:
                chapter = project.chapters[chapter_num]
                chapter.summary = content[:500] + ("..." if len(content) > 500 else "")
                chapter.actual_word_count = _count_manuscript_words(content)
                chapter.status = "completed"
                project.chapters[chapter_num] = chapter

        project.save_to_file(project_file)
        st.session_state["project_data"] = project
        progress_bar.progress(1.0, text=f"{title} 生成完成")
        if writing_material_feedback:
            st.session_state["last_generation_material_feedback"] = writing_material_feedback
            status_box.success(f"{title} 已生成并保存；已调用资料库参考。")
            st.info("生成完成资料引用证明：\n" + writing_material_feedback)
        else:
            status_box.success(f"{title} 已生成并保存。")
        st.toast(f"{title} 已生成完成", icon="✅")
    except Exception as e:
        logger.exception("Live chapter generation failed")
        error_box.error(_format_generation_error(e))
        st.toast("生成失败，错误未写入正文", icon="⚠️")


def _generate_chapter_with_ai(project: ProjectKnowledgeBase, chapter_num: int, chapter_strength_prompt: str = "") -> None:
    """使用 AI 实时生成章节内容。"""
    _run_live_chapter_generation(project, chapter_num, chapter_strength_prompt=chapter_strength_prompt)


def _generate_section_with_ai(project: ProjectKnowledgeBase, chapter_num: int, section_number: str, chapter_strength_prompt: str = "") -> None:
    """使用 AI 实时生成指定小节。"""
    _run_live_chapter_generation(project, chapter_num, section_number, chapter_strength_prompt=chapter_strength_prompt)


def _manuscript_part_chapter_overview(project: ProjectKnowledgeBase) -> str:
    """整理前言、结语、参考文献提示词可复用的章节概览与核心结论。"""
    lines = []
    project_dir = Path(project.project_dir) if project.project_dir else None
    for ch_num in sorted(project.chapters.keys()):
        ch = project.chapters[ch_num]
        summary = _clean_project_display_text(getattr(ch, "summary", ""))
        if not summary and project_dir:
            try:
                from libriscribe.utils.file_utils import read_markdown_file
                chapter_path = project_dir / f"chapter_{ch_num}.md"
                if chapter_path.exists():
                    summary = _clean_project_display_text((read_markdown_file(str(chapter_path)) or "")[:800])
            except Exception:
                summary = ""
        section_titles = "；".join(
            _format_outline_section_label(sec.section_number, sec.title)
            for sec in getattr(ch, "sections", [])[:8]
        )
        if section_titles and not summary:
            summary = f"本章围绕以下结构展开：{section_titles}"
        lines.append(f"  - 第{ch_num}章 {ch.title or '未命名'}\n    核心结论：{summary or '待根据章节标题与全书主题提炼。'}")
    return "\n".join(lines) or "  - 暂无章节结构，请基于书名、领域和用户要求审慎生成。"


def _manuscript_part_citation_context(project: ProjectKnowledgeBase) -> str:
    citations = []
    for citation in getattr(project, "citations", [])[:120]:
        formatted = (
            getattr(citation, "formatted_ref", "")
            or getattr(citation, "formatted", "")
            or getattr(citation, "raw_text", "")
            or getattr(citation, "title", "")
        )
        if formatted:
            citations.append(str(formatted).strip())
    material_context = _material_library_context(project, limit=6000, max_chunks=10)
    return f"""【平台已有可核验引用记录】
{chr(10).join(citations) or '暂无已保存 citation 记录。'}

【资料库可用依据片段】
{material_context or '暂无可用资料库片段。'}"""


def _reference_entry_lines(content: str) -> list[str]:
    """提取真实参考文献条目行，避免只有标题或 AI 内部资料被当作生成成功。"""
    lines = []
    invalid_markers = (
        "[ai_assistant]",
        "ai_analysis_not_verified_citation",
        "AI资料助手",
        "AI 资料助手",
        "头脑风暴",
        "检索词",
    )
    for raw_line in str(content or "").replace("\r\n", "\n").replace("\r", "\n").splitlines():
        line = raw_line.strip()
        if not line or re.fullmatch(r"#*\s*参考文献\s*", line):
            continue
        if any(marker.lower() in line.lower() for marker in invalid_markers):
            continue
        if re.search(r"\[[JMCDEPRZS]\]|^\s*\[?\d+\]?\s*[^\s]", line, flags=re.IGNORECASE):
            lines.append(line)
    return lines


def _project_reference_search_query(project: ProjectKnowledgeBase, requirement: str = "") -> str:
    """为参考文献兜底检索拼接尽量短、稳定的真实主题检索词。"""
    parts = [
        requirement,
        getattr(project, "title", ""),
        getattr(project, "project_name", ""),
        getattr(project, "genre", ""),
        getattr(project, "category", ""),
        getattr(project, "description", ""),
    ]
    for ch_num in sorted(getattr(project, "chapters", {}).keys()):
        ch = project.chapters[ch_num]
        parts.append(getattr(ch, "title", ""))
        parts.extend(getattr(sec, "title", "") for sec in getattr(ch, "sections", [])[:4])
    query = _join_project_context_parts(parts, separator=" ", limit=900)
    return query or str(getattr(project, "title", "") or getattr(project, "project_name", "") or "").strip()


def _project_existing_reference_text(project: ProjectKnowledgeBase) -> str:
    """从已导入 citation 和资料库来源拼出可保存的参考文献兜底文本。"""
    refs: list[str] = []
    seen: set[str] = set()

    def add_ref(value: str) -> None:
        ref = re.sub(r"^\s*\[?\d+\]?\s*", "", str(value or "").strip())
        ref = re.sub(r"\s+", " ", ref).strip()
        if not ref or ref in seen:
            return
        if not _reference_entry_lines(f"[1] {ref}"):
            return
        seen.add(ref)
        refs.append(ref)

    for citation in getattr(project, "citations", []) or []:
        add_ref(
            getattr(citation, "formatted_ref", "")
            or getattr(citation, "raw_text", "")
            or (getattr(citation, "metadata", {}) or {}).get("raw_reference", "")
            or getattr(citation, "source", "")
        )

    for doc in getattr(project, "source_documents", []) or []:
        metadata = getattr(doc, "metadata", {}) or {}
        source_type = str(getattr(doc, "source_type", "") or "Z")
        if source_type == "ai_assistant" or metadata.get("verification_status") == "ai_analysis_not_verified_citation":
            continue
        title = getattr(doc, "title", "") or getattr(doc, "file_name", "")
        if not title:
            continue
        authors = "，".join(getattr(doc, "authors", []) or [])
        year = getattr(doc, "year", "") or ""
        publisher = metadata.get("publisher", "")
        url = getattr(doc, "url", "")
        doi = getattr(doc, "doi", "")
        isbn = getattr(doc, "isbn", "")
        if publisher and year:
            add_ref(f"{authors + '．' if authors else ''}{title}[{source_type}]．{publisher}，{year}．")
        elif url or doi or isbn:
            suffix = url or (f"DOI:{doi}" if doi else f"ISBN:{isbn}")
            add_ref(f"{authors + '．' if authors else ''}{title}[{source_type}/OL]．{year or '出版年不详'}．{suffix}")

    if not refs:
        return ""
    return "参考文献\n\n" + "\n".join(f"[{idx}] {ref}" for idx, ref in enumerate(refs, 1))


def _openalex_reference_fallback_text(project: ProjectKnowledgeBase, requirement: str = "", options: Optional[dict[str, Any]] = None) -> str:
    """AI 参考文献生成超时时，直接用 OpenAlex 检索真实文献并写入 citation 记录。"""
    options = options or {}
    query = _project_reference_search_query(project, requirement)
    if not query:
        return ""
    ref_count = max(15, min(35, int(options.get("refCount") or 30)))
    ref_start_year = int(options.get("refStartYear") or 2019)
    ref_end_year = int(options.get("refEndYear") or 2026)
    language_distribution = str(options.get("languageDistribution") or "")
    language_filter = "zh" if "中文" in language_distribution and "英文" not in language_distribution else "all"
    service = LiteratureSearchService()
    try:
        diagnostics = service.search_with_diagnostics(
            query,
            limit=min(10, ref_count),
            api_key=str(st.session_state.get("openalex_api_key", "") or ""),
            recent_years=None,
            journal_only=True,
            timeout=12,
            search_mode="semantic" if len(query) > 80 else "keyword",
            language_filter=language_filter,
        )
    except Exception:
        logger.exception("OpenAlex reference fallback failed")
        return ""
    citations: list[str] = []
    for item in diagnostics.get("items") or []:
        year = _safe_int(item.get("publication_year"), 0)
        if year and not (ref_start_year <= year <= ref_end_year):
            continue
        formatted = service.format_citation(item, len(citations) + 1)
        if formatted and _reference_entry_lines(formatted):
            citations.append(formatted)
        if len(citations) >= ref_count:
            break
    if not citations:
        return ""
    try:
        service.import_formatted_citations(project, citations, keywords=query)
    except Exception:
        logger.exception("Import OpenAlex fallback citations failed")
    return "参考文献\n\n" + "\n".join(citations)


def _build_manuscript_part_prompt(
    project: ProjectKnowledgeBase,
    part_key: str,
    requirement: str = "",
    options: Optional[dict[str, Any]] = None,
) -> str:
    """根据用户补充要求和专用模板生成前言、结语、参考文献提示词。"""
    if part_key not in MANUSCRIPT_PARTS:
        raise ValueError("未知的专著组成部分。")
    options = options or {}
    book_title = project.title or project.project_name
    author = _project_author_text(project)
    field = project.genre or getattr(project, "category", "") or "未指定学科/领域"
    user_requirement = (requirement or "").strip() or "无额外要求，请严格遵循本专业提示词与项目上下文。"
    chapters = _manuscript_part_chapter_overview(project)
    common_context = f"""【用户补充要求】
{user_requirement}

【项目说明与读者】
- 项目说明：{_clean_project_display_text(getattr(project, 'description', '')) or '未填写'}
- 目标读者：{getattr(project, 'target_audience', '') or '未填写'}"""

    if part_key == "preface":
        target_words = _target_word_count_for_part(part_key, options)
        min_words = int(target_words * 0.92)
        max_words = int(target_words * 1.08)
        return f"""【系统指令】
你是一名学术专著撰写专家。你的唯一任务是为指定的专著生成“前言”。输出必须是纯文本的前言正文，不包含“前言”二字标题，不包含任何其他内容。

【任务参数】
- 专著名称：{book_title}
- 作者：{author}
- 全书所属学科/领域：{field}
- 前言预期字数：{target_words} 字；绝对允许范围：{min_words}—{max_words} 字

【全书结构概览】（你撰写的所有内容必须紧扣此框架）
{chapters}

{common_context}

【写作要求】
1. 前言应包含：
   - 研究背景与问题意识：阐述本领域现状、核心矛盾，以及撰写本书的缘由。
   - 全书主旨与目标：用凝练语言阐明本书要解决的核心问题、核心主张。
   - 内容导览：基于给定的全书结构，简要说明每一章的研究重点及其逻辑关联。
   - 致谢（若有）：用自然的方式融入，不单独设节，点到为止。
2. 语言风格：学术、平实、客观。禁止使用“在当今时代”“随着……发展”“众所周知”等空泛套话。禁止使用“极大地”“颠覆性地”等夸张副词。保持陈述句为主。
3. 不得超出给定框架虚构章节或内容。

【字数规定 - 绝对红线】
- 前言全文必须严格控制在 {target_words} 字左右，允许偏差上下不超过 8%，即 {min_words}—{max_words} 字。
- 生成完毕后你必须自己统计中文字符数（不含空格和标题）并校验；如果超出范围，必须立刻重写精简或补足，直到达标。
- 自检用的“实际字数”报告只能用于你内部校验，最终输出绝对不能包含任何字数统计。

【输出规则】
- 直接输出前言正文第一段；不得输出“前言”二字，不得输出 Markdown 标题。
- 正文结束后直接结束，不留任何空格、换行以外的符号。
- 绝对禁止输出：字数统计、自评、评分、附录、术语表、任何标记线（如“#####”）。
"""

    if part_key == "conclusion":
        target_words = _target_word_count_for_part(part_key, options)
        min_words = int(target_words * 0.92)
        max_words = int(target_words * 1.08)
        foreword_core_summary = _read_manuscript_part(project, "preface")[:1600]
        return f"""【系统指令】
你是一名学术专著撰写专家。你的唯一任务是为指定的专著生成“结语”。输出必须是纯文本的结语正文，不包含“结语”二字标题，不包含任何其他内容。

【任务参数】
- 专著名称：{book_title}
- 作者：{author}
- 全书所属学科/领域：{field}
- 结语预期字数：{target_words} 字；绝对允许范围：{min_words}—{max_words} 字

【全书各章核心结论】（你必须据此总结，不得偏离）
{chapters}

【前言核心问题与主张】（用于形成前后闭环，若平台未提供则忽略此条）
{foreword_core_summary or '平台尚未提供前言内容。'}

{common_context}

【写作要求】
1. 结语必须包含：
   - 全书主要发现与贡献：提炼全书各章共通的核心成果，形成一个整体性的学术判断。
   - 实践启示与理论价值（若适用）：指出本成果对领域实践的指导意义。
   - 研究局限与未来方向：客观、诚实地点出未解决的问题，提出后续可深入的2-3个方向。
2. 必须与前言形成呼应：若前言提出了核心问题或预设，结语须对此作出明确回答。保持术语、论调一致。
3. 语言风格：与前言一致，学术、平实、不夸大。

【字数规定 - 绝对红线】
- 结语全文必须严格控制在 {target_words} 字左右，允许偏差上下不超过 8%，即 {min_words}—{max_words} 字。
- 生成完毕后你必须自己统计中文字符数（不含空格和标题）并校验；如果超出范围，必须立刻重写精简或补足，直到达标。
- 自检用的“实际字数”报告只能用于你内部校验，最终输出绝对不能包含任何字数统计。

【输出规则】
- 直接输出结语正文第一段；不得输出“结语”二字，不得输出 Markdown 标题。
- 正文结束后直接结束，不允许任何附加信息。
- 绝对禁止：字数统计、自评、评分、附录、术语表、任何分隔标记。
"""

    ref_start_year = int(options.get('refStartYear') or 2019)
    ref_end_year = int(options.get('refEndYear') or 2026)
    ref_count = max(15, min(35, int(options.get('refCount') or 30)))
    citation_style = options.get('citationStyle') or 'GB/T 7714-2015'
    language_distribution = options.get('languageDistribution') or '以中文文献为主，可含少量权威英文文献'
    template = PromptService.load_global_prompt("manuscript_references")
    values = {
        "book_title": book_title,
        "author": author,
        "field": field,
        "ref_count": ref_count,
        "ref_start_year": ref_start_year,
        "ref_end_year": ref_end_year,
        "citation_style": citation_style,
        "language_distribution": language_distribution,
        "chapters": chapters,
        "common_context": common_context,
        "citation_context": _manuscript_part_citation_context(project),
        "user_requirement": user_requirement,
    }
    try:
        return template.format(**values)
    except Exception as e:
        logger.warning("Global manuscript reference prompt format failed; using built-in template: %s", e)
        return PromptService.load_builtin_template("manuscript_references").format(**values)


def _friendly_llm_generation_error(part_title: str, error: Exception, client: Optional[LLMClient] = None) -> str:
    """把模型接口错误转换成用户能直接处理的网页提示。"""
    details = " | ".join(
        part for part in [
            str(error or "").strip(),
            str(getattr(client, "last_error", "") or "").strip() if client is not None else "",
            str(getattr(client, "last_response_preview", "") or "").strip()[:500] if client is not None else "",
        ]
        if part
    )
    normalized = details.lower()
    if any(code in normalized for code in ("401", "invalid api key", "unauthorized")):
        reason = "API Key 无效或已失效"
        action = "请到「模型设置」重新填写并测试 API Key。"
    elif any(code in normalized for code in ("422", "model not found", "not found")):
        reason = "当前模型名称不可用或供应商不支持"
        action = "请到「模型设置」把模型名改为该接口真实支持的模型后再测试。"
    elif any(code in normalized for code in ("429", "too many requests", "rate limit")):
        reason = "模型接口限流或额度不足"
        action = "请稍后重试，或切换到可用额度更高的模型档案。"
    elif any(code in normalized for code in ("504", "524", "gateway timeout", "timeout", "timed out")):
        reason = "模型接口超时"
        action = "本次已快速停止，避免页面一直转圈；请降低文献数量、切换模型，或先用「资料与检索」里的 OpenAlex 生成真实引用。"
    else:
        reason = "模型接口未返回有效内容"
        action = "请检查模型配置、网络和供应商状态后重试。"
    detail_suffix = f"\n\n接口返回：{details[:800]}" if details else ""
    return f"生成{part_title}失败：{reason}。{action}{detail_suffix}"


def _generate_manuscript_part_with_ai(
    project: ProjectKnowledgeBase,
    part_key: str,
    requirement: str = "",
    options: Optional[dict[str, Any]] = None,
) -> None:
    """单独生成前言、结语或参考文献，并保存到项目正文组成文件。"""
    client = get_llm_client()
    if client is None:
        return
    if part_key not in MANUSCRIPT_PARTS:
        st.error("未知的专著组成部分。")
        return
    project_file = st.session_state.get("project_file")
    if project_file and not project.project_dir:
        project.project_dir = str(Path(project_file).parent)
    try:
        options = _manuscript_part_generation_options_from_state(part_key, options)
        target_words = _target_word_count_for_part(part_key, options)
        part_title = MANUSCRIPT_PARTS[part_key]['title']
        prompt = _build_manuscript_part_prompt(project, part_key, requirement, options)
        generation_kwargs: dict[str, Any] = {"max_tokens": 6000, "temperature": 0.25}
        existing_reference_text = ""
        if part_key == "references":
            existing_reference_text = str(st.session_state.get("manuscript_part_references") or _read_manuscript_part(project, "references") or "").strip()
            generation_kwargs.update({"max_tokens": 1200, "temperature": 0.2, "timeout_seconds": 75, "raw_attempt_limit": 2})
        with st.spinner(f"AI 正在生成{part_title}…"):
            content = client.generate_content(prompt, **generation_kwargs)
        if not content and getattr(client, "last_error", ""):
            if part_key == "references":
                fallback_refs = _project_existing_reference_text(project)
                if not fallback_refs:
                    fallback_refs = _openalex_reference_fallback_text(project, requirement, options)
                if fallback_refs:
                    st.warning("模型接口超时，已改用项目真实 citation/来源记录或 OpenAlex 检索结果生成参考文献，避免保存空内容。")
                    content = fallback_refs
                elif _reference_entry_lines(existing_reference_text):
                    st.warning("模型接口超时，已保留编辑框中已有的有效参考文献，未写入空内容。")
                    content = existing_reference_text
                else:
                    raise RuntimeError(getattr(client, "last_error"))
            else:
                raise RuntimeError(getattr(client, "last_error"))
        cleaned = _sanitize_generated_manuscript_part(part_key, str(content or "").strip())
        if part_key == "references" and not _reference_entry_lines(cleaned):
            repaired_refs = ""
            if cleaned.strip():
                repair_prompt = f"""请把下面 AI 已生成的参考文献内容整理为标准参考文献列表。

硬性要求：
1. 只输出“参考文献”标题和逐条参考文献，不输出解释、说明、自评或过程。
2. 每条单独一行，并使用 [1]、[2]、[3] 编号。
3. 每条尽量补齐文献类型标识，如 [M]、[J]、[D]、[C]、[R]。
4. 不新增你不确定的信息；如果原文只有不完整条目，也要保留可识别的作者、题名、年份等信息。

待整理内容：
{cleaned}
"""
                try:
                    repaired_refs = client.generate_content(repair_prompt, max_tokens=1200, temperature=0.1, timeout_seconds=45, raw_attempt_limit=1)
                except Exception:
                    logger.exception("AI reference format repair failed")
            if repaired_refs and _reference_entry_lines(repaired_refs):
                cleaned = _sanitize_generated_manuscript_part(part_key, repaired_refs)
                st.warning("AI 首次返回的参考文献格式不规范，已自动调用 AI 重新整理为参考文献列表。")
            elif cleaned.strip():
                st.warning("AI 已返回参考文献内容，但格式未被系统识别为标准条目；已写入正文供你在页面继续编辑，不再强制要求项目已有 citation。")
            else:
                fallback_refs = _project_existing_reference_text(project)
                if not fallback_refs:
                    fallback_refs = _openalex_reference_fallback_text(project, requirement, options)
                if fallback_refs:
                    cleaned = _sanitize_generated_manuscript_part(part_key, fallback_refs)
                    st.warning("AI 未返回内容，已改用项目真实 citation/来源记录或 OpenAlex 检索结果生成参考文献。")
                elif _reference_entry_lines(existing_reference_text):
                    cleaned = _sanitize_generated_manuscript_part(part_key, existing_reference_text)
                    st.warning("AI 未返回内容，已保留编辑框中已有的有效参考文献。")
                else:
                    st.error("参考文献生成失败：模型没有返回可写入内容。请稍后重试或切换模型档案。")
                    return
        if part_key in {"preface", "conclusion"} and target_words:
            min_words = int(target_words * 0.92)
            max_words = int(target_words * 1.08)
            actual_words = _count_manuscript_words(cleaned)
            retry_count = 0
            while (actual_words < min_words or actual_words > max_words) and retry_count < 3:
                direction = "大幅压缩删减" if actual_words > max_words else "补足有效内容"
                revision_prompt = f"""请严格重写以下{MANUSCRIPT_PARTS[part_key]['title']}正文，必须{direction}到 {min_words}—{max_words} 字之间，目标值 {target_words} 字。

当前内部统计字数：{actual_words} 字。这个统计只用于你判断，不得输出。

硬性要求：
1. 不得输出“{MANUSCRIPT_PARTS[part_key]['title']}”标题。
2. 不得输出【实际字数】或任何字数统计。
3. 只输出最终达标正文，不要解释。
4. 如果原文过长，必须删除次要背景、重复表述和泛泛铺垫，不能继续扩写。

原正文：
{cleaned}"""
                content = client.generate_content(revision_prompt, max_tokens=6000, temperature=0.15)
                cleaned = _sanitize_generated_manuscript_part(part_key, str(content or "").strip())
                actual_words = _count_manuscript_words(cleaned)
                retry_count += 1
            if actual_words > max_words:
                st.error(
                    f"{MANUSCRIPT_PARTS[part_key]['title']}重写后仍明显超标：目标 {target_words} 字，允许范围 {min_words}—{max_words} 字，当前约 {actual_words} 字。"
                    "为保证文章质量，系统不会机械裁剪正文；请减少补充要求、降低内容复杂度，或切换遵循字数更稳定的模型后重新生成。"
                )
                return
            if actual_words < min_words:
                st.error(
                    f"{MANUSCRIPT_PARTS[part_key]['title']}重写后仍低于设定下限：目标 {target_words} 字，允许范围 {min_words}—{max_words} 字，当前约 {actual_words} 字。"
                    "为保证文章完整性，系统不会强行拼接凑字；请补充写作要求后重新生成。"
                )
                return
        if not cleaned:
            st.error(f"{MANUSCRIPT_PARTS[part_key]['title']}生成结果为空，未写入正文。")
            return
        _write_manuscript_part(project, part_key, cleaned)
        st.session_state["project_data"] = project
        save_project()
        st.success(f"{MANUSCRIPT_PARTS[part_key]['title']}已生成并自动纳入最终书稿顺序。")
        st.rerun()
    except Exception as e:
        logger.exception("Generate manuscript part failed: %s", part_key)
        st.error(_friendly_llm_generation_error(MANUSCRIPT_PARTS[part_key]['title'], e, client))

def _generate_book_with_ai(project: ProjectKnowledgeBase) -> None:
    """前台逐章生成全书：实时显示当前章，避免后台任务看起来“没有作用”。"""
    client = get_llm_client()
    if client is None:
        return

    project_file = _clean_path_text(st.session_state.get("project_file"))
    if not project_file:
        st.error("项目文件路径未找到，请重新加载项目。")
        return

    project.project_dir = str(_safe_project_dir_from_paths(getattr(project, "project_dir", ""), project_file))

    if not project.chapters:
        st.warning("当前项目没有可生成的章节，请先在大纲页创建章节。")
        return

    profile = _resolve_project_model_profile(project)
    if profile is None:
        st.warning("请先到「模型配置」页面配置并启用一个模型档案。")
        return

    project = _sync_project_model_fields(project, profile)
    st.session_state["project_data"] = project
    save_project()

    from libriscribe.agents.chapter_writer import ChapterWriterAgent
    from libriscribe.utils.file_utils import read_markdown_file

    chapter_numbers = sorted(project.chapters.keys())
    total = len(chapter_numbers)
    writer = ChapterWriterAgent(client)
    overall_box = st.empty()
    current_box = st.empty()
    preview_box = st.empty()
    overall_progress = st.progress(0.0, text=f"准备逐章生成全书，共 {total} 章")

    for idx, chapter_num in enumerate(chapter_numbers, 1):
        # 不能在编辑器 selectbox 已实例化后再修改同名 widget state，
        # 否则 Streamlit 会抛出 StreamlitAPIException。全书生成只更新独立状态用于提示。
        st.session_state["book_generation_current_chapter"] = chapter_num
        chapter_title = project.chapters[chapter_num].title or "未命名"
        chapter_label = _format_chapter_label(chapter_num)
        chapter_display = _format_chapter_label(chapter_num, f"《{chapter_title}》")
        overall_box.info(f"正在生成{chapter_display}（{idx}/{total}）。生成完成后会自动进入下一章。")
        overall_progress.progress((idx - 1) / total, text=f"正在生成{chapter_label}（{idx}/{total}）")
        chapter_progress = current_box.progress(0.0, text=f"{chapter_label}准备中…")
        live_sections: Dict[str, str] = {}

        try:
            chapter_path, output_path = _resolve_chapter_output_paths(project, project_file, chapter_num, "")

            def progress_callback(current: int, section_total: int, section_title: str, status: str):
                progress = 0.0 if section_total <= 0 else min(current / section_total, 1.0)
                label = {"start": "正在生成", "retrying": "自动重试", "completed": "已完成", "failed": "生成失败", "failed_final": "生成失败"}.get(status, status)
                chapter_progress.progress(progress, text=f"{chapter_label}：{label} {section_title}（{current}/{section_total}）")

            def content_callback(partial_text: str, section_title: str, current: int, section_total: int):
                writer_helper = ChapterWriterAgent(client)
                section_target = 0
                for sec in getattr(project.chapters.get(chapter_num), "sections", []) or []:
                    if writer_helper.format_outline_section_label(sec.section_number, getattr(sec, "title", "")) == section_title:
                        section_target = int(getattr(sec, "word_count", 0) or 0)
                        break
                live_sections[section_title] = writer_helper._shape_preview_content(str(partial_text or ""), section_title, section_target or 800)
                preview = []
                for sec_title, sec_text in live_sections.items():
                    preview.append(f"#### {chapter_label} · {sec_title}\n\n{sec_text.strip()}")
                preview_box.markdown("\n\n".join(preview) if preview else "正在等待模型返回内容…")

            writer.execute(
                project,
                _safe_chapter_number(chapter_num),
                output_path=str(output_path),
                progress_callback=progress_callback,
                content_callback=content_callback,
            )

            if chapter_path.exists():
                content = read_markdown_file(str(chapter_path))
                chapter = project.chapters[chapter_num]
                chapter.summary = content[:500] + ("..." if len(content) > 500 else "")
                chapter.actual_word_count = _count_manuscript_words(content)
                chapter.status = "completed"
                project.chapters[chapter_num] = chapter
                project.save_to_file(project_file)
            chapter_progress.progress(1.0, text=f"{chapter_display}已完成")
        except Exception as e:
            logger.exception("Live book generation failed at chapter %s", chapter_num)
            st.error(f"全书生成在{chapter_label}中断：{_format_generation_error(e)}")
            project.save_to_file(project_file)
            st.session_state["project_data"] = project
            return

        overall_progress.progress(idx / total, text=f"已完成{chapter_label}（{idx}/{total}）")

    st.session_state["project_data"] = project
    st.success(f"全书生成完成：已按章节顺序生成 {total} 章。")
    st.toast("全书逐章生成完成", icon="✅")


def _review_chapter_with_ai(project: ProjectKnowledgeBase, chapter_num: int) -> None:
    """使用 AI 后台评审章节"""
    client = get_llm_client()
    if client is None:
        return

    project_file = st.session_state.get("project_file")
    if not project_file:
        st.error("项目文件路径未找到，请重新加载项目。")
        return

    profile = _resolve_project_model_profile(project)
    if profile is None:
        st.warning("请先到「模型配置」页面配置并启用一个模型档案。")
        return
    project = _sync_project_model_fields(project, profile)
    st.session_state["project_data"] = project
    save_project()
    provider = profile.get("provider", "openai")
    api_base = profile.get("api_base", "")
    api_key = profile.get("api_key", "")
    model = profile.get("model", "")

    mgr = _get_task_manager()
    chapter_label = _format_chapter_label(chapter_num)
    task_id = mgr.start_task(
        task_type="review_chapter",
        task_func=_bg_review_chapter,
        task_args=(project_file, chapter_num, provider, api_base, api_key, model),
        description=f"AI 评审{chapter_label}",
    )
    st.session_state["active_task_id"] = task_id
    st.info(f"🚀 已启动后台任务：AI 评审{chapter_label}。您可以继续其他操作。")
    time.sleep(1)
    st.rerun()


def _optimize_chapter_with_ai(project: ProjectKnowledgeBase, chapter_num: int,
                               location: str, requirement: str, current_content: str) -> None:
    """使用 AI 对章节进行二次优化（局部修改，不重写整章）。"""
    client = get_llm_client()
    if client is None:
        return

    if not current_content.strip():
        st.warning(t('optimize_no_content'))
        return

    from libriscribe.utils.academic_prompt import ACADEMIC_MONOGRAPH_SYSTEM_PROMPT

    # 构建二次优化提示词
    optimize_prompt = f"""{ACADEMIC_MONOGRAPH_SYSTEM_PROMPT}

## 二次优化指令

请对以下章节内容进行二次优化。严格遵守"二次优化规则"：只修改用户明确指出的部分，保持其他内容不变。

**定位**：{location}

**要求**：{requirement}

**当前章节全文**：
---
{current_content}
---

请输出【优化结果】，然后输出修改后的内容。如果修改涉及全局格式，则输出全局替换后的完整章节；否则只输出修改后的那段内容。"""

    with st.spinner(t('optimize_processing')):
        try:
            result = client.generate_content(optimize_prompt, max_tokens=8000, temperature=0.3)
            if not result or not result.strip():
                st.warning(t('optimize_no_result'))
                return

            # 提取优化结果
            optimized_content = result.strip()
            # 如果包含【优化结果】标记，提取其后的内容
            marker_match = re.search(r'【优化结果】\s*\n', optimized_content)
            if marker_match:
                optimized_content = optimized_content[marker_match.end():].strip()

            # 判断是否是完整章节（包含章标题）还是局部片段
            is_full_chapter = bool(re.search(r'^#\s+第', optimized_content)) or \
                              bool(re.search(r'^第[一二三四五六七八九十百千\d]+章', optimized_content))

            if is_full_chapter:
                # 全局替换：用优化后的完整章节替换原文
                new_content = optimized_content
            else:
                # 局部替换：尝试在原文中找到定位部分并替换
                # 简单策略：将优化片段追加到原文末尾，用户手动合并
                new_content = current_content + "\n\n---\n\n【二次优化结果 — " + location + "】\n\n" + optimized_content

            # 保存到文件
            if project.project_dir:
                from libriscribe.utils.file_utils import write_markdown_file
                chapter_path = Path(project.project_dir) / f"chapter_{chapter_num}.md"
                if is_full_chapter:
                    write_markdown_file(str(chapter_path), new_content)
                else:
                    # 局部优化：先保存原文，优化片段追加在分隔线后供用户参考
                    write_markdown_file(str(chapter_path), new_content)

            # 更新项目数据
            chapter = project.chapters[chapter_num]
            if is_full_chapter:
                chapter.summary = new_content[:500] + ("..." if len(new_content) > 500 else "")
                chapter.actual_word_count = _count_manuscript_words(new_content)
            project.chapters[chapter_num] = chapter
            st.session_state["project_data"] = project
            save_project()

            # 显示优化结果
            st.success(t('optimize_success'))
            with st.container(border=True):
                if is_full_chapter:
                    st.markdown("**全局优化结果（已替换整章）：**")
                    st.markdown(new_content)
                else:
                    st.markdown(f"**局部优化结果（定位：{location}）：**")
                    st.markdown(optimized_content)
                    st.caption(t('optimize_manual_merge_hint'))

        except Exception as e:
            st.error(t('optimize_fail', e=e))
            logger.exception("Chapter optimization failed")


def _floating_chat_context_prompt(page: str, user_message: str) -> str:
    """为悬浮聊天补充页面上下文，让 AI 能围绕首页/大纲/写作内容给可执行修改建议。"""
    page_hint = {
        "Workspace": "你正在首页/项目驾驶舱，请优先帮助用户明确项目定位、下一步流程和全书生产路径。",
        "Projects": "你正在项目页，请优先帮助用户完善书名、方向、目标读者、书型和项目描述。",
        "Outline": "你正在第三步大纲生成页，请优先帮助用户调整章数、章节层级、第一章/第一节/一、/（一）结构和写作思路，并给出可直接粘贴解析的大纲文本。",
        "Editor": "你正在第四步写文章页，请优先帮助用户基于已生成章节做局部修改、续写、润色、补证据和保持上下文一致。",
    }.get(page, "你正在写书工作台，请给出可直接执行的写作建议。")
    return f"{page_hint}\n\n用户通过页面悬浮 AI 窗口提出：{user_message}"


def render_floating_ai_chat(current_page: str) -> None:
    """页面悬浮 AI 聊天入口；移动端通过右下角按钮跳到可交互面板。"""
    enabled_pages = {"Workspace", "Projects", "Outline", "Editor"}
    if current_page not in enabled_pages:
        return

    st.markdown('<a class="hb-floating-chat-button" href="#hb-ai-chat" title="打开 AI 对话">AI</a>', unsafe_allow_html=True)
    st.markdown(
        """
        <div id="hb-ai-chat" class="hb-floating-chat-card">
            <strong>悬浮 AI 对话</strong><br>
            <span>手机点右下角 AI 按钮可回到这里；可让 AI 调整大纲、续写章节或修改生成内容。</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    project: Optional[ProjectKnowledgeBase] = st.session_state.get("project_data")
    if project is None:
        st.info("加载项目后，悬浮 AI 窗口可结合当前书稿上下文回答。")
        return

    with st.expander("打开悬浮 AI 聊天窗", expanded=False):
        history = st.session_state.get("floating_chat_history", [])
        for msg in history[-6:]:
            with st.chat_message(msg.get("role", "assistant")):
                st.markdown(msg.get("content", ""))

        with st.form(f"floating_ai_chat_form_{current_page}", clear_on_submit=True):
            user_message = st.text_area(
                "跟 AI 说你想怎么调整",
                placeholder="例如：把第三章拆成理论基础、技术体系、应用场景三节；或把当前章节改得更像学术专著。",
                height=96,
                key=f"floating_ai_input_{current_page}",
            )
            col_send, col_clear = st.columns([2, 1])
            send = col_send.form_submit_button("发送给 AI", type="primary", use_container_width=True)
            clear = col_clear.form_submit_button("清空", use_container_width=True)

        if clear:
            st.session_state["floating_chat_history"] = []
            st.rerun()
        if send:
            if not user_message.strip():
                st.warning("请输入要让 AI 调整的内容或要求。")
                return
            client = get_llm_client()
            if client is None:
                return
            prompt = _floating_chat_context_prompt(current_page, user_message.strip())
            st.session_state["floating_chat_history"].append({"role": "user", "content": user_message.strip()})
            with st.chat_message("assistant"):
                with st.spinner("AI 正在根据当前页面上下文思考…"):
                    response = _chat_with_ai(client, project, prompt)
                    st.markdown(response)
            st.session_state["floating_chat_history"].append({"role": "assistant", "content": response})
            st.session_state["current_page"] = current_page
            if current_page == "Outline":
                st.session_state["floating_outline_candidate"] = response
                parse_intent = bool(re.search(r"(重新解析|重建章节|解析章节|按.*大纲.*章节|根据.*大纲.*解析)", user_message.strip()))
                if parse_intent and (project.outline or "").strip():
                    st.info("已识别为按当前大纲重建章节，正在解析当前项目大纲…")
                    _parse_outline_text(project, project.outline, replace_all=True)
                else:
                    st.info("AI 回复已保留为大纲候选。可点击下方按钮直接按该回复重建章节。")

        if current_page == "Outline" and st.session_state.get("floating_outline_candidate"):
            st.markdown("**AI 大纲候选操作**")
            candidate = st.text_area(
                "确认要用于章节解析的 AI 大纲文本",
                value=st.session_state.get("floating_outline_candidate", ""),
                height=220,
                key="floating_outline_candidate_editor",
            )
            action_cols = st.columns(2)
            with action_cols[0]:
                if st.button("按 AI 回复重建章节", type="primary", use_container_width=True, key="floating_parse_outline_candidate"):
                    if candidate.strip():
                        st.session_state["current_page"] = "Outline"
                        _parse_outline_text(project, candidate, replace_all=True)
                    else:
                        st.warning(t('parse_outline_fail'))
            with action_cols[1]:
                if st.button("清除 AI 大纲候选", use_container_width=True, key="floating_clear_outline_candidate"):
                    st.session_state["floating_outline_candidate"] = ""
                    st.session_state["current_page"] = "Outline"
                    st.rerun()


def render_chat_page() -> None:
    """渲染聊天式指令页面"""
    st.title(t('chat_title'))

    project: Optional[ProjectKnowledgeBase] = st.session_state.get("project_data")
    if project is None:
        st.warning(t('load_project_first'))
        return

    client = get_llm_client()
    if client is None:
        return

    # 显示聊天历史
    chat_history = st.session_state.get("chat_history", [])
    for msg in chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # 用户输入
    if prompt := st.chat_input(t('chat_input_placeholder')):
        # 显示用户消息
        st.session_state["chat_history"].append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # 生成 AI 回复
        with st.chat_message("assistant"):
            with st.spinner(t('thinking')):
                response = _chat_with_ai(client, project, prompt)
                st.markdown(response)
                st.session_state["chat_history"].append({"role": "assistant", "content": response})

    # 清除聊天历史
    if chat_history:
        if st.button(t('clear_chat')):
            st.session_state["chat_history"] = []
            st.rerun()


def _chat_with_ai(client: LLMClient, project: ProjectKnowledgeBase, user_message: str) -> str:
    """与 AI 进行对话"""
    try:
        # 构建上下文
        context_parts = [
            f"项目: {project.title}",
            f"类型: {project.genre}",
            f"分类: {project.category}",
        ]
        if project.description:
            context_parts.append(f"描述: {project.description}")
        if project.outline:
            context_parts.append(f"大纲:\n{project.outline[:2000]}")
        if project.terminology:
            terms = "\n".join(f"- {t}: {d}" for t, d in list(project.terminology.items())[:20])
            context_parts.append(f"术语表:\n{terms}")

        system_prompt = (
            "你是好编辑的 AI 写作助手。你正在帮助用户撰写一本书。\n"
            "以下是当前项目的上下文信息：\n\n"
            + "\n\n".join(context_parts)
            + "\n\n请根据用户的问题提供有帮助的回答。如果用户要求生成内容，"
            "请直接输出内容。如果用户问问题，请给出专业、详细的回答。"
        )

        prompt = f"{system_prompt}\n\n用户：{user_message}\n\n助手："
        response = client.generate_content(prompt, max_tokens=2500, temperature=0.4, language=project.language)
        return response if isinstance(response, str) else str(response)

    except Exception as e:
        logger.exception("Chat failed")
        return t('chat_error', e=e)


def render_sources_page() -> None:
    """2.0 资料库 / RAG 中心：资料可视化、上传索引、证据检索测试。"""
    st.title("资料库 / RAG 中心")
    st.caption("管理真实资料来源、证据片段与检索测试。后续章节写作和引用核验将以这里的资料链为基础。")

    project: Optional[ProjectKnowledgeBase] = st.session_state.get("project_data")
    if project is None:
        st.warning(t('load_project_first'))
        return

    removed_sources, removed_chunks = _purge_bad_rag_state(project, persist=True)
    if removed_sources or removed_chunks:
        st.warning(f"已自动清理历史乱码资料 {removed_sources} 条、乱码证据片段 {removed_chunks} 条。")

    if getattr(project, "description", "") == "No description provided.":
        project.description = ""
        st.session_state["project_data"] = project
        save_project()

    source_documents = getattr(project, "source_documents", []) or []
    evidence_chunks = [
        chunk for chunk in (getattr(project, "evidence_chunks", []) or [])
        if _is_usable_evidence_text(getattr(chunk, "text", ""))
    ]
    legacy_docs = getattr(project, "rag_documents", []) or []

    with st.expander("项目描述与资料检索词整理", expanded=not bool(_clean_project_display_text(getattr(project, "description", "")))):
        st.caption("项目描述不会再使用 No description provided.。可以手动编辑，也可以让 AI 根据书名、大纲和联网检索词整理成专著写作定位。")
        description_value = st.text_area(
            "项目描述",
            value=_clean_project_display_text(getattr(project, "description", "")),
            height=110,
            key="sources_project_description_editor",
            placeholder="例如：本书围绕智慧工地建设与工程现场数字化管理，系统梳理技术体系、管理流程、数据治理与应用案例。",
        )
        desc_col_save, desc_col_ai = st.columns(2)
        with desc_col_save:
            if st.button("保存项目描述", use_container_width=True, key="sources_save_project_description"):
                project.description = description_value.strip()
                st.session_state["project_data"] = project
                save_project()
        with desc_col_ai:
            if st.button("AI 根据检索自动整理描述", use_container_width=True, key="sources_ai_project_description"):
                client = get_llm_client()
                if client is None:
                    st.stop()
                latest_query_text = st.session_state.get("sources_online_query") or st.session_state.get("sources_multi_queries", "")
                seed_context = _join_project_context_parts(
                    [getattr(project, "title", ""), description_value, getattr(project, "outline", ""), latest_query_text],
                    separator="\n",
                    limit=3500,
                )
                prompt = (
                    "你是学术专著选题策展助手。请根据书名、大纲、用户检索词，整理一段项目描述。\n"
                    "要求：1. 不写小说设定；2. 明确研究对象、核心问题、资料范围和目标读者；"
                    "3. 输出 120-220 字中文；4. 只输出描述正文。\n\n"
                    f"【上下文】\n{seed_context}"
                )
                try:
                    generated = client.generate_content(prompt, max_tokens=800, temperature=0.3, language=project.language)
                    project.description = str(generated).strip()
                    st.session_state["project_data"] = project
                    save_project()
                    st.success("已根据当前项目与检索词整理项目描述。")
                    st.rerun()
                except Exception as e:
                    st.error(f"AI 整理项目描述失败：{e}")

    last_upload_feedback = st.session_state.get("last_source_upload_feedback") or []
    if last_upload_feedback:
        with st.expander("最近一次资料上传入库证明", expanded=True):
            for item in last_upload_feedback:
                st.success(item)

    sources_docs_count = len(source_documents) or len(legacy_docs)
    sources_evidence_count = len(evidence_chunks)
    sources_citations = getattr(project, "citations", []) or []
    sources_citations_count = len(sources_citations)
    sources_unverified_count = len([c for c in sources_citations if getattr(c, "status", "unverified") != "verified"])

    col_docs, col_chunks, col_cites, col_gap = st.columns(4)
    if col_docs.button(f"📄 资料来源\n\n**{sources_docs_count}**", key="metric_source_docs_btn", use_container_width=True, help="点击定位到已索引资料管理区（查看 / 删除）"):
        st.session_state["sources_focus_docs"] = True
        st.session_state.pop("sources_focus_evidence", None)
        st.rerun()
    if col_chunks.button(f"📋 证据片段\n\n**{sources_evidence_count}**", key="metric_evidence_chunks_btn", use_container_width=True, help="点击定位到证据片段管理区（查看 / 删除）"):
        st.session_state["sources_focus_evidence"] = True
        st.session_state.pop("sources_focus_docs", None)
        st.rerun()
    if col_cites.button(f"📚 引用记录\n\n**{sources_citations_count}**", key="metric_citations_btn", use_container_width=True, help="点击跳转到引用管理页（查看 / 删除 / 添加）"):
        st.session_state["current_page"] = "Citations"
        st.session_state.pop("citation_filter_status", None)
        st.rerun()
    if col_gap.button(f"⚠️ 未核验引用\n\n**{sources_unverified_count}**", key="metric_unverified_btn", use_container_width=True, help="点击跳转到引用管理页，自动筛选仅显示未核验引用"):
        st.session_state["current_page"] = "Citations"
        st.session_state["citation_filter_status"] = "unverified"
        st.rerun()

    # 点击"资料来源"或"证据片段"按钮后，在对应区域显示醒目标记
    # （Streamlit 不支持 JS DOM 操作，改用 session_state 标记 + st.info 引导）
    sources_focus_docs_flag = st.session_state.pop("sources_focus_docs", False)
    sources_focus_evidence_flag = st.session_state.pop("sources_focus_evidence", False)

    st.divider()
    st.markdown("### 联网检索与引用真实性说明")
    st.info(
        "资料助手会按 1生成检索词 → 2整理检索结果 → 3结合大纲分析资料缺口 → 4优先 AI 搜索、失败后百度/API 补检入库 → 5基于全资料库头脑风暴 的顺序执行。"
        "AI 或网页搜索结果都会保留未核验状态，正式引用仍需上传原文、填写 DOI/URL 或人工确认权威来源。"
    )
    outline_seed_queries = []
    for line in str(getattr(project, "outline", "") or "").splitlines():
        cleaned_line = re.sub(r"^[第\d一二三四五六七八九十百章节、\.\s（）()]+", "", line).strip(" ：:，,。；;")
        if 6 <= len(cleaned_line) <= 80:
            outline_seed_queries.append(cleaned_line)
        if len(outline_seed_queries) >= 3:
            break
    default_multi_queries = "\n".join(
        query for query in [
            _join_project_context_parts([getattr(project, "title", ""), getattr(project, "category", "")], separator=" ", limit=80),
            *outline_seed_queries,
            _clean_project_display_text(getattr(project, "description", ""))[:80],
        ]
        if query
    )
    col_quick_query, col_quick_btn = st.columns([4, 1])
    with col_quick_query:
        quick_query = st.text_area(
            "资料联网检索词（每行一个，可编辑）",
            value=st.session_state.get("sources_multi_queries", default_multi_queries),
            height=110,
            placeholder="每行一个检索词，例如：\n智慧工地建设\n工程现场数字化管理\nBIM AIoT 施工现场",
            key="sources_online_query",
        )
    with col_quick_btn:
        st.write("")
        st.write("")
        if st.button("按多关键词检索资料", use_container_width=True, disabled=not bool(quick_query.strip()), key="sources_online_search_btn"):
            queries = []
            seen_queries = set()
            for line in quick_query.splitlines():
                cleaned = re.sub(r"\s+", " ", line).strip(" ；;，,。")
                if not cleaned:
                    continue
                key = cleaned.lower()
                if key in seen_queries:
                    continue
                seen_queries.add(key)
                queries.append(cleaned[:120])
            st.session_state["sources_multi_queries"] = "\n".join(queries)
            st.session_state["sources_online_query_submitted"] = queries

    submitted_queries = st.session_state.get("sources_online_query_submitted", [])
    if isinstance(submitted_queries, str):
        submitted_queries = [submitted_queries] if submitted_queries else []
    submitted_query = "；".join(submitted_queries)
    if submitted_queries:
        st.markdown("**检索入口（按关键词分开）：**")
        for query in submitted_queries[:8]:
            st.markdown(f"- `{query}`")
            links = CitationService.reference_verification_links(query)
            cols = st.columns(len(links) or 1)
            for idx, (label, url) in enumerate(links.items()):
                cols[idx].link_button(label, url, use_container_width=True)

    with st.expander("AI 资料助手：生成检索词 → 整理结果 → 缺口分析 → AI/Tavily/百度检索入库 → 全资料库头脑风暴", expanded=False):
        st.caption(
            "这是严格顺序的资料工作台：后一步必须读取前一步结果。第四步会优先要求模型使用自身搜索能力；"
            "如果模型明确反馈不支持搜索，则优先调用已配置的 Tavily，失败或无结果时再回退百度搜索 API；候选网页必须打开并经 AI 筛选后才入资料库。"
        )
        results_by_task = st.session_state.setdefault("sources_ai_results_by_task", {})
        for step in SOURCES_AI_WORKFLOW_TASKS:
            saved_text = _sources_ai_saved_text(project, step["task"], results_by_task, limit=1200)
            step["status"] = "已完成" if saved_text else "待处理"
        step_labels = [f"{step['label']} · {step['status']}" for step in SOURCES_AI_WORKFLOW_TASKS]
        selected_step_label = st.radio(
            "按正常资料工作流执行",
            step_labels,
            horizontal=False,
            key="sources_ai_task_label",
            help="建议按 1→2→3→4→5 执行。下方会一直显示全部已保存记录，后续大纲生成会读取这些资料。",
        )
        selected_index = step_labels.index(selected_step_label) if selected_step_label in step_labels else 0
        ai_task = SOURCES_AI_WORKFLOW_TASKS[selected_index]["task"]
        st.session_state["sources_ai_task"] = ai_task
        task_presets = {
            "生成检索词": "请围绕当前项目主题、项目描述和已有大纲意图，生成可直接复制的检索方案。必须输出：1. 中文核心关键词组；2. 英文关键词组；3. 可拆分短检索词；4. 同义词/近义词；5. 排除词；6. Tavily/百度/API 可直接使用的短检索词；7. 下一步优先检索顺序。",
            "整理检索结果": "请只根据第一步生成的检索词，整理当前 OpenAlex 候选、百度/API 网页结果、项目引用记录和已上传资料。必须输出：1. 每个检索词的命中情况；2. 结果主题归类；3. 来源可信度和年份；4. 可支撑章节；5. 待核验风险。不得编造未提供的文献或网页。",
            "分析资料缺口": "请基于第二步整理结果和当前大纲逐章分析资料缺口。必须包含“#### 资料状态”，并按章节输出：- 可支撑：主题方向/已有依据；- 不可直接支撑：政策依据、发展历程、权威定义、行业数据、案例、标准规范等；- 下一步补检词。",
            "AI检索资料入库": "请根据第三步资料缺口进行资料检索。优先使用你当前模型自身可用的联网/搜索能力，返回真实网页、机构报告、政策文件、标准、行业数据或文献线索；如果你不支持联网搜索，必须明确回复“不支持联网搜索”。输出必须包含：检索词、标题、链接/DOI、来源机构/网站、可支撑章节、仍需核验事项。系统会把结果或 Tavily/百度兜底检索后经网页打开和 AI 筛选通过的资料保存到资料来源库。",
            "资料库头脑风暴": "请基于第四步新增资料和资料库里所有资料进行头脑风暴。必须输出：1. 最终资料状态；2. 各章节可支撑/不可直接支撑矩阵；3. 全书核心问题与价值主张；4. 推荐章级模块与逻辑顺序；5. 仍缺资料时列出补检词并标记“需要补充资料”。如仍缺少关键资料，系统会自动回到第四步调用百度/API 补全并入库。",
        }
        ai_instruction = st.text_area(
            "具体要求",
            value=task_presets.get(ai_task, ""),
            height=140,
            key=f"sources_ai_instruction_{ai_task}",
        )
        selected_evidence = evidence_chunks[:12] if ai_task in {"大纲前头脑风暴", "资料库头脑风暴"} else evidence_chunks[:8]
        evidence_context = "\n\n".join(
            f"[证据片段 {idx}] source_id={getattr(chunk, 'source_id', '')} evidence_id={getattr(chunk, 'id', '')}\n{getattr(chunk, 'text', '')[:1200]}"
            for idx, chunk in enumerate(selected_evidence, 1)
        )
        citations_context = "\n".join(
            f"{idx}. status={getattr(citation, 'status', 'unverified')} | ref={getattr(citation, 'formatted_ref', '') or getattr(citation, 'source', '') or getattr(citation, 'sentence', '')} | DOI={getattr(citation, 'doi', '') or '无'} | URL={getattr(citation, 'url', '') or '无'}"
            for idx, citation in enumerate((getattr(project, "citations", []) or [])[:20], 1)
        )
        openalex_context = ""
        diagnostics_for_ai = st.session_state.get("openalex_diagnostics") or {}
        if diagnostics_for_ai:
            openalex_context = "\n".join(
                f"{idx}. {item.get('title') or '未命名'} | {item.get('publication_year') or '年份缺失'} | {item.get('publication_name') or '刊名缺失'} | DOI={item.get('doi') or '无'}"
                for idx, item in enumerate((diagnostics_for_ai.get("items") or [])[:10], 1)
            )
        outline_web_context = ""
        outline_web_groups = st.session_state.get("outline_web_search_results", []) or []
        if outline_web_groups:
            outline_web_context = "\n".join(
                f"{group.get('query', '')} -> "
                + "; ".join(
                    f"{item.get('title') or '无标题'} ({item.get('url') or '无链接'})"
                    for item in ((group.get("result", {}) or {}).get("items", []) or [])[:5]
                )
                for group in outline_web_groups[:6]
            )
        reference_web_context = ""
        reference_web_groups = st.session_state.get("literature_web_verification_results", []) or []
        if reference_web_groups:
            reference_web_context = "\n".join(
                f"{group.get('query', '')} -> "
                + "; ".join(
                    f"{item.get('title') or '无标题'} ({item.get('url') or '无链接'})"
                    for item in ((group.get("search", {}) or {}).get("items", []) or [])[:5]
                )
                for group in reference_web_groups[:8]
            )
        context_cols = st.columns(5)
        context_cols[0].metric("已上传证据片段", len(evidence_chunks))
        context_cols[1].metric("OpenAlex候选", len((diagnostics_for_ai.get("items") or [])))
        context_cols[2].metric("项目引用记录", len(getattr(project, "citations", []) or []))
        context_cols[3].metric("大纲网页检索组", len(outline_web_groups))
        context_cols[4].metric("参考文献网页核查组", len(reference_web_groups))
        workflow_context = _sources_ai_workflow_context(project, results_by_task, limit_per_step=2200)
        project_context = "\n".join(
            part for part in [
                f"书名：{_clean_project_display_text(getattr(project, 'title', ''))}",
                f"专著类型：{_clean_project_display_text(getattr(project, 'genre', ''))}",
                f"学科/方向：{_clean_project_display_text(getattr(project, 'category', ''))}",
                f"项目描述：{_clean_project_display_text(getattr(project, 'description', ''))}",
                f"大纲：\n{(getattr(project, 'outline', '') or '')[:3000]}",
                f"当前资料联网检索词：{submitted_query or quick_query}",
                f"OpenAlex 候选：\n{openalex_context}" if openalex_context else "",
                f"搜索 API 大纲网页结果：\n{outline_web_context}" if outline_web_context else "",
                f"搜索 API 参考文献核查结果：\n{reference_web_context}" if reference_web_context else "",
                f"项目引用记录：\n{citations_context}" if citations_context else "",
                f"资料助手已保存工作流记录：\n{workflow_context}" if workflow_context else "",
                f"已保存的大纲前头脑风暴：\n{_outline_brainstorm_context(project, limit=3000)}" if _outline_brainstorm_context(project) else "",
                f"已上传资料片段：\n{evidence_context}" if evidence_context else "",
            ]
            if str(part).strip() and not str(part).strip().endswith("：")
        )
        guardrail = (
            "你是 AI 学术专著资料助手。必须遵守：\n"
            "1. 按 生成检索词→根据检索词整理检索结果→结合检索结果和大纲分析资料缺口→AI检索资料入库→基于全资料库头脑风暴 的顺序执行，后一步必须引用前一步结果。\n"
            "2. 生成检索词时，输出中文检索式、英文检索式、同义词、排除词、Tavily/百度/API 可用短词和优先顺序。\n"
            "3. 整理检索结果时，只能依据上一步检索词、OpenAlex 候选、Tavily/百度/API 网页结果、引用记录和资料库内容，不得编造不存在的文献。\n"
            "4. 分析资料缺口时，必须结合第二步结果和大纲各章节输出“#### 资料状态”，并明确“可支撑”和“不可直接支撑”。\n"
            "5. AI检索资料入库时，优先使用模型自身联网/搜索能力；如果不支持搜索，必须明确回复“不支持联网搜索”，系统会优先调用 Tavily，失败或无结果时再回退百度搜索 API。\n"
            "6. 资料库头脑风暴时，必须综合第四步新增资料和资料库所有资料；如果仍缺资料，必须列出补检词并标记“需要补充资料”，系统会自动回到第四步补全。\n"
            "7. AI、OpenAlex、Tavily、百度/API 结果都只能作为资料线索或待核验来源；不得把未核验线索写成已核验真实引用。\n"
            "8. 输出结构清晰，适合沉淀到资料库并提交给大纲生成。"
        )
        prompt = f"{guardrail}\n\n【项目与资料上下文】\n{project_context}\n\n【任务】{ai_task}\n【具体要求】\n{ai_instruction}\n\n请输出结果："
        st.info("为避免第三方模型接口长时间 524，资料助手会使用紧凑输出；需要更细内容可保存后继续分任务追问。")
        if st.button("让 AI 处理当前步骤并保存到资料库", type="primary", use_container_width=True, key="sources_ai_assistant_btn"):
            client = get_llm_client()
            if client is None:
                st.stop()
            with st.spinner("AI 正在处理资料…"):
                try:
                    result = client.generate_content(
                        prompt,
                        max_tokens=_sources_ai_max_tokens(ai_task),
                        temperature=0.3,
                        language=project.language,
                    )
                    result_text = (result if isinstance(result, str) else str(result or "")).strip()
                    if not result_text:
                        detail = getattr(client, "last_error", "") or getattr(client, "last_response_preview", "") or "模型返回为空"
                        raise ValueError(f"模型没有返回可用结果。最近一次接口信息：{detail}")
                    results_by_task[ai_task] = result_text
                    st.session_state["sources_ai_result"] = result_text
                    st.session_state["sources_ai_result_task"] = ai_task
                    document, chunk = _persist_sources_ai_result(project, ai_task, result_text, ai_instruction, project_context)
                    literature_service_for_ai = LiteratureSearchService()
                    fallback_message = ""
                    if ai_task == "AI检索资料入库" and _sources_ai_model_search_unsupported(result_text):
                        settings_for_search = Settings()
                        fallback_message = _run_sources_ai_gap_search(
                            project,
                            _sources_ai_saved_text(project, "分析资料缺口", results_by_task, limit=12000) or result_text,
                            literature_service=literature_service_for_ai,
                            web_search_api_url=st.session_state.get("web_search_api_url", LiteratureSearchService.DEFAULT_WEB_SEARCH_URL),
                            web_search_id=st.session_state.get("web_search_api_id", ""),
                            web_search_key=st.session_state.get("web_search_api_key", ""),
                            web_search_tn=st.session_state.get("web_search_api_tn", ""),
                            web_search_cookie=st.session_state.get("web_search_api_cookie", ""),
                            tavily_api_key=st.session_state.get("tavily_api_key", settings_for_search.tavily_api_key),
                            tavily_base_url=st.session_state.get("tavily_base_url", settings_for_search.tavily_base_url or LiteratureSearchService.DEFAULT_TAVILY_BASE_URL),
                            tavily_max_results=st.session_state.get("tavily_max_results", settings_for_search.tavily_max_results),
                            tavily_search_depth=st.session_state.get("tavily_search_depth", settings_for_search.tavily_search_depth),
                            client=client,
                        )
                        result_text = f"{result_text}\n\n#### Tavily/百度兜底检索入库结果\n{fallback_message}".strip()
                        results_by_task[ai_task] = result_text
                        st.session_state["sources_ai_result"] = result_text
                        document, chunk = _persist_sources_ai_result(project, ai_task, result_text, ai_instruction, project_context)
                    if ai_task == "资料库头脑风暴" and _sources_ai_needs_more_sources(result_text):
                        settings_for_search = Settings()
                        fallback_message = _run_sources_ai_gap_search(
                            project,
                            result_text,
                            literature_service=literature_service_for_ai,
                            web_search_api_url=st.session_state.get("web_search_api_url", LiteratureSearchService.DEFAULT_WEB_SEARCH_URL),
                            web_search_id=st.session_state.get("web_search_api_id", ""),
                            web_search_key=st.session_state.get("web_search_api_key", ""),
                            web_search_tn=st.session_state.get("web_search_api_tn", ""),
                            web_search_cookie=st.session_state.get("web_search_api_cookie", ""),
                            tavily_api_key=st.session_state.get("tavily_api_key", settings_for_search.tavily_api_key),
                            tavily_base_url=st.session_state.get("tavily_base_url", settings_for_search.tavily_base_url or LiteratureSearchService.DEFAULT_TAVILY_BASE_URL),
                            tavily_max_results=st.session_state.get("tavily_max_results", settings_for_search.tavily_max_results),
                            tavily_search_depth=st.session_state.get("tavily_search_depth", settings_for_search.tavily_search_depth),
                            client=client,
                        )
                        result_text = f"{result_text}\n\n#### 自动补检入库结果\n{fallback_message}".strip()
                        results_by_task[ai_task] = result_text
                        st.session_state["sources_ai_result"] = result_text
                        document, chunk = _persist_sources_ai_result(project, ai_task, result_text, ai_instruction, project_context)
                    st.session_state["project_data"] = project
                    save_project()
                    if ai_task in {"大纲前头脑风暴", "资料库头脑风暴"}:
                        st.success(f"已生成并保存到资料库，同时设为大纲生成依据。资料ID：{document.id}；证据ID：{chunk.id}" + (f" {fallback_message}" if fallback_message else ""))
                    else:
                        st.success(f"已生成并保存到资料库，后续步骤和大纲生成都能读取。资料ID：{document.id}；证据ID：{chunk.id}" + (f" {fallback_message}" if fallback_message else ""))
                except Exception as e:
                    st.error(f"AI 资料处理失败：{e}")
                    st.warning("如果这里长时间无结果，通常是当前模型中转接口超时/524。建议换一个可用模型档案，或缩短任务要求后重试；旧结果不会被覆盖。")
                    logger.exception("Sources AI assistant failed")
        if st.session_state.get("sources_ai_result") and st.session_state.get("sources_ai_result_task"):
            results_by_task.setdefault(st.session_state.get("sources_ai_result_task"), st.session_state.get("sources_ai_result"))
        for step in SOURCES_AI_WORKFLOW_TASKS:
            saved_text = _sources_ai_saved_text(project, step["task"], results_by_task, limit=20000)
            if saved_text:
                results_by_task.setdefault(step["task"], saved_text)
        current_result = results_by_task.get(ai_task, "")
        if current_result:
            document_id, chunk_id = _sources_ai_result_ids(ai_task)
            saved_document = next((doc for doc in getattr(project, "source_documents", []) or [] if getattr(doc, "id", "") == document_id), None)
            st.markdown(f"**当前步骤结果：{ai_task}**")
            st.caption(f"当前步骤可编辑保存；所有步骤记录会在下方常驻显示。资料ID：`{document_id}` / 证据ID：`{chunk_id}`。")
            edited_ai_result = st.text_area("可复制/可编辑结果", value=current_result, height=300, key=f"sources_ai_result_text_{ai_task}")
            save_cols = st.columns(2)
            with save_cols[0]:
                if st.button("保存/更新当前步骤到资料库", use_container_width=True, key=f"save_sources_ai_result_{ai_task}"):
                    document, chunk = _persist_sources_ai_result(project, ai_task, edited_ai_result, ai_instruction, "用户手动保存/更新")
                    results_by_task[ai_task] = edited_ai_result.strip()
                    st.session_state["project_data"] = project
                    save_project()
                    st.success(f"已保存到资料库。资料ID：{document.id}；证据ID：{chunk.id}")
                    st.rerun()
            with save_cols[1]:
                if ai_task in {"大纲前头脑风暴", "资料库头脑风暴"} and st.button("保存并设为大纲生成依据", use_container_width=True, key="save_sources_ai_as_outline_brainstorm"):
                    document, chunk = _persist_sources_ai_result(project, ai_task, edited_ai_result, ai_instruction, "用户手动设为大纲前头脑风暴")
                    results_by_task[ai_task] = edited_ai_result.strip()
                    st.session_state["project_data"] = project
                    save_project()
                    st.success(f"已设为大纲生成依据并同步资料库。资料ID：{document.id}；证据ID：{chunk.id}")
                    st.rerun()
                elif saved_document:
                    st.success("当前步骤已有资料库保存记录，后续步骤和大纲生成会读取。")
                else:
                    st.caption("尚未保存到资料库。")
        st.markdown("**资料助手工作流记录（常驻显示，切换步骤不会消失）**")
        completed_workflow_text = _sources_ai_workflow_context(project, results_by_task, limit_per_step=5000)
        for step in SOURCES_AI_WORKFLOW_TASKS:
            task = step["task"]
            saved_text = _sources_ai_saved_text(project, task, results_by_task, limit=20000)
            document_id, chunk_id = _sources_ai_result_ids(task)
            expanded = bool(saved_text) or task == ai_task
            with st.expander(f"{step['label']} · {'已保存' if saved_text else '待生成'}", expanded=expanded):
                st.caption(f"作用：{step['goal']} 产出：{step['output']}")
                if saved_text:
                    edited_step_text = st.text_area(
                        "已保存内容（可编辑后更新资料库）",
                        value=saved_text,
                        height=220,
                        key=f"sources_ai_workflow_record_{task}",
                    )
                    cols_record = st.columns([1, 1])
                    with cols_record[0]:
                        if st.button("更新这一步资料库记录", use_container_width=True, key=f"update_sources_ai_workflow_record_{task}"):
                            document, chunk = _persist_sources_ai_result(project, task, edited_step_text, task_presets.get(task, ""), "用户在工作流记录区更新")
                            results_by_task[task] = edited_step_text.strip()
                            st.session_state["project_data"] = project
                            save_project()
                            st.success(f"已更新：{document.id} / {chunk.id}")
                            st.rerun()
                    with cols_record[1]:
                        st.caption(f"资料ID：`{document_id}`；证据ID：`{chunk_id}`")
                else:
                    st.info("这一步还没有生成。选择上方对应步骤后点击 AI 处理，会自动保存并显示在这里。")
        if completed_workflow_text:
            st.success("已保存的资料助手工作流记录会作为后续步骤上下文，也会在提交后成为大纲生成依据。")
            if st.button("汇总并提交给大纲生成", type="primary", use_container_width=True, key="submit_sources_ai_workflow_to_outline"):
                project.outline_brainstorm = completed_workflow_text[:20000]
                _persist_sources_ai_result(project, "大纲前头脑风暴", project.outline_brainstorm, "资料助手五步工作流汇总", "用户汇总提交给大纲生成")
                st.session_state["project_data"] = project
                save_project()
                st.success("已把资料助手五步记录汇总为大纲生成依据。")
                st.rerun()
        saved_ai_documents = [
            doc for doc in getattr(project, "source_documents", []) or []
            if (getattr(doc, "metadata", {}) or {}).get("origin") == "sources_ai_assistant"
        ]
        if saved_ai_documents:
            with st.expander(f"资料库中的 AI 内部分析资料索引（{len(saved_ai_documents)} 条）", expanded=False):
                for doc in saved_ai_documents:
                    meta = getattr(doc, "metadata", {}) or {}
                    st.markdown(f"- **{getattr(doc, 'title', '')}** · `{getattr(doc, 'id', '')}` · {meta.get('verification_status', 'ai_analysis_not_verified_citation')}")
                st.caption("这些资料是内部分析/写作线索，不是已核验参考文献；正式引用仍以引用记录和上传原文证据为准。")
        saved_brainstorm = _outline_brainstorm_context(project, limit=12000)
        if saved_brainstorm:
            st.markdown("**已提交给大纲生成的资料汇总（大纲生成会自动使用）**")
            edited_brainstorm = st.text_area(
                "可编辑大纲生成依据",
                value=saved_brainstorm,
                height=300,
                key="sources_outline_brainstorm_editor",
                help="这份内容会作为后续大纲生成的优先资料，用于确定章级模块、资料边界和写作思路。",
            )
            col_save_brainstorm, col_clear_brainstorm = st.columns(2)
            with col_save_brainstorm:
                if st.button("保存大纲生成依据修改", use_container_width=True, key="save_outline_brainstorm_btn"):
                    project.outline_brainstorm = edited_brainstorm.strip()
                    st.session_state["project_data"] = project
                    save_project()
                    st.success("已保存大纲生成依据修改。")
                    st.rerun()
            with col_clear_brainstorm:
                if st.button("清空大纲生成依据", use_container_width=True, key="clear_outline_brainstorm_btn"):
                    project.outline_brainstorm = ""
                    st.session_state["project_data"] = project
                    save_project()
                    st.success("已清空大纲生成依据。")
                    st.rerun()

    with st.expander("OpenAlex 学术文献自动检索与引用生成", expanded=False):
        st.caption("根据章节标题、关键词或项目主题检索真实 OpenAlex 期刊论文，按中文 GB/T 7714 风格生成参考文献。支持中文/英文/全部文献筛选和 search.semantic 语义搜索；API Key 仅保存在当前会话，不写入源码。")
        default_query = _join_project_context_parts(
            [getattr(project, "title", ""), getattr(project, "description", ""), getattr(project, "category", "")],
            separator=" ",
            limit=120,
        )
        literature_query = st.text_input(
            "章节关键词 / 标题 / DOI",
            value=default_query,
            placeholder="例如：智慧工地 工程现场 数字化管理 BIM AIoT 或 construction site digital management",
            key="openalex_literature_query",
        )
        semantic_seed = _join_project_context_parts(
            [getattr(project, "title", ""), getattr(project, "description", ""), getattr(project, "outline", "")],
            separator="\n",
            limit=2000,
        )
        search_mode_label = st.radio(
            "OpenAlex 检索方式",
            ["语义搜索 search.semantic（适合一段大纲/摘要）", "关键词搜索 search（适合短关键词/DOI）"],
            horizontal=True,
            key="openalex_search_mode_label",
        )
        openalex_search_mode = "semantic" if search_mode_label.startswith("语义") else "keyword"
        if openalex_search_mode == "semantic":
            semantic_query = st.text_area(
                "语义检索文本（最多使用前 2000 字符）",
                value=semantic_seed or literature_query,
                height=130,
                key="openalex_semantic_query",
                help="可粘贴章节写作目标、大纲段落、摘要或研究问题。OpenAlex 会按标题+摘要向量相似度匹配。",
            )
            effective_literature_query = semantic_query.strip()[:2000]
            st.info("语义搜索适合长文本含义匹配；OpenAlex 不支持在语义搜索中使用 cited_by_count 排序，系统会自动关闭引用量排序。")
        else:
            effective_literature_query = literature_query.strip()
        language_label = st.radio(
            "文献语言范围",
            ["中文文献", "英文文献", "全部文献"],
            index=0,
            horizontal=True,
            key="openalex_language_filter_label",
            help="中文专著建议先选中文文献；如果中文结果不足，再切到英文或全部文献。",
        )
        openalex_language_filter = {"中文文献": "zh", "英文文献": "en", "全部文献": "all"}.get(language_label, "zh")
        col_api, col_limit, col_years = st.columns([2, 1, 1])
        with col_api:
            openalex_api_key = st.text_input(
                "OpenAlex API Key（可选，当前会话使用，不写入仓库）",
                type="password",
                key="openalex_api_key",
                help="也可通过环境变量 OPENALEX_API_KEY 配置。",
            )
        with col_limit:
            literature_limit = st.slider("返回条数", min_value=1, max_value=10, value=5, key="openalex_literature_limit")
        with col_years:
            recent_only = st.checkbox("近 10 年", value=False, key="openalex_recent_10y")

        literature_service = LiteratureSearchService()
        if effective_literature_query:
            st.code(
                literature_service.build_openalex_search_url(
                    effective_literature_query,
                    limit=literature_limit,
                    api_key=openalex_api_key,
                    recent_years=10 if recent_only else None,
                    search_mode=openalex_search_mode,
                    language_filter=openalex_language_filter,
                ),
                language="text",
            )
            st.caption("说明：OpenAlex 的期刊论文 type 实际为 article；系统默认按 OpenAlex 相关性排序，并支持中文/英文/全部文献过滤，避免高被引但不相关结果挤占。")

        if st.button("检索并生成参考文献", type="primary", use_container_width=True, disabled=not bool(effective_literature_query)):
            try:
                diagnostics = literature_service.search_with_diagnostics(
                    effective_literature_query,
                    limit=literature_limit,
                    api_key=openalex_api_key,
                    recent_years=10 if recent_only else None,
                    journal_only=True,
                    search_mode=openalex_search_mode,
                    language_filter=openalex_language_filter,
                )
                formatted_rows = []
                for item in diagnostics["items"]:
                    formatted = literature_service.format_citation(item, len(formatted_rows) + 1)
                    if formatted:
                        formatted_rows.append(formatted)
                citations = formatted_rows[:literature_limit]
                st.session_state["openalex_formatted_citations"] = citations
                st.session_state["openalex_diagnostics"] = diagnostics
                st.session_state["openalex_last_query"] = effective_literature_query
                if citations:
                    st.success(f"OpenAlex 返回 {diagnostics['raw_count']} 条候选，已生成 {len(citations)} 条可用引用。")
                else:
                    meta_count = (diagnostics.get("meta") or {}).get("count", diagnostics.get("raw_count", 0))
                    st.warning(f"OpenAlex 检索命中 {meta_count} 条，当前页 {diagnostics.get('raw_count', 0)} 条，但缺少标题/刊名/年份等必要字段，未生成可用引用。下方已显示候选与剔除原因。")
            except Exception as e:
                st.error(f"OpenAlex 检索失败：{e}")
                logger.exception("OpenAlex literature search failed")

        diagnostics = st.session_state.get("openalex_diagnostics") or {}
        if diagnostics:
            meta = diagnostics.get("meta") or {}
            mode_text = "语义搜索" if diagnostics.get("search_mode") == "semantic" else "关键词搜索"
            st.caption(f"OpenAlex 诊断：{mode_text}；总命中 {meta.get('count', diagnostics.get('raw_count', 0))} 条；当前页候选 {diagnostics.get('raw_count', 0)} 条。")
            with st.expander("查看 OpenAlex 原始候选与不可用原因", expanded=not bool(st.session_state.get("openalex_formatted_citations", []))):
                for idx, item in enumerate((diagnostics.get("items") or [])[:10], 1):
                    missing = literature_service.citation_missing_reasons(item)
                    st.markdown(f"**{idx}. {item.get('title') or '未命名文献'}**")
                    st.caption(
                        f"年份：{item.get('publication_year') or '缺失'} | "
                        f"刊名：{item.get('publication_name') or '缺失'} | "
                        f"类型：{item.get('type') or '未知'} | DOI：{item.get('doi') or '无'}"
                    )
                    if missing:
                        st.warning("不可生成原因：" + "；".join(missing))
                    else:
                        st.success("字段完整，可生成引用。")

        formatted_citations = st.session_state.get("openalex_formatted_citations", [])
        if formatted_citations:
            st.markdown(f"**生成结果（纯文本，一行一条，共 {len(formatted_citations)} 条）：**")
            citation_text_height = max(260, min(560, 44 * len(formatted_citations) + 80))
            st.text_area("参考文献", value="\n".join(formatted_citations), height=citation_text_height, key="openalex_citation_text")
            st.caption("如果参考文献较多，文本框会自动增高；仍可直接 Ctrl+A 全选复制全部条目。")
            if st.button("导入到引用记录", use_container_width=True):
                imported = literature_service.import_formatted_citations(
                    project,
                    formatted_citations,
                    keywords=st.session_state.get("openalex_last_query", effective_literature_query),
                )
                if save_project():
                    st.success(f"已导入 {len(imported)} 条 OpenAlex 引用记录；本版本视为已核验，无需再走二次核验流程。")
                    st.rerun()
        st.info("OpenAlex 来源于开放学术数据库；本版本导入后直接进入已核验引用记录，用户仍可在引用页面查看、删除或补充 DOI/URL。")

    st.divider()
    st.markdown("### 上传资料")
    st.caption("支持 PDF、DOCX、TXT、Markdown、HTML、Excel。默认先导入资料库并生成证据片段，不主动下载 HuggingFace embedding 模型。")
    uploaded_files = st.file_uploader(
        "上传参考资料",
        type=["pdf", "docx", "txt", "md", "markdown", "html", "htm", "xlsx", "xls"],
        accept_multiple_files=True,
        key="sources_rag_upload",
        help="上传后会先进入资料库，供大纲和正文生成参考；向量索引可在网络和本地模型可用时再启用。",
    )
    build_vector_index = st.checkbox(
        "同时建立向量索引（使用模型设置里的独立资料索引 API 配置）",
        value=False,
        key="sources_build_vector_index",
    )
    if uploaded_files and st.button("导入资料库", type="primary", use_container_width=True):
        _index_rag_documents(project, uploaded_files, build_vector_index=build_vector_index)
        st.rerun()

    st.divider()
    if sources_focus_docs_flag:
        st.info("👇 以下是已索引资料管理区，可查看每份资料的详情与关联证据片段，并支持删除资料及其证据片段。")
    st.markdown("### 已索引资料")
    if source_documents:
        for doc in source_documents:
            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([3, 1, 1, 1])
                c1.markdown(f"**{doc.title or doc.file_name or doc.source_type}**")
                c1.caption(f"ID: {doc.id} | 文件: {doc.file_name or doc.file_path}")
                c2.metric("片段", doc.chunk_count)
                c3.caption(f"状态：{doc.status}")
                delete_key = f"delete_source_document_{doc.id}"
                if c4.button("删除资料", key=delete_key, use_container_width=True, help="删除该资料及其证据片段；不会删除已人工整理的引用记录。"):
                    deleted_docs, deleted_chunks = _delete_source_document_from_project(project, doc.id)
                    if save_project():
                        st.success(f"已删除资料 {deleted_docs} 条、证据片段 {deleted_chunks} 条。")
                        st.rerun()
                with st.expander("查看资料详情与片段", expanded=False):
                    st.write(f"标题：{doc.title or '-'}")
                    st.write(f"文件：{doc.file_name or doc.file_path or '-'}")
                    st.write(f"类型：{doc.source_type or '-'} | 状态：{doc.status or '-'} | 入库时间：{doc.indexed_at or '-'}")
                    if doc.doi or doc.url:
                        st.write(f"DOI：{doc.doi or '-'} | URL：{doc.url or '-'}")
                    if doc.summary:
                        st.markdown("**摘要/首段：**")
                        st.write(doc.summary)
                    related_chunks = [chunk for chunk in evidence_chunks if chunk.document_id == doc.id]
                    st.caption(f"关联证据片段：{len(related_chunks)} 条")
                    for chunk in related_chunks[:5]:
                        st.markdown(f"- `{chunk.id}` · #{chunk.chunk_index}：{chunk.text[:220]}")
                    if len(related_chunks) > 5:
                        st.caption(f"仅展示前 5 条，共 {len(related_chunks)} 条。")
                if doc.file_hash:
                    st.caption(f"file_hash: {doc.file_hash[:16]}… | indexed_at: {doc.indexed_at or '未知'}")
    elif legacy_docs:
        st.info("当前项目存在旧版 RAG 文档记录，尚未生成 2.0 资料来源元数据。重新上传并索引后可获得证据追溯能力。")
        for doc_path in legacy_docs:
            st.caption(str(doc_path))
    else:
        st.info("尚未索引资料。建议先上传真实参考资料，再生成章节，以减少幻觉引用。")

    st.divider()
    st.markdown("### RAG 检索测试")
    query = st.text_input("输入检索问题或小节标题", placeholder="例如：制造业绿色转型评价指标")
    top_k = st.slider("返回片段数", min_value=1, max_value=10, value=5)
    if st.button("检索证据片段", use_container_width=True) and query.strip():
        try:
            from libriscribe.rag.embeddings import EmbeddingProvider
            from libriscribe.rag.vector_store import VectorStore
            store = VectorStore(embedding_provider=EmbeddingProvider())
            results = _purge_bad_vector_results(store.query(query.strip(), top_k=top_k))
            if not results:
                st.warning("没有检索到可用证据片段。请确认资料已成功索引，或更换查询词；历史乱码向量已被页面过滤。")
            for idx, result in enumerate(results, start=1):
                meta = result.get("metadata", {}) or {}
                with st.expander(f"证据 {idx} · {meta.get('source', '未知来源')} · score {1 - float(result.get('distance', 0) or 0):.3f}", expanded=idx == 1):
                    st.caption(f"evidence_id: {meta.get('evidence_id', result.get('id', ''))} | source_id: {meta.get('source_id', '')} | chunk_index: {meta.get('chunk_index', '')}")
                    st.write(result.get("content", ""))
        except ImportError as e:
            st.error(t('rag_unavailable', e=e))
        except Exception as e:
            st.error(t('rag_index_fail', e=e))
            logger.exception("RAG search failed")

    st.divider()
    st.markdown("### 证据片段样例")
    if sources_focus_evidence_flag:
        st.info("👇 以下是证据片段管理区，可查看每条片段的来源与内容，并支持删除不再需要的片段。")
    if evidence_chunks:
        for chunk in evidence_chunks[:10]:
            with st.expander(f"{chunk.source} · #{chunk.chunk_index} · {chunk.id}"):
                st.caption(f"document_id: {chunk.document_id} | chunk_hash: {chunk.chunk_hash[:16]}…")
                st.write(chunk.text)
                delete_chunk_key = f"delete_evidence_chunk_{chunk.id}"
                if st.button("删除此证据片段", key=delete_chunk_key, help="仅删除本条证据片段，不影响关联的资料文档与其他片段"):
                    deleted_count = _delete_evidence_chunk_from_project(project, chunk.id)
                    if save_project():
                        st.success(f"已删除证据片段 {deleted_count} 条。")
                        st.rerun()
        if len(evidence_chunks) > 10:
            st.caption(f"仅展示前 10 条，共 {len(evidence_chunks)} 条。")
    else:
        st.caption("暂无证据片段。")


def render_settings_page() -> None:
    """渲染项目设置页面"""
    st.title(t('settings_title'))

    project: Optional[ProjectKnowledgeBase] = st.session_state.get("project_data")
    if project is None:
        st.warning(t('load_project_first'))
        return

    # 基本信息
    st.markdown(t('basic_info'))
    with st.form("settings_basic"):
        title = st.text_input(t('book_title_label'), value=project.title)
        description = st.text_area(t('project_desc').replace('### ', ''), value=project.description, height=100)
        col1, col2 = st.columns(2)
        with col1:
            category = st.selectbox(
                t('category_label'),
                CATEGORIES,
                index=CATEGORIES.index(project.category) if project.category in CATEGORIES else 0,
            )
        with col2:
            genre = st.text_input(t('genre_label'), value=project.genre)
        col3, col4 = st.columns(2)
        with col3:
            language = st.selectbox(
                t('language_label'),
                PROJECT_LANGUAGES,
                index=PROJECT_LANGUAGES.index(project.language)
                if project.language in PROJECT_LANGUAGES
                else 0,
            )
        with col4:
            ready_profiles = _available_model_profiles(require_ready=True)
            current_profile = _resolve_project_model_profile(project)
            ready_ids = [p["id"] for p in ready_profiles]
            selected_model_profile_id = st.selectbox(
                "写作模型",
                ready_ids,
                index=ready_ids.index(current_profile["id"]) if current_profile and current_profile.get("id") in ready_ids else 0,
                format_func=lambda pid: _profile_label(next((p for p in ready_profiles if p["id"] == pid), {})),
                disabled=not ready_profiles,
            ) if ready_profiles else ""
            if not ready_profiles:
                st.warning("没有可用模型，请先到「模型配置」页面配置。")

        if st.form_submit_button(t('save_basic_info')):
            project.title = title
            project.description = description
            project.category = category
            project.genre = genre
            project.language = language
            old_profile_id = getattr(project, "model_profile_id", "")
            if selected_model_profile_id:
                profile = _find_model_profile(selected_model_profile_id)
                if profile:
                    project = _sync_project_model_fields(project, profile)
            st.session_state["project_data"] = project
            if old_profile_id != getattr(project, "model_profile_id", ""):
                st.session_state["llm_client"] = None  # 重置 LLM 客户端
            save_project()
            st.rerun()

    st.divider()

    # 术语表管理
    st.markdown(t('terminology_title'))
    st.caption(t('terminology_desc'))

    if project.terminology:
        for term, defn in list(project.terminology.items()):
            col_t, col_d, col_x = st.columns([2, 4, 1])
            with col_t:
                st.write(f"**{term}**")
            with col_d:
                st.write(defn)
            with col_x:
                if st.button("🗑️", key=f"del_term_{term}"):
                    del project.terminology[term]
                    st.session_state["project_data"] = project
                    save_project()
                    st.rerun()

    with st.form("add_terminology"):
        col_a, col_b = st.columns(2)
        with col_a:
            new_term = st.text_input(t('term_label'), placeholder=t('term_placeholder'))
        with col_b:
            new_defn = st.text_input(t('defn_label'), placeholder=t('defn_placeholder'))
        if st.form_submit_button(t('add_terminology')):
            if new_term.strip() and new_defn.strip():
                project.terminology[new_term.strip()] = new_defn.strip()
                st.session_state["project_data"] = project
                save_project()
                st.rerun()
            else:
                st.warning(t('term_empty_warning'))

    st.divider()

    # 风格指南
    st.markdown(t('style_guide'))
    style_guide = st.text_area(
        t('style_guide_label'),
        value=project.style_guide or "",
        height=200,
        placeholder=t('style_guide_placeholder'),
    )
    if st.button(t('save_style_guide')):
        project.style_guide = style_guide
        st.session_state["project_data"] = project
        save_project()

    st.divider()

    # RAG 文档管理
    st.markdown(t('rag_docs'))
    st.caption(t('rag_docs_desc'))

    if project.rag_documents:
        st.write(t('indexed_docs', n=len(project.rag_documents)))
        for doc_path in project.rag_documents:
            st.caption(str(doc_path))

    uploaded_files = st.file_uploader(
        t('upload_docs'),
        type=["pdf", "docx", "txt", "md", "markdown", "html", "htm", "xlsx", "xls"],
        accept_multiple_files=True,
        key="rag_upload",
        help="支持论文、报告、访谈稿、网页摘录、Markdown、Excel 表格等资料；默认先入资料库，不主动下载 HuggingFace embedding 模型。",
    )
    settings_build_vector_index = st.checkbox(
        "同时建立向量索引（使用模型设置里的独立资料索引 API 配置）",
        value=False,
        key="settings_build_vector_index",
    )
    if uploaded_files and st.button("导入资料库"):
        _index_rag_documents(project, uploaded_files, build_vector_index=settings_build_vector_index)

    st.divider()

    # 危险操作
    st.markdown(t('danger_zone'))
    col_del, col_reset = st.columns(2)
    with col_del:
        if st.button(t('delete_project'), type="primary", use_container_width=True):
            st.session_state["confirm_delete"] = True
    with col_reset:
        if st.button(t('reset_llm'), use_container_width=True):
            st.session_state["llm_client"] = None
            st.success(t('llm_reset_ok'))

    if st.session_state.get("confirm_delete"):
        st.error(t('confirm_delete_warning'))
        col_yes, col_no = st.columns(2)
        with col_yes:
            if st.button(t('confirm_delete_btn'), type="primary"):
                _delete_project(project)
        with col_no:
            if st.button(t('cancel')):
                st.session_state["confirm_delete"] = False
                st.rerun()


def _delete_source_document_from_project(project: ProjectKnowledgeBase, document_id: str) -> tuple[int, int]:
    """从项目资料库删除一个来源文档及其证据片段，并返回删除数量。"""
    document_id = str(document_id or "").strip()
    if not document_id:
        return 0, 0
    before_docs = len(getattr(project, "source_documents", []) or [])
    before_chunks = len(getattr(project, "evidence_chunks", []) or [])
    project.source_documents = [
        doc for doc in (getattr(project, "source_documents", []) or [])
        if str(getattr(doc, "id", "")) != document_id
    ]
    project.evidence_chunks = [
        chunk for chunk in (getattr(project, "evidence_chunks", []) or [])
        if str(getattr(chunk, "document_id", "")) != document_id
    ]
    return before_docs - len(project.source_documents), before_chunks - len(project.evidence_chunks)


def _delete_citation_from_project(project: ProjectKnowledgeBase, citation_id: str) -> int:
    """从项目引用库删除一条引用记录，并返回删除数量。"""
    citation_id = str(citation_id or "").strip()
    if not citation_id:
        return 0
    before = len(getattr(project, "citations", []) or [])
    project.citations = [
        citation for citation in (getattr(project, "citations", []) or [])
        if str(getattr(citation, "id", "")) != citation_id
    ]
    return before - len(project.citations)


def _delete_evidence_chunk_from_project(project: ProjectKnowledgeBase, chunk_id: str) -> int:
    """从项目资料库删除一条证据片段，并返回删除数量。"""
    chunk_id = str(chunk_id or "").strip()
    if not chunk_id:
        return 0
    before = len(getattr(project, "evidence_chunks", []) or [])
    project.evidence_chunks = [
        chunk for chunk in (getattr(project, "evidence_chunks", []) or [])
        if str(getattr(chunk, "id", "")) != chunk_id
    ]
    return before - len(project.evidence_chunks)


def _embedding_provider_from_material_index_config():
    """使用独立资料索引 API 配置创建 embedding provider。

    资料索引配置保存在 material_index_api.json，和上方正文写作模型档案互不影响；
    未启用或缺少 API Key/模型名时不回退 HuggingFace，也不借用聊天模型密钥。
    """
    from libriscribe.rag.embeddings import EmbeddingProvider

    config = _load_material_index_config()
    if not _material_index_config_ready(config):
        return EmbeddingProvider(allow_local_fallback=False)

    api_base = str(config.get("api_base", "") or "").strip()
    if api_base and not api_base.rstrip("/").endswith("/v1"):
        api_base = api_base.rstrip("/") + "/v1"

    return EmbeddingProvider(
        provider="custom_openai",
        model=str(config.get("model", "") or "DeepSeek-V4-Flash").strip(),
        api_base=api_base,
        api_key=str(config.get("api_key", "") or "").strip(),
        allow_local_fallback=False,
    )



def _format_source_upload_feedback(file_name: str, document: SourceDocument, chunks_count: int, added_vectors: int, vector_status: str) -> str:
    """生成用户可见的资料入库证明，明确资料已进入后续大纲/正文/引用链路。"""
    status_label = "已建立向量索引" if vector_status == "indexed" else "资料库模式"
    return (
        f"✅ 资料已入库：{file_name}\n"
        f"- 资料ID：{document.id}\n"
        f"- 证据片段：{chunks_count} 条\n"
        f"- 向量块：{added_vectors} 条\n"
        f"- 当前状态：{status_label}\n"
        f"- 后续用途：大纲生成、正文写作和引用参考都会读取该资料。"
    )



def _material_usage_feedback(project: Optional[ProjectKnowledgeBase], query: str = "", *, max_items: int = 5) -> str:
    """生成正文写作前后的资料库调用证明，展示来源文件和 evidence_id。"""
    if project is None:
        return ""
    documents_by_id = {
        str(getattr(doc, "id", "")): doc
        for doc in (getattr(project, "source_documents", []) or [])
        if str(getattr(doc, "id", "")).strip()
    }
    query_terms = [term for term in re.split(r"[\s，,。；;：:、（）()]+", str(query or "")) if len(term) >= 2]
    rows = []
    for chunk in getattr(project, "evidence_chunks", []) or []:
        text = _clean_project_display_text(getattr(chunk, "text", ""))
        if not _is_usable_evidence_text(text):
            continue
        doc = documents_by_id.get(str(getattr(chunk, "document_id", "")))
        source_name = getattr(doc, "file_name", "") if doc else ""
        if doc and not source_name:
            source_name = getattr(doc, "title", "")
        source_name = source_name or getattr(chunk, "source", "") or "资料库片段"
        score = 0
        for term in query_terms[:8]:
            if term and term in text:
                score += 2
            if term and term in source_name:
                score += 1
        rows.append((score, len(rows), source_name, getattr(chunk, "id", ""), text[:120]))
    rows.sort(key=lambda item: (-item[0], item[1]))
    if not rows:
        return ""
    lines = ["本次写作已调用资料库参考，提交给 AI 的资料来源包括："]
    for _, _, source_name, evidence_id, preview in rows[:max_items]:
        lines.append(f"- {source_name}（evidence_id={evidence_id}）：{preview}")
    return "\n".join(lines)



def _index_rag_documents(project: ProjectKnowledgeBase, uploaded_files, *, build_vector_index: bool = False) -> None:
    """导入上传资料并尽力建立向量索引。

    资料库是大纲、正文和引用参考的主来源；embedding/Chroma 失败时不能阻断上传资料入库，
    因此先保存文件和证据片段，再把向量索引作为可降级的增强能力。
    """
    try:
        from libriscribe.rag.document_loader import DocumentLoader

        loader = DocumentLoader()
        store = None
        vector_warning = "未启用向量索引：资料已先以资料库模式导入，避免上传时访问 HuggingFace 导致超时。"

        if build_vector_index:
            from libriscribe.rag.vector_store import VectorStore

            embedding_provider = None
            vector_warning = ""
            try:
                embedding_provider = _embedding_provider_from_material_index_config()
                if embedding_provider.provider == "custom_openai":
                    st.info(f"使用独立资料索引 API 配置建立索引：{embedding_provider.model}")
                else:
                    st.warning("资料索引 API 未启用或配置不完整，本次将以资料库模式导入。")
                    embedding_provider = None
            except Exception as emb_err:
                vector_warning = f"Embedding 初始化失败：{emb_err}。本次将以资料库模式导入，不阻断大纲和正文参考。"
                st.warning(vector_warning)
                embedding_provider = None

            if embedding_provider is not None:
                try:
                    store = VectorStore(embedding_provider=embedding_provider)
                except Exception as store_err:
                    vector_warning = f"向量库初始化失败：{store_err}。本次将以资料库模式导入。"
                    st.warning(vector_warning)
                    store = None

        project_dir = Path(st.session_state.get("project_dir", "."))
        docs_dir = project_dir / "documents"
        docs_dir.mkdir(parents=True, exist_ok=True)

        upload_feedback = []
        for uploaded_file in uploaded_files:
            file_path = docs_dir / uploaded_file.name
            with open(file_path, "wb") as f:
                f.write(uploaded_file.getbuffer())

            chunks = [
                chunk for chunk in loader.load_file(str(file_path))
                if loader.is_usable_text(getattr(chunk, "content", ""))
            ]
            if not chunks:
                st.warning(t('rag_parse_fail', name=uploaded_file.name))
                continue

            added = 0
            indexing_error = ""
            if store is not None:
                try:
                    added = store.add_documents(chunks)
                except Exception as index_err:
                    indexing_error = str(index_err)
                    logger.warning("Vector indexing failed for %s: %s", uploaded_file.name, index_err)
                    st.warning(f"{uploaded_file.name} 向量索引失败，已保留为资料库参考：{index_err}")
            elif vector_warning:
                indexing_error = vector_warning

            first_meta = chunks[0].metadata or {}
            vector_status = "indexed" if added > 0 and not indexing_error else "library_only"
            document = SourceDocument(
                id=str(first_meta.get("source_id", "")),
                title=file_path.stem,
                source_type=str(first_meta.get("file_type", file_path.suffix.lower())),
                file_path=str(file_path),
                file_name=uploaded_file.name,
                file_hash=str(first_meta.get("file_hash", "")),
                chunk_count=len(chunks),
                indexed_at=datetime.now().isoformat(),
                status=vector_status,
                summary=(chunks[0].content or "")[:600],
                metadata={
                    "origin": "user_upload",
                    "added_chunks": added,
                    "vector_indexed": bool(added > 0 and not indexing_error),
                    "vector_index_error": indexing_error,
                    "can_use_for_outline": True,
                    "can_use_for_draft": True,
                    "can_use_for_reference": True,
                },
            )
            project.add_source_document(document)
            for chunk in chunks:
                meta = dict(chunk.metadata or {})
                meta.update({
                    "origin": "user_upload",
                    "document_status": vector_status,
                    "vector_indexed": bool(added > 0 and not indexing_error),
                    "can_use_for_outline": True,
                    "can_use_for_draft": True,
                    "can_use_for_reference": True,
                })
                project.add_evidence_chunk(EvidenceChunk(
                    id=str(meta.get("evidence_id", chunk.chunk_id)),
                    document_id=document.id,
                    source=uploaded_file.name,
                    text=chunk.content[:1800],
                    chunk_index=int(meta.get("chunk_index", 0) or 0),
                    chunk_hash=str(meta.get("chunk_hash", "")),
                    metadata=meta,
                ))
            if str(file_path) not in project.rag_documents:
                project.rag_documents.append(str(file_path))
            feedback_text = _format_source_upload_feedback(uploaded_file.name, document, len(chunks), added, vector_status)
            upload_feedback.append(feedback_text)
            st.success(feedback_text)

        st.session_state["project_data"] = project
        if upload_feedback:
            st.session_state["last_source_upload_feedback"] = upload_feedback
        save_project()

    except ImportError as e:
        st.error(t('rag_unavailable', e=e))
    except Exception as e:
        st.error(t('rag_index_fail', e=e))
        logger.exception("RAG indexing failed")


def _delete_project(project: ProjectKnowledgeBase) -> None:
    """删除项目"""
    project_path = st.session_state.get("project_file", "") or str(Path(st.session_state.get("project_dir", "")) / "knowledge_base.json")
    if _delete_project_by_path(project_path):
        st.success(t('project_deleted', title=project.title))
    st.session_state["project_data"] = None
    st.session_state["project_file"] = None
    st.session_state["project_dir"] = None
    st.session_state["llm_client"] = None
    st.session_state["confirm_delete"] = False
    st.rerun()


# ══════════════════════════════════════════════════════════════════════
#  AI 配置页面
# ══════════════════════════════════════════════════════════════════════

def render_ai_config_page() -> None:
    """统一模型配置页：官方平台与自定义平台都在这里维护，项目只选择模型档案。"""
    st.title(t('ai_config_title'))
    st.caption("AI 配置永久读取本地配置文件；保存后会写入磁盘，下次启动仍然保留。")

    profiles = _load_model_profiles()
    provider_options = LLM_PROVIDERS

    st.markdown("### 模型档案")
    st.caption(f"永久配置文件：`{MODEL_PROFILE_CONFIG.as_posix()}`")
    ready_profiles = [p for p in profiles if p.get("enabled") and p.get("api_key") and p.get("model")]
    if ready_profiles:
        st.success("已从本地配置读取可用 AI：" + "；".join(_profile_label(p) for p in ready_profiles))
    else:
        st.warning("本地配置文件中还没有可用 AI。请填写并保存一次，之后会永久读取该配置。")

    profile_ids = [p["id"] for p in profiles]
    selected_id = st.selectbox(
        "选择要编辑的模型档案",
        profile_ids + ["__new__"],
        format_func=lambda pid: "新增模型档案" if pid == "__new__" else _profile_label(next((p for p in profiles if p["id"] == pid), {})),
        key="model_profile_editor_select",
    )
    editing = next((p for p in profiles if p.get("id") == selected_id), None) if selected_id != "__new__" else None
    default_provider = editing.get("provider", "openai") if editing else "custom"
    form_key = f"model_profile_form_{selected_id}"
    st.caption("已按所选模型档案刷新下方配置；不同模型的 API Base、模型名和提示说明互相独立。")

    with st.form(form_key, clear_on_submit=False):

        col1, col2 = st.columns(2)
        with col1:
            name = st.text_input("档案名称", value=editing.get("name", "") if editing else "", key=f"profile_name_{selected_id}")
            provider = st.selectbox(
                "平台类型",
                provider_options,
                index=provider_options.index(default_provider) if default_provider in provider_options else 0,
                format_func=lambda p: PROVIDER_DISPLAY_NAMES.get(p, p),
                key=f"profile_provider_{selected_id}",
            )
            model_name = st.text_input(
                t('model_name_label'),
                value=editing.get("model", DEFAULT_PROVIDER_MODELS.get(provider, "")) if editing else DEFAULT_PROVIDER_MODELS.get(provider, ""),
                placeholder=t('model_name_placeholder'),
                help=f"推荐默认：{DEFAULT_PROVIDER_MODELS.get(provider, '') or '按平台文档填写'}。模型名必须与平台控制台/文档完全一致。",
                key=f"profile_model_{selected_id}",
            )
        with col2:
            default_base = editing.get("api_base", "") if editing else ""
            if not default_base and provider == "openrouter":
                default_base = Settings().openrouter_base_url
            guidance = _model_provider_guidance(provider, model_name)
            api_base = st.text_input(
                t('api_base_url'),
                value=default_base,
                placeholder="官方平台可留空；自定义/OpenRouter 可填写 https://.../v1",
                help=guidance.get("api_base", ""),
                key=f"profile_api_base_{selected_id}_{provider}",
            )
            existing_api_key = editing.get("api_key", "") if editing else ""
            api_key = st.text_input(
                t('api_key_label'),
                value="",
                type="password",
                placeholder="留空则保持已保存密钥；新增档案时必须填写",
                help="为避免浏览器/Streamlit 密码框清空导致保存失败，编辑已有模型时可不重新输入密钥。",
                key=f"profile_api_key_{selected_id}",
            )
            if existing_api_key:
                st.caption("已保存密钥：••••••••（保存时留空将继续使用原密钥）")
            enabled = st.checkbox("启用此模型", value=bool(editing.get("enabled", False)) if editing else True, key=f"profile_enabled_{selected_id}")

        guidance = _model_provider_guidance(provider, model_name)
        st.info(
            f"**{guidance['title']}**\n\n"
            f"- 推荐/默认模型：`{guidance.get('recommended_model') or '按平台文档填写'}`\n"
            f"- 当前填写模型：`{guidance.get('current_model') or '未填写'}`\n"
            f"- 必填信息：{guidance.get('required', '')}\n"
            f"- API Base：{guidance.get('api_base', '')}"
        )
        notes = guidance.get("notes") or []
        if notes:
            st.warning("\n".join(f"- {note}" for note in notes))
        link_cols = st.columns(2)
        if guidance.get("key_url"):
            link_cols[0].link_button("获取 API Key", guidance["key_url"], use_container_width=True)
        else:
            link_cols[0].caption("自定义平台请到对应服务商控制台获取 API Key。")
        if guidance.get("model_url"):
            link_cols[1].link_button("查看模型名/文档", guidance["model_url"], use_container_width=True)
        else:
            link_cols[1].caption("模型名以第三方平台文档为准。")

        col_save, col_delete = st.columns(2)
        save_profile = col_save.form_submit_button("保存模型档案", use_container_width=True)
        delete_profile = col_delete.form_submit_button("删除当前档案", use_container_width=True, disabled=selected_id == "__new__")

        if save_profile:
            if not name.strip():
                name = PROVIDER_DISPLAY_NAMES.get(provider, provider)
            effective_api_key = api_key.strip() or (editing.get("api_key", "") if editing else "")
            if not effective_api_key:
                st.error("请填写 API 密钥。编辑已有模型时可留空沿用原密钥。")
            elif not model_name.strip():
                st.error("请填写模型名称。")
            else:
                if editing:
                    profile_id = editing["id"]
                    profiles = [p for p in profiles if p.get("id") != profile_id]
                else:
                    profile_id = _profile_id(provider, name)
                    existing_ids = {p.get("id") for p in profiles}
                    if profile_id in existing_ids:
                        profile_id = f"{profile_id}_{uuid.uuid4().hex[:6]}"
                profiles.append({
                    "id": profile_id,
                    "name": name.strip(),
                    "provider": provider,
                    "api_base": api_base.rstrip("/"),
                    "api_key": effective_api_key,
                    "model": model_name.strip(),
                    "enabled": enabled,
                    "source": "official" if provider != "custom" else "custom",
                    "updated_at": datetime.now().isoformat(),
                })
                _save_model_profiles(profiles)
                st.success("模型档案已保存。")
                st.rerun()

        if delete_profile and editing:
            profiles = [p for p in profiles if p.get("id") != editing.get("id")]
            _save_model_profiles(profiles)
            st.success("模型档案已删除。")
            st.rerun()

    st.divider()
    st.markdown("### 资料索引 API 配置")
    st.caption(f"单独用于上传资料建立向量索引，配置文件：`{MATERIAL_INDEX_CONFIG.as_posix()}`。它不读取、不修改上方模型档案。")
    index_config = _load_material_index_config()
    with st.form("material_index_api_config_form", clear_on_submit=False):
        index_enabled = st.checkbox(
            "启用资料向量索引 API",
            value=bool(index_config.get("enabled", False)),
            key="material_index_enabled",
            help="关闭时上传资料仍会进入资料库，大纲和正文仍可直接读取资料片段；只是不会建立 Chroma 向量索引。",
        )
        index_col1, index_col2 = st.columns(2)
        with index_col1:
            index_api_base = st.text_input(
                "资料索引 API Base",
                value=str(index_config.get("api_base", "") or ""),
                placeholder="例如：https://api.deepseek.com/v1",
                help="填写到 /v1 即可，程序会调用 OpenAI-compatible /embeddings 接口。",
                key="material_index_api_base",
            )
            index_model = st.text_input(
                "资料索引模型",
                value=str(index_config.get("model", "") or "DeepSeek-V4-Flash"),
                placeholder="例如：DeepSeek-V4-Flash",
                help="必须是服务商支持 embeddings 的模型名，不是正文聊天模型名。",
                key="material_index_model",
            )
        with index_col2:
            existing_index_key = str(index_config.get("api_key", "") or "")
            index_api_key = st.text_input(
                "资料索引 API Key",
                value="",
                type="password",
                placeholder="留空则保持已保存索引密钥",
                help="仅保存到独立资料索引配置文件。不要把密钥写入提示词、资料或源码。",
                key="material_index_api_key",
            )
            if existing_index_key:
                st.caption("已保存资料索引密钥：••••••••（保存时留空将继续使用原密钥）")
            st.info("DeepSeek 示例：API Base 填 `https://api.deepseek.com/v1`，模型填 `DeepSeek-V4-Flash`。")
        save_index_config = st.form_submit_button("保存资料索引 API 配置", type="primary", use_container_width=True)
        if save_index_config:
            effective_index_key = index_api_key.strip() or existing_index_key
            if index_enabled and not effective_index_key:
                st.error("启用资料索引 API 时请填写 API Key；如不需要向量索引，可关闭此开关。")
            elif index_enabled and not index_model.strip():
                st.error("启用资料索引 API 时请填写 embeddings 模型名。")
            else:
                _save_material_index_config({
                    "enabled": index_enabled,
                    "api_base": index_api_base,
                    "api_key": effective_index_key,
                    "model": index_model,
                })
                st.success("资料索引 API 配置已保存；不会影响上方模型档案。")
                st.rerun()

    st.divider()
    st.markdown("### 在线状态检测")
    test_prompt = st.text_area(t('test_prompt'), value=t('test_prompt_default'), height=80, key="ai_test_prompt")
    col_test_one, col_test_all = st.columns(2)
    selected_test_id = col_test_one.selectbox(
        "选择检测对象",
        [p["id"] for p in profiles],
        format_func=lambda pid: _profile_label(next((p for p in profiles if p["id"] == pid), {})),
        key="profile_test_select",
    ) if profiles else ""
    if col_test_one.button("检测选中模型", use_container_width=True, disabled=not selected_test_id):
        profile = next((p for p in profiles if p.get("id") == selected_test_id), None)
        if profile:
            ok, msg = _profile_connection_result(profile, test_prompt)
            if ok:
                st.success(f"{_profile_label(profile)} 在线可用")
                st.info(msg)
            else:
                st.error(f"{_profile_label(profile)} 检测失败：{msg}")

    if col_test_all.button("一键检测全部已启用模型", use_container_width=True, disabled=not profiles):
        for profile in [p for p in profiles if p.get("enabled")]:
            ok, msg = _profile_connection_result(profile, test_prompt)
            if ok:
                st.success(f"{_profile_label(profile)} 在线可用")
                st.caption(msg)
            else:
                st.error(f"{_profile_label(profile)} 检测失败：{msg}")

    st.divider()
    st.markdown("### 项目当前使用")
    project: Optional[ProjectKnowledgeBase] = st.session_state.get("project_data")
    if project is None:
        st.caption("当前未加载项目。创建项目或项目设置中会直接选择这里的模型档案。")
    else:
        current_profile = _resolve_project_model_profile(project)
        st.info(f"当前项目模型：{_profile_label(current_profile) if current_profile else project.llm_provider}")
        ready_profiles = _available_model_profiles(require_ready=True)
        if ready_profiles:
            ids = [p["id"] for p in ready_profiles]
            selected_project_profile = st.selectbox(
                "切换当前项目模型",
                ids,
                index=ids.index(current_profile["id"]) if current_profile and current_profile.get("id") in ids else 0,
                format_func=lambda pid: _profile_label(next((p for p in ready_profiles if p["id"] == pid), {})),
                key="project_profile_switch",
            )
            if st.button("应用到当前项目", use_container_width=True):
                profile = _find_model_profile(selected_project_profile)
                if profile:
                    updated = _sync_project_model_fields(project, profile)
                    st.session_state["project_data"] = updated
                    st.session_state["llm_client"] = None
                    save_project()
                    st.success("当前项目模型已更新。")
                    st.rerun()
        else:
            st.warning("没有可用模型，请先保存并启用一个模型档案。")


def _do_test_connection(provider: str, api_base: str, api_key: str, model_name: str, test_prompt: str) -> None:
    """兼容旧调用的单模型连接测试。"""
    profile = {
        "id": "adhoc",
        "name": PROVIDER_DISPLAY_NAMES.get(provider, provider),
        "provider": provider,
        "api_base": api_base,
        "api_key": api_key,
        "model": model_name or DEFAULT_PROVIDER_MODELS.get(provider, ""),
        "enabled": True,
    }
    with st.spinner(t('thinking')):
        ok, msg = _profile_connection_result(profile, test_prompt)
    if ok:
        st.success(t('test_success'))
        st.markdown(f"**{t('model_response')}:**")
        st.info(msg)
    else:
        st.error(t('test_fail', e=msg))


def _current_project() -> Optional[ProjectKnowledgeBase]:
    """返回当前加载项目，供商业化页面骨架复用。"""
    return st.session_state.get("project_data")


def _render_business_hero(title: str, subtitle: str, badge: str = "") -> None:
    """统一页面头部；未传 badge 时不显示默认品牌角标。"""
    badge_html = f'<span class="hb-hero-badge">{badge}</span>' if badge else ""
    st.markdown(
        f"""
        <div class="hb-hero">
            {badge_html}
            <h1>{title}</h1>
            <p>{subtitle}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _stage_status_class(status: str) -> str:
    """将流水线状态映射到商业化视觉状态类。"""
    normalized = (status or "pending").replace(" ", "_").lower()
    return normalized if normalized in {"completed", "in_progress", "blocked", "optional", "failed", "risk", "risky"} else "pending"


def _render_stage_cards(stages: list[dict], *, columns: int = 2) -> None:
    """以产品级卡片渲染生产流水线阶段。"""
    if not stages:
        st.info("暂无流水线阶段数据。")
        return
    grid_class = "hb-product-grid" if columns == 2 else "hb-action-grid"
    cards = []
    for stage in stages:
        status = str(stage.get("status", "pending"))
        status_class = _stage_status_class(status)
        progress = 100 if status == "completed" else 45 if status == "in_progress" else 18 if status == "optional" else 8
        cards.append(
            f"""
            <div class="hb-stage-card">
                <div class="hb-stage-head">
                    <div class="hb-stage-title">{stage.get('order', '')}. {stage.get('title', '')}</div>
                    <span class="hb-status-pill hb-status-{status_class}">{status}</span>
                </div>
                <div class="hb-stage-desc">{stage.get('description', '')}</div>
                <div class="hb-stage-desc"><strong>用户：</strong>{stage.get('user_action', '')}</div>
                <div class="hb-stage-desc"><strong>AI：</strong>{stage.get('agent_action', '')}</div>
                <div class="hb-stage-desc"><strong>产出：</strong>{stage.get('output', '')}</div>
                <div class="hb-progress-track"><div class="hb-progress-fill" style="width:{progress}%"></div></div>
            </div>
            """
        )
    st.markdown(f"<div class=\"{grid_class}\">{''.join(cards)}</div>", unsafe_allow_html=True)


def render_workspace_page() -> None:
    """项目驾驶舱；保留旧 Dashboard 的创建/加载能力。"""
    project = _current_project()
    if project is None:
        render_dashboard()
        return

    quality = QualityService().summarize_project_quality(project)
    source_summary = SourceService().source_summary(project)
    outline_summary = OutlineService().outline_summary(project)

    col1, col2, col3 = st.columns(3)
    col1.metric("资料/文献", source_summary.get("documents", 0))
    col2.metric("大纲单元", outline_summary.get("sections", 0))
    col3.metric("正文完成度", f"{quality.get('completion_score', 0)}%")

    with st.expander("旧版项目总览与创建/加载入口", expanded=False):
        render_dashboard()


def render_projects_page() -> None:
    """项目创建与加载入口，复用旧 Dashboard 的稳定能力。"""
    render_dashboard()


def render_pipeline_page() -> None:
    """已废弃：一小时写书工作台页面，自动重定向到首页。"""
    st.session_state["current_page"] = "Workspace"
    st.rerun()


def render_citations_page() -> None:
    """引用与事实核验中心页面。"""
    _render_business_hero("引用与事实核验中心", "面向商用交付的引用完整性、来源绑定、页码定位和幻觉风险核验。")
    project = _current_project()
    if project is None:
        st.warning(t('load_project_first'))
        return

    citation_service = CitationService()
    st.warning(
        '参考文献不能因为是 GPT 写出来就默认真实。系统现在会把粘贴/AI 生成的参考文献先标为\u201c风险/未核验\u201d，'
        '只有绑定上传资料证据片段、DOI/URL 或人工在可信数据库核验后，才能进入已核验链路。'
    )

    # ---- 顶部统计指标 ----
    summary = citation_service.citation_risk_summary(project)
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("引用总数", summary.get("total", 0))
    col2.metric("已核验", summary.get("verified", 0))
    col3.metric("未核验", summary.get("unverified", 0))
    col4.metric("风险引用", summary.get("risky", 0))
    col5.metric("缺少定位", summary.get("missing_locator", 0))

    # ---- 从资料来源页跳转来的筛选标志 ----
    citation_filter = st.session_state.pop("citation_filter_status", None)
    citations_raw = citation_service.list_citations(project)
    citations = [c.dict() if hasattr(c, "dict") else c for c in citations_raw]

    # ---- 主区域：引用列表 + 添加引用（置顶，用户最需要） ----
    st.divider()
    col_list_head, col_add_btn = st.columns([3, 1])
    with col_list_head:
        filter_label = ""
        if citation_filter == "unverified":
            filter_label = "（已筛选：仅显示未核验引用）"
        st.markdown(f"### 引用记录管理{filter_label}")
    with col_add_btn:
        if st.button("＋ 添加引用", use_container_width=True, type="primary", key="citation_add_top_btn"):
            st.session_state["citation_show_add_form"] = True
            st.rerun()

    st.caption("所有引用都可以在这里查看详情、删除或补充；OpenAlex 导入记录默认显示为已核验。点击上方 ＋ 按钮手动添加引用。")

    # 自定义添加引用表单（内联，默认收起；点击按钮后展开）
    if st.session_state.pop("citation_show_add_form", False):
        with st.container(border=True):
            st.markdown("#### 自定义添加一条引用文献")
            st.caption("手动录入已经掌握的论文、报告、网页或图书引用；默认标记为未核验，后续可人工核验 DOI/URL。")
            with st.form("custom_citation_add_form", clear_on_submit=True):
                col_title, col_year = st.columns([3, 1])
                with col_title:
                    custom_title = st.text_input("题名", key="custom_citation_title")
                with col_year:
                    custom_year = st.text_input("年份", key="custom_citation_year")
                custom_authors = st.text_input("作者（多个用逗号或分号分隔）", key="custom_citation_authors")
                custom_source = st.text_input("期刊/出版社/网站/来源", key="custom_citation_source")
                col_doi, col_url = st.columns(2)
                with col_doi:
                    custom_doi = st.text_input("DOI（可选）", key="custom_citation_doi")
                with col_url:
                    custom_url = st.text_input("URL（可选）", key="custom_citation_url")
                custom_ref = st.text_area("GB/T 7714 格式参考文献（可选；不填则系统按字段拼接）", height=72, key="custom_citation_formatted_ref")
                submitted_custom_citation = st.form_submit_button("确认添加引用", type="primary", use_container_width=True)
                if submitted_custom_citation:
                    if not custom_title.strip() and not custom_ref.strip():
                        st.error("请至少填写题名或完整格式参考文献。")
                    else:
                        authors = [item.strip() for item in re.split(r"[,，;；、]", custom_authors) if item.strip()]
                        formatted_ref = custom_ref.strip() or f"{'，'.join(authors) or '佚名'}．{custom_title.strip()}．{custom_source.strip() or '未注明来源'}，{custom_year.strip() or '年份不详'}．"
                        citation = Citation(
                            id=f"manual_{uuid.uuid4().hex[:10]}",
                            source=custom_source.strip() or custom_title.strip() or "自定义引用",
                            formatted_ref=formatted_ref,
                            doi=custom_doi.strip(),
                            url=custom_url.strip(),
                            status="unverified",
                            confidence=0.0,
                            metadata={
                                "origin": "manual_custom_citation",
                                "title": custom_title.strip(),
                                "authors": authors,
                                "year": custom_year.strip(),
                                "created_at": datetime.now().isoformat(),
                            },
                        )
                        project.add_citation(citation)
                        if save_project():
                            st.success("已添加自定义引用，并标记为未核验。")
                            st.rerun()

    # 引用卡片列表
    if citations_raw:
        display_citations = citations_raw
        if citation_filter == "unverified":
            display_citations = [c for c in citations_raw if getattr(c, "status", "unverified") != "verified"]
        if not display_citations:
            st.info("当前筛选条件下没有匹配的引用记录。")
        else:
            for citation in display_citations:
                citation_id = str(getattr(citation, "id", "") or "")
                title = (getattr(citation, "formatted_ref", "") or getattr(citation, "source", "") or citation_id or "未命名引用")[:160]
                c_status = getattr(citation, "status", "") or "-"
                status_icon = {"verified": "✅", "unverified": "⚠️", "risky": "❌"}.get(c_status, "❓")
                with st.container(border=True):
                    c1, c2, c3 = st.columns([4, 1.2, 1])
                    c1.markdown(f"**{title}**")
                    c1.caption(f"ID: {citation_id or '-'} | 来源：{getattr(citation, 'source', '') or '-'}")
                    c2.markdown(f"{status_icon} {c_status}")
                    if c3.button("删除引用", key=f"delete_citation_{citation_id}", use_container_width=True, disabled=not bool(citation_id)):
                        deleted = _delete_citation_from_project(project, citation_id)
                        if save_project():
                            st.success(f"已删除引用 {deleted} 条。")
                            st.rerun()
                    with st.expander("查看引用详情", expanded=False):
                        st.write(f"格式化引用：{getattr(citation, 'formatted_ref', '') or '-'}")
                        st.write(f"DOI：{getattr(citation, 'doi', '') or '-'}")
                        st.write(f"URL：{getattr(citation, 'url', '') or '-'}")
                        st.write(f"页码/定位：{getattr(citation, 'page', '') or '-'}")
                        st.write(f"置信度：{getattr(citation, 'confidence', 0.0)}")
                        st.json(getattr(citation, "metadata", {}) or {})
    else:
        st.info("暂无引用记录。可以通过上方 ＋ 按钮手动添加，或通过下方工具粘贴批量导入。")

    # ---- 下部工具区（折叠以保持页面整洁） ----
    st.divider()
    st.markdown("### 更多工具")

    with st.expander("📋 粘贴参考文献并生成核验任务", expanded=summary.get("total", 0) == 0):
        st.caption("支持粘贴 [1]作者．题名[J]．刊名，年份，卷(期)：页码． 这类格式。导入后不会自动视为真实文献。")
        reference_text = st.text_area(
            "参考文献列表",
            height=180,
            placeholder="[1]张三．某某研究[J]．某某期刊，2024，10(2)：1-8．",
            key="citation_reference_import_text",
        )
        preview_items = citation_service.parse_reference_text(reference_text)
        if preview_items:
            st.markdown("**解析预览（导入后默认风险/未核验）：**")
            st.dataframe(
                [
                    {
                        "题名": item.get("title", ""),
                        "作者": "、".join(item.get("authors", [])[:3]),
                        "来源": item.get("source", ""),
                        "年份": item.get("year", ""),
                        "类型": item.get("source_type", ""),
                        "核验检索词": citation_service.build_reference_search_query(item),
                    }
                    for item in preview_items
                ],
                use_container_width=True,
                hide_index=True,
            )
        if st.button("导入为待核验参考文献", type="primary", use_container_width=True, disabled=not bool(preview_items)):
            imported = citation_service.import_reference_text(project, reference_text)
            if save_project():
                st.success(f"已导入 {len(imported)} 条参考文献；均已标记为风险/未核验，请继续核验来源。")
                st.rerun()

    coverage_rows = citation_service.coverage_matrix(project)
    with st.expander("🔗 引用证据闭环矩阵", expanded=False):
        if coverage_rows:
            st.dataframe(coverage_rows, use_container_width=True)
        else:
            st.info("暂无引用闭环数据。写作生成或手动绑定证据后，将在这里显示引用—证据—来源文档链路。")

    with st.expander("🌐 联网/外部检索核验入口", expanded=False):
        st.caption("当前版本提供核验检索词与外部检索入口；是否能访问知网、万方、Google Scholar 等取决于本机网络和账号权限。")
        risky_citations = [c for c in citations_raw if getattr(c, "status", "unverified") != "verified"]
        if risky_citations:
            selected = st.selectbox(
                "选择一条未核验引用",
                risky_citations,
                format_func=lambda c: (getattr(c, "formatted_ref", "") or getattr(c, "source", "") or getattr(c, "id", ""))[:120],
                key="citation_verify_select",
            )
            query = citation_service.build_reference_search_query(selected)
            st.text_input("建议检索词", value=query, key="citation_verify_query")
            links = citation_service.reference_verification_links(query)
            if links:
                link_cols = st.columns(len(links))
                for idx, (label, url) in enumerate(links.items()):
                    link_cols[idx].link_button(label, url, use_container_width=True)
            with st.form("manual_citation_verify_form"):
                st.caption("人工核验后，可填写 DOI/URL 并标记为已核验。建议同时在资料库上传原文，形成证据片段闭环。")
                doi = st.text_input("DOI（可选）", value=getattr(selected, "doi", ""))
                url = st.text_input("URL/数据库链接（可选）", value=getattr(selected, "url", ""))
                page_text = st.text_input("页码/定位（可选）", value=str(getattr(selected, "page", "") or ""))
                mark_verified = st.form_submit_button("人工确认已核验", type="primary")
                if mark_verified:
                    selected.doi = doi.strip()
                    selected.url = url.strip()
                    if page_text.strip().isdigit():
                        selected.page = int(page_text.strip())
                    selected.status = "verified"
                    selected.confidence = max(float(getattr(selected, "confidence", 0.0) or 0.0), 0.7)
                    selected.metadata = dict(getattr(selected, "metadata", {}) or {})
                    selected.metadata["verification_note"] = "已由用户人工通过外部检索或数据库核验。"
                    if save_project():
                        st.success("已标记为人工核验。")
                        st.rerun()
        else:
            st.success("当前没有未核验引用。")

    with st.expander("📊 原始引用记录表", expanded=False):
        if citations:
            st.dataframe(citations, use_container_width=True)
        else:
            st.caption("暂无引用记录。")


def render_quality_page() -> None:
    """审校与质量中心页面。"""
    _render_business_hero("审校与质量中心", "对结构完整度、资料覆盖、引用链、术语一致性和交付风险进行出版前体检。")
    project = _current_project()
    if project is None:
        st.warning(t('load_project_first'))
        return

    quality_service = QualityService()
    summary = quality_service.summarize_project_quality(project)
    export_chapters = _collect_chapters(project)
    export_report = quality_service.export_readiness_report(export_chapters)
    manuscript_report = quality_service.manuscript_quality_report(export_chapters, citations=getattr(project, "citations", []))
    source_service = SourceService()
    document_rows = source_service.document_coverage(project)
    gap_rows = source_service.chapter_source_gaps(project)

    cols = st.columns(4)
    cols[0].metric("结构完成度", f"{summary.get('completion_score', 0)}%")
    cols[1].metric("资料覆盖", f"{summary.get('coverage_score', 0)}%")
    cols[2].metric("引用健康", f"{summary.get('citation_score', 0)}%")
    cols[3].metric("正文质量", f"{manuscript_report.get('quality_score', 0)}/100", manuscript_report.get("status", ""))
    st.metric("导出就绪", f"{export_report.get('readiness_score', 0)}/100", export_report.get("status", ""))

    st.markdown("### 出版前质量体检")
    st.dataframe(
        [
            {"检查项": "结构完成度", "得分": summary.get("completion_score", 0), "说明": "章节与四级写作单元完成情况"},
            {"检查项": "资料覆盖", "得分": summary.get("coverage_score", 0), "说明": "资料、证据片段与写作单元覆盖情况"},
            {"检查项": "引用健康", "得分": summary.get("citation_score", 0), "说明": "引用核验、来源绑定、页码定位与风险状态"},
            {"检查项": "正文质量", "得分": manuscript_report.get("quality_score", 0), "说明": "内容深度、伪引用、无来源事实句、专著语体和标题结构"},
            {"检查项": "导出就绪", "得分": export_report.get("readiness_score", 0), "说明": "最终交付稿清洁度、重复标题、过程信息残留和基础内容缺口"},
        ],
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("### 导出前交付风险")
    if export_report.get("warnings"):
        st.dataframe(export_report["warnings"], use_container_width=True, hide_index=True)
    else:
        st.success("当前导出稿未发现明显过程信息残留、重复章标题或空章节风险。")
    with st.expander("导出就绪原始报告", expanded=False):
        st.json(export_report)

    st.markdown("### 正文生成质量风险")
    if manuscript_report.get("issues"):
        st.dataframe(manuscript_report["issues"], use_container_width=True, hide_index=True)
    else:
        st.success("当前正文未发现明显内容深度、伪引用、无来源事实句或专著语体风险。")
    with st.expander("正文质量原始报告", expanded=False):
        st.json(manuscript_report)

    st.markdown("### 来源文档覆盖")
    if document_rows:
        st.dataframe(document_rows, use_container_width=True)
    else:
        st.info("暂无来源文档覆盖数据。请先在资料库/RAG 页面上传并索引资料。")

    st.markdown("### 章节资料缺口")
    if gap_rows:
        st.dataframe(gap_rows, use_container_width=True)
    else:
        st.caption("暂无章节资料缺口；当前章节、资料或证据数据不足以生成缺口矩阵。")

    with st.expander("质量指标原始 JSON", expanded=False):
        st.json(summary)


def render_prompts_page() -> None:
    """全局提示词查看、编辑与优化方向页面。"""
    _render_business_hero("提示词", "展示之前设置的所有全局提示词；这里保存后对所有项目生效，不再绑定单个项目。")
    _render_global_prompts_editor(expanded_first=True)


def render_global_settings_page() -> None:
    """左上角隐藏入口进入的全局设置页面。"""
    _render_business_hero("全局设置", "统一管理网站名称、全局参数、视觉风格、默认模型和所有全局提示词。")
    service = GlobalSettingsService()
    settings = service.load()
    style = dict(settings.get("style", {}) or {})
    params = dict(settings.get("parameters", {}) or {})
    model = dict(settings.get("model", {}) or {})

    tab_base, tab_params, tab_style, tab_model, tab_prompts = st.tabs(["网站", "全局参数", "风格", "模型", "提示词"])

    with tab_base:
        site_name = st.text_input("网站名称", value=str(settings.get("site_name") or "好编辑"))
        site_subtitle = st.text_area("网站副标题/说明", value=str(settings.get("site_subtitle") or ""), height=90)
        if st.button("保存网站设置", type="primary", use_container_width=True, key="save_global_site"):
            settings["site_name"] = site_name.strip() or "好编辑"
            settings["site_subtitle"] = site_subtitle.strip()
            path = service.save(settings)
            st.success(f"全局网站设置已保存：{path}")
            st.rerun()

    with tab_params:
        params["default_language"] = st.selectbox(
            "默认项目语言",
            PROJECT_LANGUAGES,
            index=PROJECT_LANGUAGES.index(params.get("default_language", "简体中文")) if params.get("default_language", "简体中文") in PROJECT_LANGUAGES else 0,
        )
        params["rag_top_k"] = st.number_input("RAG 默认检索条数", min_value=1, max_value=20, value=int(params.get("rag_top_k", 5)))
        params["target_word_tolerance"] = st.number_input("目标字数容差（%）", min_value=5, max_value=80, value=int(params.get("target_word_tolerance", 20)))
        params["anti_hallucination"] = st.checkbox("启用反幻觉约束", value=bool(params.get("anti_hallucination", True)))
        params["fullwidth_indent"] = st.checkbox("中文段落强制两个全角空格缩进", value=bool(params.get("fullwidth_indent", True)))
        if st.button("保存全局参数", type="primary", use_container_width=True, key="save_global_params"):
            settings["parameters"] = params
            path = service.save(settings)
            st.success(f"全局参数已保存：{path}")

    with tab_style:
        style["theme"] = st.text_input("主题名称", value=str(style.get("theme") or "米白玻璃风"))
        style["primary_color"] = st.text_input("主色", value=str(style.get("primary_color") or "#496D57"))
        style["accent_color"] = st.text_input("强调色", value=str(style.get("accent_color") or "#B9863D"))
        style["writing_tone"] = st.text_area("默认写作风格", value=str(style.get("writing_tone") or "严谨、清晰、专著体"), height=120)
        if st.button("保存风格设置", type="primary", use_container_width=True, key="save_global_style"):
            settings["style"] = style
            path = service.save(settings)
            st.success(f"全局风格已保存：{path}")

    with tab_model:
        profiles = _available_model_profiles(require_ready=False)
        profile_ids = [p.get("id", "") for p in profiles]
        current_profile_id = str(model.get("default_profile_id") or "")
        selected_profile_id = st.selectbox(
            "默认模型档案",
            [""] + profile_ids,
            index=([""] + profile_ids).index(current_profile_id) if current_profile_id in ([""] + profile_ids) else 0,
            format_func=lambda pid: "不指定" if not pid else _profile_label(_find_model_profile(pid) or {"id": pid}),
        )
        model["default_profile_id"] = selected_profile_id
        model["temperature"] = st.slider("默认 temperature", min_value=0.0, max_value=1.5, value=float(model.get("temperature", 0.35)), step=0.05)
        model["max_tokens"] = st.number_input("默认 max_tokens", min_value=512, max_value=64000, value=int(model.get("max_tokens", 8000)), step=512)
        if st.button("保存模型设置", type="primary", use_container_width=True, key="save_global_model"):
            settings["model"] = model
            path = service.save(settings)
            st.success(f"全局模型设置已保存：{path}")

    with tab_prompts:
        _render_global_prompts_editor(expanded_first=True)


def _render_global_prompts_editor(*, expanded_first: bool = False) -> None:
    """展示并编辑所有全局提示词。"""
    prompt_service = PromptService()
    prompts = prompt_service.list_all_global_prompts()
    st.markdown("### 全局提示词（中文说明 + 范文）")
    st.caption("正文生成读取“章节正文写作”；大纲生成读取“大纲生成与优化”；写章节页的前言、结语/总结、参考文献生成分别读取对应提示词。英文模板名已隐藏到高级信息，页面主视图只展示中文名称、用途、范文和可编辑提示词。")
    if not prompts:
        st.warning("没有找到全局提示词模板。")
        return

    active_keys = {"chapter_writer", "outliner", "manuscript_preface", "manuscript_conclusion", "manuscript_references"}
    active_prompts = [prompt for prompt in prompts if prompt.get("key") in active_keys]
    backup_prompts = [prompt for prompt in prompts if prompt.get("key") not in active_keys]
    ordered_prompts = active_prompts + backup_prompts

    for index, prompt in enumerate(ordered_prompts):
        key = prompt.get("key", "")
        is_active = bool(prompt.get("is_active") or key == "chapter_writer")
        is_outline = key == "outliner"
        is_manuscript_part = key in {"manuscript_preface", "manuscript_conclusion", "manuscript_references"}
        title = f"{prompt.get('name') or '未命名提示词'}"
        if key == "chapter_writer":
            title += " · 正文生成正在使用"
        elif is_outline:
            title += " · 大纲生成正在使用"
        elif is_manuscript_part:
            title += " · 前后文/文献生成正在使用"
        elif prompt.get("is_customized"):
            title += " · 已自定义备用"
        else:
            title += " · 高级备用"
        with st.expander(title, expanded=(is_active and expanded_first) or (expanded_first and index == 0)):
            if key == "chapter_writer":
                st.success("这一条是当前章节正文生成实际读取的全局提示词。")
            elif is_outline:
                st.success("这一条是当前 AI 大纲生成与二次改进实际读取的全局提示词。")
            elif is_manuscript_part:
                st.success("这一条是写章节页生成前言、结语/总结或参考文献时实际读取的全局提示词。")
            else:
                st.info("这是历史/备用模板，当前不会参与章节正文或大纲生成；后续接入对应功能时才会生效。")
            st.caption(prompt.get("description", ""))
            st.markdown("**范文/示例：**")
            st.info(prompt.get("example", "暂无范文示例。"))
            meta_cols = st.columns(2)
            meta_cols[0].write(f"中文名称：{prompt.get('name') or '未命名提示词'}")
            meta_cols[1].write(f"分类：{prompt.get('category') or '-'}")
            with st.expander("高级信息（模板键名、原始英文名、文件来源）", expanded=False):
                st.write(f"模板键名：{key}")
                st.write(f"原始名称：{prompt.get('original_name') or '-'}")
                st.write(f"来源：{prompt.get('path') or '-'}")
            edited = st.text_area(
                "当前生效提示词内容" if (is_active or is_outline or is_manuscript_part) else "备用提示词内容",
                value=prompt.get("current_template", ""),
                height=500 if (is_active or is_outline or is_manuscript_part) else 260,
                key=f"global_prompt_editor_{key}",
                help="变量请保留大括号格式，例如 {book_title}、{section_title}、{rag_context}。",
            )
            col_save, col_reset = st.columns(2)
            if col_save.button("保存这个全局提示词", type="primary", use_container_width=True, key=f"save_global_prompt_{key}"):
                try:
                    path = prompt_service.save_global_prompt(key, edited)
                    st.success(f"全局提示词已保存：{path}")
                    st.rerun()
                except Exception as exc:
                    st.error(f"保存失败：{exc}")
            if col_reset.button("恢复内置默认", use_container_width=True, key=f"reset_global_prompt_{key}"):
                try:
                    path = prompt_service.reset_global_prompt(key)
                    st.success(f"已恢复内置默认：{path}")
                    st.rerun()
                except Exception as exc:
                    st.error(f"恢复失败：{exc}")
            if prompt.get("default_template") and prompt.get("is_customized"):
                with st.expander("查看内置原始提示词", expanded=False):
                    st.code(prompt.get("default_template", ""), language="markdown")

    st.divider()
    st.markdown("### AI 分析提示词与优化方向")
    st.markdown(prompt_service.prompt_analysis_guide())

    with st.expander("内置写作剧本（只作参考，不会自动覆盖全局提示词）", expanded=False):
        for playbook in prompt_service.builtin_playbooks():
            with st.container(border=True):
                st.markdown(f"#### {playbook.get('name', '')}")
                st.caption(playbook.get("description", ""))
                st.write("工作流：", " → ".join(playbook.get("workflow", [])))
                st.write("提示词重点：", "；".join(playbook.get("prompt_focus", [])))


def render_exports_page() -> None:
    """出版与交付中心页面。"""
    _render_business_hero("出版与交付中心", "导出 DOCX、PDF、PPTX、LaTeX，并用更适合中文专著的版式生成交付文件。")
    project = _current_project()
    if project is None:
        st.warning(t('load_project_first'))
        return
    st.info("PPTX 会自动把长篇正文整理为封面、目录、章节摘要、章节要点和结束页，避免把整篇文章直接塞进幻灯片。")

    export_chapters = _collect_chapters(project)
    quality_service = QualityService()
    export_report = quality_service.export_readiness_report(export_chapters)
    manuscript_report = quality_service.manuscript_quality_report(export_chapters, citations=getattr(project, "citations", []))

    st.markdown("### 导出前交付门禁")
    gate_cols = st.columns(4)
    gate_cols[0].metric("导出就绪", f"{export_report.get('readiness_score', 0)}/100", export_report.get("status", ""))
    gate_cols[1].metric("正文质量", f"{manuscript_report.get('quality_score', 0)}/100", manuscript_report.get("status", ""))
    gate_cols[2].metric("章节数", export_report.get("chapter_count", 0))
    gate_cols[3].metric("总字数", export_report.get("total_words", 0))

    blocking_issues = int(export_report.get("severe_warnings", 0) or 0) + int(export_report.get("high_warnings", 0) or 0) + int(manuscript_report.get("high_issues", 0) or 0)
    if blocking_issues:
        st.warning("导出前发现高风险问题：建议先到“审校”页处理短章、重复标题、过程残留、伪引用或无来源事实句，再生成最终交付文件。")
    elif export_report.get("status") == "通过" and manuscript_report.get("status") == "通过":
        st.success("导出前体检通过：当前正文未发现明显交付阻断风险。")
    else:
        st.info("当前可导出预览稿，但建议复核下方质量提示后再作为最终稿交付。")

    if export_report.get("warnings"):
        with st.expander("导出就绪风险", expanded=True):
            st.dataframe(export_report["warnings"], use_container_width=True, hide_index=True)
    if manuscript_report.get("issues"):
        with st.expander("正文质量风险", expanded=True):
            st.dataframe(manuscript_report["issues"], use_container_width=True, hide_index=True)

    export_dir = Path(st.session_state.get("project_dir") or ".") / "exports"
    st.markdown("### 生成交付文件")
    col1, col2, col3, col4 = st.columns(4)
    if col1.button("导出 DOCX", use_container_width=True, key="export_docx_center"):
        _export_docx(project, export_dir)
    if col2.button("导出 PDF", use_container_width=True, key="export_pdf_center"):
        _export_pdf(project, export_dir)
    if col3.button("导出 PPTX", use_container_width=True, key="export_pptx_center"):
        _export_pptx(project, export_dir)
    if col4.button("导出 LaTeX", use_container_width=True, key="export_latex_center"):
        _export_latex(project, export_dir)


def render_tools_page() -> None:
    """写作工具箱页面，兼容旧聊天助手。"""
    _render_business_hero("写作工具箱", "将资料问答、摘要、改写、扩写、术语统一和项目上下文助手整合为工具矩阵。")
    render_chat_page()


def render_audit_page() -> None:
    """审计中心页面。"""
    _render_business_hero("审计中心", "记录模型调用、资料入库、写作任务、审校结果和导出交付，为企业级治理预留接口。")
    mgr = _get_task_manager()
    tasks = list(mgr.get_all_tasks().values())
    st.metric("当前会话任务记录", len(tasks))
    if tasks:
        st.dataframe(tasks, use_container_width=True)
    else:
        st.caption("暂无任务审计记录。后续将接入持久化 TaskService 与 AuditService。")


PAGE_RENDERERS = {
    "GlobalSettings": render_global_settings_page,
    "Workspace": render_workspace_page,
    "Projects": render_projects_page,
    "Dashboard": render_workspace_page,
    "Sources": render_sources_page,
    "Outline": render_outline_page,
    "Pipeline": render_pipeline_page,
    "Editor": render_editor_page,
    "Citations": render_citations_page,
    "Quality": render_quality_page,
    "Prompts": render_prompts_page,
    "Exports": render_exports_page,
    "Tools": render_tools_page,
    "Chat": render_tools_page,
    "Settings": render_settings_page,
    "AIConfig": render_ai_config_page,
    "Audit": render_audit_page,
}


def main() -> None:
    """Streamlit 应用主入口"""
    # 1. 初始化 session state
    init_session_state()

    # 2. 渲染侧边栏与移动端兜底导航
    render_sidebar()
    render_mobile_navigation()

    # 3. 显示后台任务进度（全局，任何页面都可见）
    mgr = _get_task_manager()
    running = mgr.get_running_tasks()
    if running:
        with st.container():
            st.markdown("---")
            st.markdown("### 后台任务进行中")
            for task in running:
                desc = task.get("description", task.get("type", ""))
                msg = task.get("message", "")
                st.progress(task.get("progress", 0.0), text=f"{desc} — {msg}" if msg else desc)
            # 不再使用 HTML meta refresh。
            # meta refresh 会触发浏览器整页重载，刷新时容易先闪出 Streamlit/旧首页骨架，
            # 因此后台任务进度仅随用户交互或 Streamlit rerun 更新，避免视觉跳闪。

    # 显示已完成/失败的任务结果
    _render_task_results()

    # 4. 路由到当前页面
    current_page = st.session_state.get("current_page", "Workspace")
    current_page = LEGACY_PAGE_ALIASES.get(current_page, current_page)
    st.session_state["current_page"] = current_page
    renderer = PAGE_RENDERERS.get(current_page)

    if renderer is not None:
        try:
            renderer()
            render_floating_ai_chat(current_page)
        except Exception as e:
            st.error(t('page_error', e=e))
            logger.exception("Page rendering error for %s", current_page)
            st.exception(e)
    else:
        st.error(t('unknown_page', page=current_page))
        st.info(t('select_valid_page'))


# ── Streamlit 入口 ────────────────────────────────────────────────────
if __name__ == "__main__":
    main()
