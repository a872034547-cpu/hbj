# 2026-05-09 创建 outline.py 大纲管理页面

## 概述
创建了 Streamlit Web UI 的大纲管理页面 `libriscribe/src/libriscribe/web/pages/outline.py`。

## 变更文件
- `libriscribe/src/libriscribe/web/pages/outline.py` — 新建

## 实现内容

### 主入口函数
- `render_outline()` — 页面主入口，整合概念展示、章节树、大纲操作和参考资料四个区域，采用 3:1 主内容/侧边栏布局

### 核心功能函数
- `render_concept_section(project)` — 书籍概念展示与编辑（标题、类型、简介、基调、目标读者、logline 等），使用 `st.expander` 折叠编辑区 + 只读摘要表格
- `render_chapter_tree(project)` — 章节大纲树状视图，包含快速导航下拉框、统计概览（章节数/场景数/角色数）、上移/下移排序按钮、添加新章节表单
- `render_chapter_detail(chapter, chapter_number)` — 单章节详情，支持标题/摘要编辑、目标字数设置、场景列表展示、添加/删除场景、删除章节（自动重新编号）
- `render_scene_detail(scene, chapter_number, scene_number)` — 单场景详情，支持摘要/地点/目标/情感节拍编辑、角色多选（带角色速览）、保存/删除操作
- `render_outline_actions(project)` — 大纲操作区，包含生成/重新生成/清空大纲按钮，调用 `OutlinerAgent` 执行生成
- `render_references(project)` — 侧边栏参考资料，展示角色列表和世界观设定

### 设计要点
- 所有数据修改通过 `_save_project()` 同步到 `session_state` 并持久化到 JSON 文件
- 章节删除后自动重新编号，场景删除后自动重新编号
- 角色多选基于项目已有的 `characters` 字典
- 大纲生成通过延迟导入 `OutlinerAgent` 避免循环依赖
