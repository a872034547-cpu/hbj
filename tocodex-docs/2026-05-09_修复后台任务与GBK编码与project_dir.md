# Bug 修复：后台任务、GBK 编码、project_dir 空值

## 日期
2026-05-09

## 摘要
修复了多个关键 bug，包括后台 AI 任务调用签名错误、Windows GBK 编码崩溃、project_dir 空值导致章节写入失败等问题。

## 修改文件列表

### 核心修复
1. **`src/libriscribe/web/app.py`**
   - `_bg_write_chapter()`: 修复 `ChapterWriterAgent.execute()` 返回 `None`（写入文件）而非字符串的逻辑；添加 `project_dir` 空值保护；移除 `task_id` 参数简化进度管理
   - `_bg_review_chapter()`: 修复调用签名错误——`ContentReviewerAgent.execute()` 接受 `chapter_path: str` 而非 `(project, chapter_num)`；添加章节文件存在性检查；添加 `project_dir` 空值保护
   - `_generate_chapter_with_ai()`: 修复 `task_id_placeholder` 未定义变量错误，简化为直接传递参数
   - `_review_chapter_with_ai()`: 调用签名已正确

### GBK 编码修复（移除 emoji + print→logger）
2. **`src/libriscribe/agents/chapter_writer.py`** — 移除 `📝` `🎬` `✅` emoji
3. **`src/libriscribe/agents/content_reviewer.py`** — 移除 `🔍` emoji
4. **`src/libriscribe/agents/editor.py`** — 移除 `✏️` `✅` emoji；`print()` → `self.logger.error()`；添加 `project_dir` 空值检查
5. **`src/libriscribe/agents/style_editor.py`** — 移除 `🎨` `✅` emoji；`print()` → `self.logger.error()`；添加 `project_dir` 空值检查
6. **`src/libriscribe/agents/concept_generator.py`** — 移除 `🔍` emoji
7. **`src/libriscribe/agents/character_generator.py`** — 移除 `✅` emoji
8. **`src/libriscribe/agents/outliner.py`** — 移除 `📝` `🎬` `✅` emoji
9. **`src/libriscribe/agents/fact_checker.py`** — 移除 `🔍` emoji
10. **`src/libriscribe/agents/editor_enhanced.py`** — 移除 `✏️` `✅` emoji
11. **`src/libriscribe/agents/worldbuilding.py`** — 移除 `🏔️` `✅` emoji
12. **`src/libriscribe/main.py`** — 移除 `📝` `✅` emoji

### project_dir 空值修复
13. **`src/libriscribe/knowledge_base.py`** — `load_from_file()` 中从文件路径推导 `project_dir`
14. **`src/libriscribe/agents/chapter_writer.py`** — 添加 `project_dir` 空值检查和错误提示
15. **`src/libriscribe/agents/editor.py`** — 添加 `project_dir` 空值检查
16. **`src/libriscribe/agents/style_editor.py`** — 添加 `project_dir` 空值检查
