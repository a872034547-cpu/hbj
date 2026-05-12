# 一小时写书 Agent 工作流与 OpenAlex 预留

## 摘要

本次升级将原有商业化生产流水线重构为基于 GPT-5.4/5.5 Agent 一体化理念的“一小时写书”6 步闭环：需求理解与选题策展、文献/知识库注入、结构化大纲生成、AI 正文逐章撰写、图文同步生成（可选）、全书交付与版本管理。

同时新增 OpenAlex 文献 API 接入预留服务，当前不强制联网请求，先提供检索 URL、规范化 OpenAlex work 数据、导入候选文献到资料库的骨架能力。

## 变更文件

- `libriscribe/src/libriscribe/services/pipeline_service.py`
  - 扩展 `PipelineStage`，新增用户动作、Agent 动作、产出物、主路由、主按钮和可选阶段字段。
  - 将原 8 阶段流水线改为 6 步一小时写书闭环。
  - 新增图文优化可选状态和交付阶段聚合状态。

- `libriscribe/src/libriscribe/services/literature_search_service.py`
  - 新增 `LiteratureSearchService`。
  - 预留 OpenAlex works 检索 URL 构造。
  - 支持 OpenAlex work 规范化与候选文献导入为 `SourceDocument`。

- `libriscribe/src/libriscribe/services/__init__.py`
  - 导出 `LiteratureSearchService`。

- `libriscribe/src/libriscribe/web/app.py`
  - 导入 `LiteratureSearchService`。
  - 将项目驾驶舱升级为“一小时写书”项目入口。
  - 将流水线页升级为“Agent 一小时写书工作台”。
  - 6 步卡片展示用户要做什么、AI 做什么、产出什么。
  - 资料页新增 OpenAlex 文献 API 接入预留区。

- `libriscribe/tests/test_outline_pipeline_services.py`
  - 更新流水线测试为 6 步闭环。
  - 增加 OpenAlex 预留服务规范化与导入测试。

- `libriscribe/tests/test_export_and_quality_gate_services.py`
  - 将旧 `citation_check` / `quality_review` / `export` 阶段断言调整为新的 `delivery` 聚合阶段断言。

## 验证结果

已执行并通过：

```bash
python -m compileall src
python -m pytest tests\test_outline_pipeline_services.py tests\test_citation_source_services.py tests\test_commercial_routes.py tests\test_export_and_quality_gate_services.py -q
python scripts\quality_gate.py
```

结果：

- 目标测试：`17 passed`
- 全量质量门禁：`Overall status: PASS`
