# src/libriscribe/settings.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

class Settings(BaseSettings):
    # === 原有 LLM 配置 ===
    openai_api_key: str = ""
    google_ai_studio_api_key: str = ""
    claude_api_key: str = ""
    deepseek_api_key: str = ""
    mistral_api_key: str = ""
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "openai/gpt-5.5"
    projects_dir: str = str(Path(__file__).parent.parent.parent / "projects")
    default_llm: str = "openai"

    # === 新增：Tavily 搜索配置 ===
    tavily_api_key: str = "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"
    tavily_base_url: str = "https://api.tavily.com"
    tavily_max_results: int = 10
    tavily_search_depth: str = "advanced"

    # === 新增：RAG 配置 ===
    embedding_provider: str = "local"  # openai | local | custom_openai
    embedding_model: str = "all-MiniLM-L6-v2"  # 本地默认模型；OpenAI 时用 text-embedding-3-small
    chroma_persist_dir: str = str(Path(__file__).parent.parent.parent / "chroma_db")
    rag_top_k: int = 5
    rag_chunk_size: int = 1000
    rag_chunk_overlap: int = 200

    # === 新增：Web UI 配置 ===
    web_host: str = "0.0.0.0"
    web_port: int = 8501

    # === 新增：工作流配置 ===
    max_review_iterations: int = 3
    critic_score_threshold: float = 0.7
    cost_optimization: bool = True  # 初稿用低成本模型
    draft_model: str = "gpt-5.5"  # 初稿模型
    polish_model: str = "gpt-5.5"  # 润色模型

    # === 新增：导出配置 ===
    pandoc_path: str = "pandoc"  # Pandoc 可执行文件路径

    model_config = SettingsConfigDict(env_file=".env", extra='ignore')  # type: ignore
