# 创建 chapter_tree.py 章节树状导航组件

**日期**: 2026-05-09

## 概述

创建了 `libriscribe/src/libriscribe/web/components/chapter_tree.py`，一个可复用的 Streamlit 章节/场景层级导航组件。

## 变更文件

- `libriscribe/src/libriscribe/web/components/__init__.py` — 新建，组件包初始化
- `libriscribe/src/libriscribe/web/components/chapter_tree.py` — 新建，核心组件

## 功能清单

| 功能 | 说明 |
|------|------|
| `render_chapter_tree()` | 主入口，渲染完整章节树，含筛选/搜索/统计 |
| `render_chapter_node()` | 渲染单个章节节点（状态图标、字数、评审分数、可展开场景） |
| `render_scene_node()` | 渲染单个场景节点（标题、描述、角色列表） |
| `get_chapter_status()` | 判断章节状态：written/reviewed/pending/error |
| 状态筛选 | 支持全部/已撰写/待撰写/已评审/需修改 |
| 搜索 | 按章节标题、摘要、场景摘要关键词搜索 |
| 选中高亮 | 通过 session_state 或自定义回调管理选中状态 |
| 统计摘要 | 顶部显示各状态章节数量 |
