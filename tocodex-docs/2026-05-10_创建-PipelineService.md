# 创建 PipelineService

## 摘要

新增商业化专著生产流水线服务，用于根据项目数据生成固定阶段的进度状态视图。该服务无副作用，可供后续 Web 页面、任务中心或 API 层复用。

## 变更文件

- [`pipeline_service.py`](../libriscribe/src/libriscribe/services/pipeline_service.py)：新增 `PipelineService`、阶段定义和 `get_pipeline(project)`，内置 `project`、`sources`、`outline`、`draft`、`citation_check`、`quality_review`、`export`、`publish` 八个阶段，并根据项目字段、章节、资料、引用、评审报告和任务日志推断阶段状态。

## 验证

- 已执行 `python -m py_compile libriscribe\src\libriscribe\services\pipeline_service.py`，语法检查通过。
