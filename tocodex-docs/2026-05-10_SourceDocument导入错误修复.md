# SourceDocument 导入错误修复

## 问题

用户报告运行时报错：

```text
ImportError: cannot import name 'SourceDocument' from 'libriscribe.knowledge_base'
```

只做 `py_compile` 未覆盖实际包路径导入场景，导致问题上线前未被发现。

## 根因

`SourceDocument`、`EvidenceChunk` 已存在于 [`libriscribe/src/libriscribe/knowledge_base.py`](../libriscribe/src/libriscribe/knowledge_base.py)，但从工作区根目录 `d:/weidong` 运行时，Python 会优先解析到仓库目录包 [`libriscribe/__init__.py`](../libriscribe/__init__.py)，该根包原先为空且没有把 `src/libriscribe` 加入包搜索路径，导致 `libriscribe.knowledge_base` 在根目录启动场景下无法稳定解析。

同时，用户报错时仍有旧 Streamlit 进程在运行：

```text
streamlit.exe run src/libriscribe/web/app.py --server.port 8501 --server.headless true
```

旧进程会继续使用旧模块状态，因此修复导入路径后需要终止旧进程并重启。

## 修改

- 修改 [`libriscribe/__init__.py`](../libriscribe/__init__.py)：加入兼容 shim，使用 `pkgutil.extend_path` 并把 `libriscribe/src/libriscribe` 追加到包 `__path__`。
- 这样无论从项目目录 [`libriscribe`](../libriscribe) 启动，还是从工作区根目录启动，都能导入真实源码包里的 `knowledge_base`、`web.app` 等子模块。
- 已终止旧 Streamlit 进程，并用项目目录作为工作目录重启 8501 服务。

## 已验证

从项目目录 [`libriscribe`](../libriscribe) 验证：

```text
python -m py_compile __init__.py src\libriscribe\knowledge_base.py src\libriscribe\rag\document_loader.py src\libriscribe\rag\vector_store.py src\libriscribe\web\app.py src\libriscribe\web\i18n.py
python -c "from libriscribe.knowledge_base import SourceDocument, EvidenceChunk, ProjectKnowledgeBase; ..."
python -c "import libriscribe.web.app as app; ..."
```

结果：

```text
project import ok: SourceDocument EvidenceChunk ProjectKnowledgeBase
project app import ok: True
```

从工作区根目录 [`d:/weidong`](../) 验证：

```text
python -m py_compile libriscribe\__init__.py libriscribe\src\libriscribe\knowledge_base.py libriscribe\src\libriscribe\rag\document_loader.py libriscribe\src\libriscribe\rag\vector_store.py libriscribe\src\libriscribe\web\app.py libriscribe\src\libriscribe\web\i18n.py
python -c "from libriscribe.knowledge_base import SourceDocument, EvidenceChunk, ProjectKnowledgeBase; ..."
python -c "import libriscribe.web.app as app; ..."
```

结果：

```text
root import ok: SourceDocument EvidenceChunk ProjectKnowledgeBase
root app import ok: True
```

旧进程检查与处理：

```text
wmic process where "name='python.exe'" get ProcessId,CommandLine /FORMAT:LIST
```

发现并终止：

```text
PID 145672: streamlit.exe run src/libriscribe/web/app.py --server.port 8501 --server.headless true
PID 306240: python -m streamlit run libriscribe\src\libriscribe\web\app.py --server.headless true --server.port 8509
```

随后重新启动正式 8501 服务：

```text
python -m streamlit run src/libriscribe/web/app.py --server.port 8501 --server.headless true
```

结果：

```text
You can now view your Streamlit app in your browser.
Local URL: http://localhost:8501
```

## 后续规范

以后涉及导入、路由、数据模型、核心逻辑变更时，不能只跑语法检查；至少补充：

1. 目标模块 import 检测。
2. Web app import 检测。
3. 从工作区根目录和项目目录两个启动路径分别检测。
4. 必要时启动 Streamlit 做运行级 smoke test。
5. 若用户页面仍报旧错误，必须检查并重启旧 Streamlit/Python 进程，避免旧模块缓存误判。
