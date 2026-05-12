# 向量索引复用模型档案 Embedding 配置

## 摘要

用户询问“索引不能用我配置的 AI 做吗，一定要通过 HuggingFace 下载吗”。本次调整后，资料向量索引不再强制走 HuggingFace 本地模型。

新的逻辑是：

1. 上传资料默认仍只导入资料库，避免上传阶段被 embedding 网络问题阻断。
2. 用户勾选“同时建立向量索引”时，系统优先读取当前项目绑定的模型档案。
3. 如果模型档案是 OpenAI-compatible/custom/openai/openrouter，并且该 API Base 支持 `/embeddings`，则用该 API 做 embedding。
4. 如果远程 embedding 初始化或调用失败，不再自动降级下载 HuggingFace，而是保留资料库导入结果并提示索引失败。

注意：普通聊天模型接口 `/chat/completions` 不能直接生成向量；同一个 API 服务必须同时支持 `/embeddings` 才能用于向量索引。

## 变更文件

- `libriscribe/src/libriscribe/rag/embeddings.py`
  - `EmbeddingProvider` 增加 `api_base`、`api_key`、`allow_local_fallback` 参数。
  - 支持从外部传入 OpenAI-compatible embedding 配置。
  - 当 `allow_local_fallback=False` 时，远程 embedding 失败不会自动降级到 HuggingFace 本地模型。

- `libriscribe/src/libriscribe/web/app.py`
  - 新增 `_embedding_provider_from_project_profile()`。
  - 向量索引勾选后优先使用当前项目模型档案的 API Base/API Key/model 创建 OpenAI-compatible embedding provider。
  - 自定义 API Base 自动补齐 `/v1`。
  - 索引失败时保留资料库模式，不阻断大纲和正文引用参考。

- `libriscribe/tests/test_commercial_routes.py`
  - 增加远程 OpenAI-compatible embedding provider 测试。
  - 增加项目模型档案转 embedding provider 的测试。
  - 更新上传资料索引测试，确认向量索引优先使用当前模型档案。

## 验证

已运行：

```bash
cd libriscribe && pytest tests/test_commercial_routes.py tests/test_outline_pipeline_services.py -q
```

结果：

```text
55 passed in 3.20s
```
