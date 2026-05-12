# 自定义模型 assistant 空响应检测修复

## 摘要

修复自定义 OpenAI-compatible 模型接口只返回 `assistant`、`assistantassistant` 等 chat role 标记时仍被网页判定为“在线可用”的问题。现在底层 LLM 客户端会识别这类角色标记空响应，返回清晰诊断；模型在线检测也会拒绝将其标记为可用。

## 变更文件

- `libriscribe/src/libriscribe/utils/llm_client.py`
  - 新增 role-only 响应识别与 role 标记剥离逻辑。
  - 自定义 OpenAI-compatible raw HTTP / responses API 返回 `assistant` 等无正文内容时，记录明确的 `last_error`。
  - 避免章节生成把 role 标记当成有效模型正文继续重试或误判。

- `libriscribe/src/libriscribe/web/app.py`
  - 在线检测 `_profile_connection_result()` 增加 role-only 响应校验。
  - 当接口只返回 `assistant` 时，不再显示“在线可用”，改为提示检查 API Base、模型名称和 `/chat/completions` 兼容配置。

- `libriscribe/tests/test_commercial_routes.py`
  - 新增自定义模型 role-only 响应回归测试。
  - 新增网页模型在线检测拒绝 role-only 响应的回归测试。

## 验证

已运行针对性测试：

```cmd
cd libriscribe && set PYTHONPATH=src && python -m pytest tests/test_commercial_routes.py -k "role_marker_only_response or custom_llm_client_fallbacks_do_not_downshift_to_tiny_output_budgets or custom_llm_client_accepts_fast_fail_options_for_reference_generation" -q
```

结果：

```text
4 passed, 94 deselected
```

## 服务状态

已重启 Streamlit：

```text
Local URL: http://localhost:8501
```

## 说明

这次修复不会让配置错误的模型“强行可用”。如果模型测试仍返回 `assistant`，页面现在会明确提示它不是有效正文响应，通常需要检查：

1. API Base 是否正确，通常应为平台的 OpenAI-compatible `/v1` 地址。
2. 模型名称是否真实存在且支持 chat completions。
3. 中转平台是否把流式 role 字段错误地作为 `message.content` 返回。
4. 是否填成了网页地址、控制台地址或非 `/chat/completions` 兼容入口。
