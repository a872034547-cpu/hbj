# 2026-05-09 创建 reference_formatter.py

## 任务总结
创建了参考文献格式化模块，支持 GB/T 7714 标准和 BibTeX 导出。

## 更改文件
- `libriscribe/src/libriscribe/export/reference_formatter.py` (新建)

## 功能说明
- `ReferenceFormatter` 类提供以下功能：
  - `format_reference()`: 按 GB/T 7714 格式化单条参考文献
  - `format_references_list()`: 生成参考文献列表
  - `extract_citations_from_text()`: 从文本中提取引用标记
  - `generate_bibtex()`: 生成 BibTeX 格式
- 支持多种文献类型：book, journal, newspaper, conference, thesis, report, standard, patent, database, webpage
- 自动处理中英文作者姓名格式