# 任务备忘录：创建 DOCX 导出模块

**日期**: 2026-05-09

## 概述
创建了 `DocxExporter` 类，用于将书籍项目导出为 DOCX 格式。

## 变更文件
- `libriscribe/src/libriscribe/export/docx_export.py` — 新建，包含 `DocxExporter` 类

## 功能说明
- `export()`: 接收章节列表，生成带封面页、目录提示和格式化章节的 DOCX 文件
- `export_from_project()`: 从项目目录读取 Markdown 章节文件并导出为 DOCX
- 支持 Markdown 基本语法解析（标题、粗体、斜体、代码块、列表）
- 依赖 `python-docx` 库
