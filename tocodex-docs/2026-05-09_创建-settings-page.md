# 创建 Web UI 项目设置页面

## 概述
创建了 Streamlit Web UI 的项目设置页面 `settings.py`，包含五个标签页的完整设置界面。

## 创建的文件
- `libriscribe/src/libriscribe/web/pages/settings.py`

## 功能详情

### 五个标签页
1. **📖 项目设置** — 项目名称、书名、描述、分类、体裁、语言、书籍长度、风格指南编辑
2. **🤖 LLM 设置** — 6 个 LLM 提供商选择、API Key 密码输入、模型选择、Temperature 滑块、Max Tokens、成本优化开关（初稿/润色模型）
3. **📐 RAG 设置** — 嵌入提供商/模型、ChromaDB 目录、Top-K 滑块、分块大小/重叠、文档上传（PDF/DOCX/TXT）、已索引文档列表（含删除）
4. **📤 导出设置** — 输出格式选择、Pandoc 路径、引用格式（GB/T 7714 等）、导出预览
5. **📝 术语表** — 术语搜索、添加术语表单、CSV 导入/导出、分页展示、单条删除

### 设计要点
- 使用 `st.form` 组织分组输入，提交时保存
- 所有变更同步到 `session_state` 和 `ProjectKnowledgeBase`
- 术语管理通过 `TerminologyManager` 实现，支持持久化
- 文档上传保存到项目目录下的 `rag_documents/` 子目录
- 导出预览生成 Markdown 格式的书籍概览
