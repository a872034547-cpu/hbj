# src/libriscribe/rag/embeddings.py
"""嵌入模型封装

支持 OpenAI Embedding、自定义 OpenAI-compatible API 和本地 sentence-transformers。
当 OpenAI/custom_openai 初始化失败时，自动降级到本地模型。
"""

import logging
from typing import ClassVar, Dict, List
from libriscribe.settings import Settings

logger = logging.getLogger(__name__)


class EmbeddingProvider:
    """统一的嵌入模型接口，支持 openai / custom_openai / local 三种提供商。
    
    初始化失败时自动降级到本地 sentence-transformers。
    """

    _LOCAL_MODEL_CACHE: ClassVar[Dict[str, object]] = {}

    def __init__(self, provider: str = None, model: str = None, api_base: str = "", api_key: str = "", allow_local_fallback: bool = True):
        settings = Settings()
        self.provider = provider or settings.embedding_provider
        self.model = model or settings.embedding_model
        self._client = None
        self._local_model = None
        self._api_base = api_base or ""
        self._api_key = api_key or ""
        self._allow_local_fallback = allow_local_fallback
        self._init_provider()

    def _init_provider(self):
        """初始化嵌入模型提供商，失败时自动降级到本地模型。"""
        original_provider = self.provider
        
        if self.provider == "openai":
            try:
                from openai import OpenAI
                settings = Settings()
                api_key = self._api_key or settings.openai_api_key
                api_base = self._api_base
                if not api_key:
                    logger.warning("OpenAI API key 未配置，无法初始化远程 embedding 模型。")
                    self._fallback_to_local()
                    return
                self._client = OpenAI(api_key=api_key, base_url=api_base) if api_base else OpenAI(api_key=api_key)
                logger.info(f"OpenAI embedding provider initialized with model: {self.model}")
            except ImportError:
                logger.warning("openai 包未安装，无法初始化远程 embedding 模型。")
                self._fallback_to_local()
                return
            except Exception as e:
                logger.warning(f"OpenAI embedding 初始化失败: {e}")
                self._fallback_to_local()
                return

        elif self.provider == "custom_openai":
            try:
                from openai import OpenAI
                settings = Settings()
                api_base = self._api_base or getattr(settings, 'custom_api_base', '') or ""
                api_key = self._api_key or getattr(settings, 'custom_api_key', '') or ""
                # 尝试从项目模型配置中获取
                if not api_base or not api_key:
                    # 从 session_state 获取（Web 端）
                    try:
                        import streamlit as st
                        profiles = st.session_state.get("model_profiles", [])
                        active_id = st.session_state.get("active_model_profile_id", "")
                        for p in profiles:
                            if p.get("id") == active_id:
                                api_base = p.get("api_base", api_base)
                                api_key = p.get("api_key", api_key)
                                self.model = p.get("model", self.model)
                                break
                    except Exception:
                        pass
                
                if not api_key:
                    logger.warning("自定义 API key 未配置，无法初始化远程 embedding 模型。")
                    self._fallback_to_local()
                    return
                
                self._api_base = api_base
                self._api_key = api_key
                self._client = OpenAI(api_key=api_key, base_url=api_base)
                logger.info(f"Custom OpenAI-compatible embedding provider initialized: base={api_base}, model={self.model}")
            except ImportError:
                logger.warning("openai 包未安装，无法初始化远程 embedding 模型。")
                self._fallback_to_local()
                return
            except Exception as e:
                logger.warning(f"Custom OpenAI embedding 初始化失败: {e}")
                self._fallback_to_local()
                return

        elif self.provider == "local":
            self._init_local_model()
            return

        else:
            logger.warning(f"不支持的 embedding provider: {self.provider}")
            self._fallback_to_local()
            return

    def _init_local_model(self):
        """初始化本地 sentence-transformers 模型；同一进程内复用已加载模型。"""
        try:
            from sentence_transformers import SentenceTransformer
            model_name = self.model or "all-MiniLM-L6-v2"
            # 如果模型名看起来是 OpenAI 的模型，强制替换为本地默认
            if model_name.startswith("text-embedding"):
                model_name = "all-MiniLM-L6-v2"
                self.model = model_name
            cached_model = self._LOCAL_MODEL_CACHE.get(model_name)
            if cached_model is None:
                cached_model = SentenceTransformer(model_name)
                self._LOCAL_MODEL_CACHE[model_name] = cached_model
                logger.info(f"Local embedding model loaded: {model_name}")
            else:
                logger.info(f"Local embedding model reused from cache: {model_name}")
            self._local_model = cached_model
            self.provider = "local"
        except ImportError:
            raise ImportError("sentence-transformers 未安装。请执行: pip install sentence-transformers")
        except Exception as e:
            raise RuntimeError(f"本地 embedding 模型加载失败: {e}")

    def _fallback_to_local(self):
        """降级到本地 embedding 模型。"""
        if not self._allow_local_fallback:
            raise RuntimeError("远程 embedding 初始化失败，且当前索引配置禁止自动下载/加载 HuggingFace 本地模型。")
        logger.info("正在降级到本地 sentence-transformers embedding...")
        self.model = "all-MiniLM-L6-v2"
        self._init_local_model()

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """批量生成文本嵌入向量
        
        Args:
            texts: 要嵌入的文本列表
            
        Returns:
            嵌入向量列表
        """
        if not texts:
            return []

        if self.provider in ("openai", "custom_openai") and self._client:
            # OpenAI-compatible 有批量限制，分批处理
            all_embeddings = []
            batch_size = 100
            for i in range(0, len(texts), batch_size):
                batch = texts[i:i + batch_size]
                try:
                    response = self._client.embeddings.create(
                        model=self.model,
                        input=batch
                    )
                    batch_embeddings = [item.embedding for item in response.data]
                    all_embeddings.extend(batch_embeddings)
                except Exception as e:
                    logger.error(f"Embedding API 调用失败: {e}")
                    # 尝试降级到本地
                    if self.provider != "local" and self._allow_local_fallback:
                        logger.warning("API 调用失败，尝试降级到本地模型...")
                        self._fallback_to_local()
                        return self.embed_texts(texts)
                    raise
            return all_embeddings

        elif self.provider == "local" and self._local_model:
            embeddings = self._local_model.encode(texts, show_progress_bar=False)
            return embeddings.tolist()

        return []

    def embed_query(self, query: str) -> List[float]:
        """生成单条查询的嵌入向量
        
        Args:
            query: 查询文本
            
        Returns:
            嵌入向量
        """
        results = self.embed_texts([query])
        return results[0] if results else []

    @property
    def dimension(self) -> int:
        """返回嵌入向量维度"""
        if self.provider in ("openai", "custom_openai"):
            # text-embedding-3-small: 1536, text-embedding-3-large: 3072
            model_dims = {
                "text-embedding-3-small": 1536,
                "text-embedding-3-large": 3072,
                "text-embedding-ada-002": 1536,
            }
            return model_dims.get(self.model, 1536)
        elif self.provider == "local":
            if self._local_model:
                return self._local_model.get_sentence_embedding_dimension()
            return 384  # all-MiniLM-L6-v2 default
        return 384