# LibriScribe 📚✨

<div align="center">

<img src="https://guerra2fernando.github.io/libriscribe/img/logo.png" alt="LibriScribe Logo" width="30%">

Your AI-Powered Book Writing Assistant


[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Documentation](https://img.shields.io/badge/docs-visit%20now-green.svg)](https://guerra2fernando.github.io/libriscribe/)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)
[![Python Version](https://img.shields.io/badge/python-3.8%2B-blue)](https://www.python.org/downloads/)
[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-Support-yellow.svg?style=flat&logo=buy-me-a-coffee)](https://buymeacoffee.com/guerra2fernando)

</div>

## 🌟 Overview

LibriScribe harnesses the power of AI to revolutionize your book writing journey. Using a sophisticated multi-agent system, where each agent specializes in specific tasks, LibriScribe assists you from initial concept to final manuscript.

![Libriscribe Demo](https://github.com/guerra2fernando/libriscribe/blob/main/docs/static/img/libriscribe.gif?raw=true)

## ✨ Features

### Creative Assistance 🎨
- **Concept Generation:** Transform your ideas into detailed book concepts
- **Automated Outlining:** Create comprehensive chapter-by-chapter outlines
- **Character Generation:** Develop rich, multidimensional character profiles
- **Worldbuilding:** Craft detailed universes with rich history, culture, and geography

### Writing & Editing 📝
- **Chapter Writing:** Generate chapter drafts based on your outline
- **Content Review:** Catch inconsistencies and plot holes
- **Style Editing:** Polish your writing style for your target audience
- **Fact-Checking:** Verify factual claims (for non-fiction)

### Quality Assurance 🔍
- **Plagiarism Detection:** Ensure content originality
- **Research Assistant:** Access comprehensive topic research
- **Manuscript Formatting:** Export to polished Markdown or PDF

## 🚀 Quickstart

### 1. Installation

```bash
git clone https://github.com/guerra2fernando/libriscribe.git
cd libriscribe
pip install -e .
```

### 2. Configuration

*   **LLM API Key:** Get an API key from one of the following services:

    - **OpenAI:** [Get API Key](https://platform.openai.com/signup/)
    - **Anthropic:** [Get API Key](https://console.anthropic.com/)
    - **DeepSeek:** [Get API Key](https://platform.deepseek.com/)
    - **Google AI Studio (Gemini):** [Get API Key](https://aistudio.google.com/)
    - **Mistral AI:** [Get API Key](https://console.mistral.ai/)

Create a `.env` file in the root directory and fill the api key of the LLM that you want to use:
```bash
OPENAI_API_KEY=your_api_key_here
GOOGLE_AI_STUDIO_API_KEY=your_api_key_here
CLAUDE_API_KEY=your_api_key_here
DEEPSEEK_API_KEY=your_api_key_here
MISTRAL_API_KEY=your_api_key_here
```


### 3. Launch LibriScribe

```bash
libriscribe start
```

Choose between:
- 🎯 **Simple Mode:** Quick, streamlined book creation
- 🎛️ **Advanced Mode:** Fine-grained control over each step

## 💻 Advanced Usage

### Project Creation
```bash
python src/libriscribe/main.py start \
    --project-name my_book \
    --title "My Awesome Book" \
    --genre fantasy \
    --description "A tale of epic proportions." \
    --category fiction \
    --num-characters 3 \
    --worldbuilding-needed True
```

### Core Commands
```bash
# Generate book concept
python src/libriscribe/main.py concept

# Create outline
python src/libriscribe/main.py outline

# Generate characters
python src/libriscribe/main.py characters

# Build world
python src/libriscribe/main.py worldbuilding

# Write chapter
python src/libriscribe/main.py write-chapter --chapter-number 1

# Edit chapter
python src/libriscribe/main.py edit-chapter --chapter-number 1

# Format book
python src/libriscribe/main.py format
```

## 📁 Project Structure

```
your_project/
├── project_data.json    # Project metadata
├── outline.md          # Book outline
├── characters.json     # Character profiles
├── world.json         # Worldbuilding details
├── chapter_1.md       # Generated chapters
├── chapter_2.md
└── research_results.md # Research findings
```

## ⚠️ Important Notes

- **API Costs:** Monitor your LLM API usage and spending limits
- **Content Quality:** Generated content serves as a starting point, not final copy
- **Review Process:** Always review and edit the AI-generated content


## 🔗 Quick Links

- [📚 Documentation](https://guerra2fernando.github.io/libriscribe/)
- [🐛 Issue Tracker](https://github.com/guerra2fernando/libriscribe/issues)
- [💡 Feature Requests](https://github.com/guerra2fernando/libriscribe/issues/new)
- [📖 Wiki](https://github.com/guerra2fernando/libriscribe/wiki)

## 🤝 Contributing

We welcome contributions! Check out our [Contributing Guidelines](CONTRIBUTING.md) to get started.

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🗺️ LibriScribe Development Roadmap

### 🤖 LLM Integration & Support
- [X] **Multi-LLM Support Implementation**: Anthropic Claude Models - Google Gemini Models - - Deepseek Models - Mistral Models
- [ ] **Model Performance Benchmarking**
- [ ] **Automatic Model Fallback System**
- [ ] **Custom Model Fine-tuning Support**
- [ ] **Cost Optimization Engine**
- [ ] **Response Quality Monitoring**

### 🔍 Vector Store & Search Enhancement
- [ ] **Multi-Vector Database Support**: ChromaDB Integration, MongoDB Vector Search, Pinecone Integration, Weaviate Implementation
- [ ] **Advanced Search Features**: Semantic Search, Hybrid Search (Keywords + Semantic), Cross-Reference Search, Contextual Query Understanding
- [ ] **Embedding Models Integration**: Multiple Embedding Model Support, Custom Embedding Training, Embedding Optimization

### 🔐 Authentication & Authorization
- [ ] **Cerbos Implementation**: Role-Based Access Control (RBAC), Attribute-Based Access Control (ABAC), Custom Policy Definitions, Policy Testing Framework
- [ ] **User Management System**: User Registration & Authentication, Social Auth Integration, Multi-Factor Authentication, Session Management
- [ ] **Security Features**: Audit Logging, Rate Limiting, API Key Management, Security Headers Implementation

### 🌐 API Development
- [ ] **Core API Features**: RESTful Endpoints, GraphQL Interface, WebSocket Support, API Documentation (OpenAPI/Swagger)
- [ ] **API Management**: Version Control, Rate Limiting, Usage Monitoring, Error Handling
- [ ] **Integration Features**: Webhook Support, Event System, Batch Processing, Export/Import Functionality

### 🎨 Frontend Application
- [ ] **Dashboard Development**: Modern React Interface, Real-time Updates, Progressive Web App Support, Responsive Design
- [ ] **Editor Features**: Rich Text Editor, Markdown Support, Real-time Collaboration, Version History
- [ ] **Visualization Tools**: Character Relationship Graphs, Plot Timeline Visualization, World Map Generation, Story Arc Visualization



---

## 🚀 New Features (Secondary Development)

The following features have been added through secondary development to significantly enhance LibriScribe's capabilities.

### RAG Integration (ChromaDB + Document Parsing)
- **Vector Retrieval**: ChromaDB-based local vector database for semantic search across uploaded reference documents
- **Document Parsing**: Support for PDF, Word, and Excel file ingestion via `Unstructured`
- **Hybrid Retrieval**: Combines vector similarity search with keyword matching for higher accuracy
- **Embedding Models**: Flexible embedding provider support (OpenAI Embedding, local sentence-transformers)

### LangGraph Workflow Orchestration
- **Stateful Multi-Agent Pipeline**: LangGraph-based state machine replacing the linear agent chain
- **Iterative Review Loop**: Automatic quality scoring via `CriticAgent` with configurable score thresholds — chapters are re-written until quality standards are met
- **Conditional Routing**: Dynamic edge logic that routes chapters through review → edit → re-review cycles
- **Checkpoint & Rollout**: State snapshots at each workflow node for debugging and rollback

### Web UI (Streamlit)
- **Interactive Interface**: Full-featured Streamlit-based web application for visual project management
- **Real-time Progress**: Live progress tracking for multi-chapter generation workflows
- **Human-in-the-Loop**: Edit, approve, or request regeneration of any chapter directly from the browser

### Citation Tracing
- **Automatic Citation Extraction**: `CitationAgent` identifies claims requiring references and extracts source information
- **GB/T 7714 Formatting**: References are formatted according to the Chinese national standard GB/T 7714
- **Structured Output**: Citations are stored as structured data with sentence, source, page, and original quote

### Export Capabilities
- **DOCX Export**: Microsoft Word document generation via `python-docx`
- **LaTeX Export**: LaTeX source generation for academic publishing workflows
- **PDF Export**: Enhanced PDF output (existing `fpdf` support retained)
- **Reference Formatting**: Automatic bibliography generation in multiple formats

### Global Memory System
- **Terminology Management**: Persistent terminology dictionary ensuring consistent use of key terms across chapters
- **Hierarchical Summarization**: Automatic chapter summaries that are injected into subsequent chapter writing prompts, maintaining narrative coherence
- **Version History**: File-based checkpoint system with snapshot/rollback support for all major operations

### Cost Optimization
- **Draft vs. Polish Models**: Use cheaper/faster models (e.g., DeepSeek) for initial drafts, and premium models (e.g., Claude, GPT-4) for final polishing
- **Configurable Per-Agent**: Each agent can be assigned a different LLM provider and model

### Human-in-the-Loop Collaboration
- **Web UI Editing**: Direct chapter editing in the browser with diff viewing
- **Feedback Loop**: Provide natural language feedback to guide regeneration
- **Approval Gates**: Configurable approval steps between workflow stages

---

## 📦 Installation (Secondary Development)

### Development Install

```bash
git clone https://github.com/guerra2fernando/libriscribe.git
cd libriscribe
pip install -e .
```

### New Environment Variables

Add the following to your `.env` file for the new features:

```bash
# === RAG Settings ===
EMBEDDING_PROVIDER=openai          # "openai" or "local"
EMBEDDING_MODEL=text-embedding-3-small
CHROMA_PERSIST_DIR=./chroma_db

# === Web UI ===
STREAMLIT_SERVER_PORT=8501
STREAMLIT_SERVER_ADDRESS=0.0.0.0

# === Workflow Settings ===
MAX_REVIEW_ITERATIONS=3
CRITIC_SCORE_THRESHOLD=8.0

# === Export Settings ===
PANDOC_PATH=/usr/bin/pandoc
REFERENCE_FORMAT=gbt7714
```

---

## 🖥️ Web UI

### Launch

```bash
streamlit run src/libriscribe/web/app.py
```

The Web UI will be available at `http://localhost:8501` by default.

### Pages

| Page | Description |
|------|-------------|
| **Dashboard** | Project overview with progress tracking, chapter status, and quick actions |
| **Outline** | Visual outline editor — add, remove, reorder chapters and scenes |
| **Editor** | Rich chapter editor with side-by-side diff viewing and regeneration controls |
| **Chat** | Conversational interface for issuing commands and providing feedback in natural language |
| **Settings** | Configure LLM providers, RAG parameters, export formats, and workflow thresholds |

### Components

- **Chapter Tree**: Hierarchical navigation of the book structure
- **Diff Viewer**: Compare original and edited chapter versions side by side
- **Progress Bar**: Real-time visualization of multi-chapter generation progress

---

## 🔧 Configuration

### RAG Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `embedding_provider` | `openai` | Embedding model provider (`openai` or `local`) |
| `embedding_model` | `text-embedding-3-small` | Model name for embeddings |
| `chroma_persist_dir` | `./chroma_db` | ChromaDB local storage path |
| `chunk_size` | `1000` | Text chunk size for document splitting |
| `chunk_overlap` | `200` | Overlap between consecutive chunks |
| `retrieval_top_k` | `5` | Number of top results returned by retriever |

### Workflow Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `max_review_iterations` | `3` | Maximum number of review-rewrite cycles per chapter |
| `critic_score_threshold` | `8.0` | Minimum quality score (1-10) to pass review |
| `enable_citation_agent` | `true` | Whether to run citation extraction after writing |
| `draft_model` | `deepseek-chat` | Cheaper model for initial drafts |
| `polish_model` | `claude-3-5-sonnet` | Premium model for final editing |

### Export Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `pandoc_path` | `/usr/bin/pandoc` | Path to Pandoc binary (for LaTeX/DOCX conversion) |
| `reference_format` | `gbt7714` | Citation style (`gbt7714`, `apa`, `mla`) |
| `export_dir` | `./exports` | Output directory for exported files |

---

## 📁 Project Structure (Updated)

```
libriscribe/
├── src/libriscribe/
│   ├── __init__.py
│   ├── main.py                    # CLI entry point
│   ├── settings.py                # Extended configuration
│   ├── knowledge_base.py          # State model (extended with citations, terminology)
│   │
│   ├── agents/                    # Agent modules
│   │   ├── agent_base.py          # Base agent class
│   │   ├── chapter_writer.py      # Chapter generation (RAG-enhanced)
│   │   ├── citation_agent.py      # 🆕 Automatic citation extraction
│   │   ├── critic_agent.py        # 🆕 Quality scoring & iterative review
│   │   ├── concept_generator.py
│   │   ├── content_reviewer.py
│   │   ├── editor.py
│   │   ├── style_editor.py
│   │   ├── outliner.py
│   │   ├── character_generator.py
│   │   ├── worldbuilding.py
│   │   ├── researcher.py          # Enhanced with RAG retrieval
│   │   ├── formatting.py
│   │   ├── plagiarism_checker.py
│   │   ├── fact_checker.py
│   │   └── project_manager.py     # Refactored for LangGraph integration
│   │
│   ├── rag/                       # 🆕 RAG module
│   │   ├── document_loader.py     # PDF/Word/Excel parsing
│   │   ├── vector_store.py        # ChromaDB vector storage
│   │   ├── retriever.py           # Hybrid retrieval (vector + keyword)
│   │   └── embeddings.py          # Embedding model abstraction
│   │
│   ├── workflow/                  # 🆕 LangGraph workflow
│   │   ├── graph.py               # Main state graph definition
│   │   ├── state.py               # BookWritingState TypedDict
│   │   ├── nodes.py               # Workflow node implementations
│   │   └── edges.py               # Conditional edge logic
│   │
│   ├── export/                    # 🆕 Export module
│   │   ├── docx_export.py         # DOCX generation (python-docx)
│   │   ├── latex_export.py        # LaTeX source generation
│   │   └── reference_formatter.py # GB/T 7714 & other citation formats
│   │
│   ├── memory/                    # 🆕 Global memory system
│   │   ├── terminology.py         # Terminology dictionary management
│   │   ├── summary_manager.py     # Hierarchical chapter summarization
│   │   └── version_history.py     # Checkpoint & rollback system
│   │
│   ├── web/                       # 🆕 Streamlit Web UI
│   │   ├── app.py                 # Main Streamlit application
│   │   ├── pages/
│   │   │   ├── dashboard.py       # Project dashboard
│   │   │   ├── editor.py          # Chapter editor with diff viewer
│   │   │   ├── outline.py         # Outline management
│   │   │   ├── chat.py            # Chat-based command interface
│   │   │   └── settings.py        # Project & system settings
│   │   └── components/
│   │       ├── chapter_tree.py    # Tree navigation component
│   │       ├── diff_viewer.py     # Version diff comparison
│   │       └── progress_bar.py    # Progress visualization
│   │
│   └── utils/
│       ├── file_utils.py
│       ├── llm_client.py          # Enhanced: Structured Output support
│       ├── prompt_loader.py
│       ├── prompts_context.py
│       └── prompt_integration.py
│
├── prompts/templates/             # Prompt templates (existing + new)
│   ├── citation_agent.yml         # 🆕
│   ├── critic_agent.yml           # 🆕
│   └── ...
│
├── requirements.txt               # Extended dependencies
├── setup.py
├── .env.example                   # Extended environment variables
└── README.md
```

---

## 🤖 New Agents

### CitationAgent

**Purpose**: Automatically identifies claims in generated text that require citations, extracts source information, and formats references.

**Workflow**:
1. Scans chapter content for factual claims, statistics, and quoted material
2. Queries RAG vector store for supporting source documents
3. Extracts relevant passages with page numbers
4. Formats citations according to GB/T 7714 standard
5. Injects formatted references into the chapter's bibliography section

**Configuration**:
```yaml
# prompts/templates/citation_agent.yml
citation_style: gbt7714
min_confidence: 0.7
max_citations_per_chapter: 20
```

### CriticAgent

**Purpose**: Evaluates chapter quality on multiple dimensions and drives the iterative improvement loop.

**Scoring Dimensions** (each 1-10):
- **Coherence**: Logical flow and narrative consistency
- **Style**: Writing quality and tone alignment
- **Completeness**: Coverage of outline requirements
- **Engagement**: Reader interest and pacing
- **Accuracy**: Factual correctness (for non-fiction)

**Workflow**:
1. Receives generated chapter content
2. Scores each dimension independently
3. Computes weighted average score
4. If score < `critic_score_threshold`: provides specific improvement suggestions → triggers rewrite
5. If score ≥ threshold: approves chapter and passes to next stage
6. Maximum iterations capped by `max_review_iterations`

**Configuration**:
```yaml
# prompts/templates/critic_agent.yml
score_threshold: 8.0
max_iterations: 3
weights:
  coherence: 0.25
  style: 0.20
  completeness: 0.25
  engagement: 0.15
  accuracy: 0.15
```

---

<div align="center">

Made with ❤️ by Fernando Guerra and Lenxys

[⭐ Star us on GitHub](https://github.com/guerra2fernando/libriscribe)

If LibriScribe has been helpful for your projects, consider buying me a coffee:

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-Support-yellow.svg?style=flat&logo=buy-me-a-coffee)](https://buymeacoffee.com/guerra2fernando)

</div>
