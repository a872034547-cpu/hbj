# 2026-05-09 创建 workflow/__init__.py

## 任务描述
创建 LangGraph 工作流模块的初始化文件。

## 变更文件
- `libriscribe/src/libriscribe/workflow/__init__.py` (新建)

## 内容说明
- 定义模块文档字符串，说明该模块提供有状态、多代理循环编排能力
- 从 `state` 模块导入 `BookWritingState`
- 从 `graph` 模块导入 `create_book_writing_graph`
- 导出符号列表：`BookWritingState`, `create_book_writing_graph`
