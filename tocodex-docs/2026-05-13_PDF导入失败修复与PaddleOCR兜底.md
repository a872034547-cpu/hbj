# PDF 导入失败修复与 PaddleOCR 兜底

## 摘要

修复资料库 PDF 导入在本地解析失败、扫描版 PDF 抽取不到文字时直接入库失败的问题，并新增 PaddleOCR AIStudio 在线 OCR 兜底方式，用于最小化识别导入资料文字。

## 变更文件

- `libriscribe/src/libriscribe/rag/document_loader.py`
- `libriscribe/.env.example`

## 主要变更

### 1. PDF 多级解析兜底

`DocumentLoader._load_pdf()` 从原来的“优先 unstructured，缺失时才用 PyPDF2”改为多级兜底：

1. `unstructured.partition.pdf` 本地解析；
2. `PyPDF2` 本地文本抽取；
3. 前两者失败或抽取为空时，尝试 PaddleOCR 在线识别。

这样可以修复 `unstructured` 已安装但解析异常时不会继续尝试 PyPDF2 的问题。

### 2. 新增 PaddleOCR 最小化文字识别

新增：

- `_load_pdf_with_paddleocr()`：提交 PDF 到 PaddleOCR AIStudio OCR jobs API、轮询任务、读取 JSONL 结果。
- `_extract_paddleocr_jsonl_text()`：只解析 JSONL 里的文字，不下载识别图片。
- `_collect_text_from_ocr_object()`：兼容 `recText`、`text`、`content`、`recTexts`、`ocrResults`、`prunedResult` 等常见返回结构。
- `_dedupe_text_lines()`：保持顺序去重，避免递归兼容解析造成重复片段。

### 3. 密钥配置

没有把真实 Token 写入源码或 `.env.example`。实际使用时在本地 `.env` 配置：

```env
PADDLEOCR_AISTUDIO_TOKEN=你的真实token
PADDLEOCR_AISTUDIO_MODEL=PP-OCRv5
PADDLEOCR_AISTUDIO_JOB_URL=https://paddleocr.aistudio-app.com/api/v2/ocr/jobs
PADDLEOCR_AISTUDIO_TIMEOUT_SECONDS=180
```

## 验证

已运行：

```bash
python -m py_compile src/libriscribe/rag/document_loader.py
```

并用最小 JSONL 样例验证 PaddleOCR 结果抽取可识别 `recText`、`text`、`recTexts`，且会去重。

同时验证 `.env.example` 未写入用户提供的真实 token。
