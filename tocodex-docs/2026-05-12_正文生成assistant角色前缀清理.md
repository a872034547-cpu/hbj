# 正文生成 assistant 角色前缀清理

## 摘要

修复部分 OpenAI-compatible 中转接口在正文生成结果中泄露 `assistantassistant`、`assistant:`、`system:` 等 chat role 前缀的问题。该问题会污染章节正文，尤其可能出现在初稿、续写、压缩、质量门禁重写和最终格式化环节。

## 变更内容

- 在 `ChapterWriterAgent._sanitize_model_output()` 中增加统一清理规则：
  - 删除行首 `assistantassistant`、`assistant:`、`assistant -` 等角色前缀。
  - 删除行首 `user:`、`system:` 等调试角色前缀。
  - 保留前缀后面的真实正文内容。
- 增加回归测试，确保正文中不再残留 `assistant` / `system:`，同时不误删真实中文正文。

## 变更文件

- `libriscribe/src/libriscribe/agents/chapter_writer.py`
- `libriscribe/tests/test_commercial_routes.py`

## 验证

已运行：

```bash
python -m pytest libriscribe/tests/test_commercial_routes.py -k "sanitize or quality_gate or semantic_word_targets"
```

结果：`8 passed, 88 deselected`。
