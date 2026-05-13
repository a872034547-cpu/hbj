# src/libriscribe/utils/llm_client.py
import openai
from openai import OpenAI  # For OpenAI
import logging
import json
import re
from tenacity import retry, stop_after_attempt, wait_random_exponential
from libriscribe.settings import Settings

import requests  # For DeepSeek and Mistral

# ADDED THIS: Import the function
from libriscribe.utils.file_utils import extract_json_from_markdown

logger = logging.getLogger(__name__)

# Configure httpx logger to be less verbose
httpx_logger = logging.getLogger("httpx")
httpx_logger.setLevel(logging.WARNING)  # Or ERROR, to suppress even warnings


class LLMClient:
    """Unified LLM client for multiple providers."""

    def __init__(self, llm_provider: str, api_base: str = "", api_key: str = "", model: str = ""):
        self.settings = Settings()
        self.llm_provider = llm_provider
        self.custom_api_base = api_base
        self.custom_api_key = api_key
        self.custom_model = model
        self.last_error = ""
        self.last_response_preview = ""
        self.last_usage: dict = {}
        self.last_completion_tokens = 0
        self.last_total_tokens = 0
        self.client = self._get_client()
        self.model = self._get_default_model()

    def _get_client(self):
        """Initializes the appropriate client based on the provider."""
        if self.llm_provider == "openrouter":
            api_key = self.custom_api_key or self.settings.openrouter_api_key
            base_url = self.custom_api_base or self.settings.openrouter_base_url
            if not api_key:
                raise ValueError("OpenRouter API key is not set.")
            return OpenAI(api_key=api_key, base_url=base_url)
        elif self.llm_provider == "openai":
            api_key = self.custom_api_key or self.settings.openai_api_key
            if not api_key:
                raise ValueError("OpenAI API key is not set.")
            if self.custom_api_base:
                return OpenAI(api_key=api_key, base_url=self.custom_api_base)
            return OpenAI(api_key=api_key)
        elif self.llm_provider == "claude":
            try:
                import anthropic
            except ImportError:
                raise ValueError("Claude provider requires 'anthropic' package. Install with: pip install anthropic")
            api_key = self.custom_api_key or self.settings.claude_api_key
            if not api_key:
                raise ValueError("Claude API key is not set.")
            return anthropic.Anthropic(api_key=api_key)
        elif self.llm_provider == "google_ai_studio":
            try:
                import google.generativeai as genai
            except ImportError:
                raise ValueError("Google AI Studio requires 'google-generativeai' package. Install with: pip install google-generativeai")
            api_key = self.custom_api_key or self.settings.google_ai_studio_api_key
            if not api_key:
                raise ValueError("Google AI Studio API key is not set.")
            genai.configure(api_key=api_key)
            return genai  # We don't instantiate a client, we use the module directly
        elif self.llm_provider == "deepseek":
             if not (self.custom_api_key or self.settings.deepseek_api_key):
                raise ValueError("DeepSeek API key is not set.")
             return None  # No client object, we'll use requests directly
        elif self.llm_provider == "mistral":
             if not (self.custom_api_key or self.settings.mistral_api_key):
                raise ValueError("Mistral API key is not set")
             return None
        elif self.llm_provider == "custom":
            if not self.custom_api_key:
                raise ValueError("Custom API key is not set.")
            return OpenAI(
                api_key=self.custom_api_key,
                base_url=self.custom_api_base
            )
        else:
            raise ValueError(f"Unsupported LLM provider: {self.llm_provider}")

    def _get_default_model(self):
        """Gets the default model name for the selected provider."""
        if self.custom_model:
            return self.custom_model
        if self.llm_provider == "openrouter":
            return self.settings.openrouter_model
        elif self.llm_provider == "openai":
            return "gpt-5.5"
        elif self.llm_provider == "claude":
            return "claude-sonnet-4-5"
        elif self.llm_provider == "google_ai_studio":
            return "gemini-3.1-pro-preview"
        elif self.llm_provider == "deepseek":
             return "deepseek-v4-pro"
        elif self.llm_provider == "mistral":
            return "mistral-medium-latest"
        elif self.llm_provider == "custom":
            return self.custom_model or "gpt-5.5"
        else:
            return "unknown"  # Should not happen, but good for safety
    def set_model(self, model_name: str):
      self.model = model_name

    def _capture_usage(self, response) -> None:
        """记录最近一次模型调用的 token usage，供上层字数控制做历史预估。"""
        usage = None
        try:
            if isinstance(response, dict):
                usage = response.get("usage")
            elif hasattr(response, "usage"):
                usage = getattr(response, "usage")
        except Exception:
            usage = None
        if usage is None:
            return
        try:
            if not isinstance(usage, dict):
                if hasattr(usage, "model_dump"):
                    usage = usage.model_dump()
                elif hasattr(usage, "dict"):
                    usage = usage.dict()
                else:
                    usage = {
                        key: getattr(usage, key, 0)
                        for key in ("completion_tokens", "output_tokens", "total_tokens")
                        if hasattr(usage, key)
                    }
            self.last_usage = dict(usage or {})
            completion = self.last_usage.get("completion_tokens") or self.last_usage.get("output_tokens") or 0
            total = self.last_usage.get("total_tokens") or 0
            self.last_completion_tokens = int(completion or 0)
            self.last_total_tokens = int(total or 0)
        except Exception:
            logger.debug("Failed to capture token usage from response", exc_info=True)

    def _safe_response_payload(self, response):
        """将 OpenAI SDK / 第三方 SDK 对象转为可读结构，便于诊断空响应。"""
        if response is None or isinstance(response, (str, int, float, bool, list, dict)):
            return response
        for method_name in ("model_dump", "to_dict_recursive", "to_dict", "dict"):
            method = getattr(response, method_name, None)
            if callable(method):
                try:
                    return method()
                except Exception:
                    pass
        for method_name in ("model_dump_json", "json"):
            method = getattr(response, method_name, None)
            if callable(method):
                try:
                    return json.loads(method())
                except Exception:
                    pass
        return str(response)

    def _safe_response_preview(self, response, limit: int = 2000) -> str:
        """生成不含密钥的响应预览；用于连接检测失败时说明真实返回结构。"""
        try:
            payload = self._safe_response_payload(response)
            if isinstance(payload, (dict, list)):
                return json.dumps(payload, ensure_ascii=False, default=str)[:limit]
            return str(payload)[:limit]
        except Exception:
            return str(response)[:limit]

    @staticmethod
    def _strip_role_marker_noise(text: str) -> str:
        """剥离 OpenAI-compatible 中转误返回/泄露的 chat role 标记。"""
        value = str(text or "").strip()
        if not value:
            return ""
        value = re.sub(r"(?im)^\s*(?:assistant\s*){1,8}[:：\-—\s]*", "", value)
        value = re.sub(r"(?im)^\s*(?:user|system|tool|developer)\s*[:：\-—]\s*", "", value)
        value = re.sub(r"(?i)(?<=\n)(?:assistant\s*){2,}(?=\S)", "", value)
        value = re.sub(r"(?i)^(?:assistant\s*){2,}(?=\S)", "", value)
        return value.strip()

    @classmethod
    def _is_role_marker_only(cls, text: str) -> bool:
        """判断响应是否只有 assistant/user/system 等角色名，没有真正正文。"""
        raw = str(text or "").strip()
        if not raw:
            return True
        compact = re.sub(r"[\s:：\-—_`'\"，。,.!！?？\[\]()（）{}<>]+", "", raw, flags=re.IGNORECASE).lower()
        if compact in {"assistant", "assistantassistant", "user", "system", "tool", "developer"}:
            return True
        return not cls._strip_role_marker_noise(raw)

    def _valid_generated_text_or_empty(self, text: str, *, source: str = "模型") -> str:
        """返回有效正文；若只得到角色标记，记录清晰诊断并返回空。"""
        value = str(text or "").strip()
        self.last_response_preview = value[:2000]
        if self._is_role_marker_only(value):
            self.last_error = (
                f"{source}只返回了 chat 角色标记“{value[:80] or '空'}”，没有正文。"
                "这通常表示 API Base、模型名称或 OpenAI-compatible 协议不匹配，"
                "也可能是中转站把流式 role 字段误当作 content 返回。"
            )
            return ""
        return value

    def _stringify_content_blocks(self, content) -> str:
        """兼容 OpenAI-compatible 平台常见的 content 分块格式。"""
        text = self._deep_find_text(content, prefer_text_keys=True)
        return self._strip_role_marker_noise(text)

    def _deep_find_text(self, value, prefer_text_keys: bool = False, _depth: int = 0) -> str:
        """递归提取不同 OpenAI-like 响应结构中的正文。"""
        if value is None or _depth > 10:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (int, float, bool)):
            return ""

        payload = self._safe_response_payload(value)
        if payload is not value:
            return self._deep_find_text(payload, prefer_text_keys=prefer_text_keys, _depth=_depth + 1)

        if isinstance(value, list):
            parts = [self._deep_find_text(item, prefer_text_keys=True, _depth=_depth + 1) for item in value]
            return "\n".join(part for part in parts if part).strip()

        if isinstance(value, dict):
            if prefer_text_keys:
                for key in ("text", "content", "value", "output_text", "reasoning_content"):
                    found = self._deep_find_text(value.get(key), prefer_text_keys=True, _depth=_depth + 1)
                    if found:
                        return found
            for key in ("output_text", "message", "content", "reasoning_content", "text", "delta", "output"):
                found = self._deep_find_text(value.get(key), prefer_text_keys=True, _depth=_depth + 1)
                if found:
                    return found
            if value.get("choices"):
                found = self._deep_find_text(value.get("choices"), prefer_text_keys=True, _depth=_depth + 1)
                if found:
                    return found
            for item in value.values():
                found = self._deep_find_text(item, prefer_text_keys=True, _depth=_depth + 1)
                if found:
                    return found
            return ""

        for attr in ("output_text", "message", "content", "reasoning_content", "text", "delta", "output", "choices"):
            if hasattr(value, attr):
                found = self._deep_find_text(getattr(value, attr), prefer_text_keys=True, _depth=_depth + 1)
                if found:
                    return found
        return ""

    def _extract_openai_compatible_text(self, response) -> str:
        """兼容标准与第三方 OpenAI-like 返回格式，包含 choices.text / responses.output。"""
        text = self._deep_find_text(response)
        if text and not text.startswith(("ChatCompletion(", "Response(")):
            raw_text = str(text).strip()
            if self._is_role_marker_only(raw_text):
                self.last_response_preview = raw_text[:2000]
                self.last_error = (
                    f"模型只返回了 chat 角色标记“{raw_text[:80] or '空'}”，没有正文。"
                    "请检查 API Base 是否应以 /v1 结尾、模型名称是否真实可用，"
                    "以及该中转是否完整兼容 /chat/completions 的 message.content。"
                )
                return ""
            return self._strip_role_marker_noise(raw_text)
        return ""

    def stream_content(self, prompt: str, max_tokens: int = 2000, temperature: float = 0.7, language: str = "English"):
        """流式生成文本；不支持真流式的供应商自动降级为一次性返回。"""
        if "IMPORTANT: The content should be written entirely in" not in prompt and language != "English":
            prompt += f"\n\nIMPORTANT: Generate the response in {language}."

        if self.llm_provider == "custom":
            content = self.generate_content(prompt, max_tokens=max_tokens, temperature=temperature, language=language)
            if content:
                yield content
            return

        if self.llm_provider in ("openai", "openrouter"):
            try:
                stream = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt + "\n\nPlease format any JSON output in markdown code blocks with ```json```" if self.llm_provider == "openrouter" else prompt}],
                    max_tokens=max_tokens,
                    temperature=temperature,
                    stream=True,
                )
                for event in stream:
                    if not getattr(event, "choices", None):
                        continue
                    delta = getattr(event.choices[0], "delta", None)
                    chunk = getattr(delta, "content", "") if delta is not None else ""
                    if chunk:
                        yield chunk
                return
            except Exception as exc:
                # 某些 OpenAI-compatible 中转会拦截 openai-python SDK 的流式请求；
                # 降级到 generate_content，复用 raw HTTP 兜底路径，避免章节写作整段失败。
                self.last_error = str(exc)
                logger.warning("Streaming call failed, falling back to non-stream generate_content: %s", exc)
                content = self.generate_content(prompt, max_tokens=max_tokens, temperature=temperature, language=language)
                if content:
                    yield content
                return

        if self.llm_provider == "claude":
            with self.client.messages.stream(
                model=self.model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                for text in stream.text_stream:
                    if text:
                        yield text
            return

        # Google / DeepSeek / Mistral 等先降级为非流式，仍能让页面看到明确状态与最终预览。
        content = self.generate_content(prompt, max_tokens=max_tokens, temperature=temperature, language=language)
        if content:
            yield content

    @retry(wait=wait_random_exponential(min=1, max=60), stop=stop_after_attempt(6))
    def generate_content(
        self,
        prompt: str,
        max_tokens: int = 2000,
        temperature: float = 0.7,
        language: str = "English",
        timeout_seconds: int | None = None,
        raw_attempt_limit: int | None = None,
    ) -> str:
        """
        Generates text using the selected LLM provider.
        Now supports specifying the output language explicitly.
        """
        self.last_error = ""
        self.last_response_preview = ""
        self.last_usage = {}
        self.last_completion_tokens = 0
        self.last_total_tokens = 0
        try:
            # Append language instruction to prompt if not already included
            if "IMPORTANT: The content should be written entirely in" not in prompt and language != "English":
                prompt += f"\n\nIMPORTANT: Generate the response in {language}."
                
            if self.llm_provider == "openai" or self.llm_provider == "openrouter":
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt + "\n\nPlease format any JSON output in markdown code blocks with ```json```" if self.llm_provider == "openrouter" else prompt}],
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                self._capture_usage(response)
                content = response.choices[0].message.content.strip()
                # Post-process OpenRouter responses to ensure markdown JSON format
                if self.llm_provider == "openrouter" and "```json" not in content and "{" in content:
                    json_match = re.search(r'\{.*\}', content, re.DOTALL)
                    if json_match:
                        content = f"```json\n{json_match.group()}\n```"
                return content

            elif self.llm_provider == "claude":
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    messages=[{"role": "user", "content": prompt}]
                )
                self._capture_usage(response)
                return response.content[0].text.strip()

            elif self.llm_provider == "google_ai_studio":
                model = self.client.GenerativeModel(model_name=self.model)
                response = model.generate_content(prompt) # No need for messages list with genai
                return response.text.strip()

            elif self.llm_provider == "deepseek":
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.custom_api_key or self.settings.deepseek_api_key}"
                }
                data = {
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": temperature
                }
                endpoint = (self.custom_api_base.rstrip("/") if self.custom_api_base else "https://api.deepseek.com/v1") + "/chat/completions"
                response = requests.post(endpoint, headers=headers, json=data, timeout=timeout_seconds or 120) # Timeout
                response.raise_for_status() # Raise for HTTP errors
                payload = response.json()
                self._capture_usage(payload)
                return payload["choices"][0]["message"]["content"].strip()
            elif self.llm_provider == "mistral":
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.custom_api_key or self.settings.mistral_api_key}"
                }
                data = {
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": temperature
                }

                endpoint = (self.custom_api_base.rstrip("/") if self.custom_api_base else "https://api.mistral.ai/v1") + "/chat/completions"
                response = requests.post(endpoint, headers=headers, json=data, timeout=timeout_seconds or 120)
                response.raise_for_status()
                payload = response.json()
                self._capture_usage(payload)
                return payload['choices'][0]['message']['content'].strip()

            elif self.llm_provider == "custom":
                messages = [{"role": "user", "content": prompt}]
                chat_attempts = [
                    {"max_tokens": max_tokens, "temperature": temperature},
                    {"max_tokens": min(max_tokens, 12000), "temperature": temperature},
                    {"max_completion_tokens": max_tokens, "temperature": temperature},
                    {"temperature": temperature},
                    {},
                ]
                response_attempts = [
                    {"max_output_tokens": max_tokens, "temperature": temperature},
                    {"max_output_tokens": min(max_tokens, 12000), "temperature": temperature},
                    {},
                ]
                last_exc = None
                skip_sdk = True
                if not skip_sdk:
                    for params in chat_attempts:
                        try:
                            response = self.client.chat.completions.create(
                                model=self.model,
                                messages=messages,
                                **params,
                            )
                            self._capture_usage(response)
                            text = self._extract_openai_compatible_text(response)
                            self.last_response_preview = (text or self._safe_response_preview(response))[:2000]
                            if text:
                                return text
                            last_exc = ValueError(f"chat.completions 返回成功但未提取到正文；响应预览：{self.last_response_preview[:500]}")
                        except Exception as exc:
                            last_exc = exc
                            self.last_error = str(exc)
                            logger.warning("Custom OpenAI-compatible SDK chat call failed with params %s: %s", params, exc)

                # 自定义 OpenAI-compatible 平台统一优先使用 raw HTTP，避免 openai-python SDK 默认请求头/流式协议被中转站拦截。
                raw_endpoint = (self.custom_api_base or "").rstrip("/") + "/chat/completions"
                raw_headers = {
                    "Authorization": f"Bearer {self.custom_api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": "Mozilla/5.0 Libriscribe/2.0 OpenAI-Compatible-Client",
                }
                raw_attempts = [
                    {"max_tokens": max_tokens, "temperature": temperature},
                    {"max_tokens": min(max_tokens, 12000), "temperature": temperature},
                    {"max_tokens": min(max_tokens, 6000), "temperature": 0.3},
                    {"temperature": temperature},
                    {},
                ]
                if raw_attempt_limit is not None:
                    raw_attempts = raw_attempts[:max(1, int(raw_attempt_limit))]
                for params in raw_attempts:
                    try:
                        self.last_error = ""
                        payload = {"model": self.model, "messages": messages, **params}
                        raw_response = requests.post(raw_endpoint, headers=raw_headers, json=payload, timeout=timeout_seconds or 180)
                        raw_preview = raw_response.text[:2000]
                        self.last_response_preview = raw_preview
                        raw_response.raise_for_status()
                        try:
                            raw_payload = raw_response.json()
                        except Exception:
                            raw_payload = raw_response.text
                        self._capture_usage(raw_payload)
                        text = self._extract_openai_compatible_text(raw_payload)
                        self.last_response_preview = (text or self._safe_response_preview(raw_payload))[:2000]
                        valid_text = self._valid_generated_text_or_empty(text, source="自定义 OpenAI-compatible 接口") if text else ""
                        if valid_text:
                            self.last_error = ""
                            return valid_text
                        if self.last_error:
                            last_exc = ValueError(self.last_error)
                        else:
                            last_exc = ValueError(f"requests chat 返回成功但未提取到正文；响应预览：{self.last_response_preview[:500]}")
                    except Exception as exc:
                        last_exc = exc
                        self.last_error = str(exc)
                        logger.warning("Custom OpenAI-compatible raw chat call failed with params %s: %s", params, exc)

                responses_api = getattr(self.client, "responses", None)
                create_response = getattr(responses_api, "create", None) if responses_api is not None else None
                if callable(create_response):
                    for params in response_attempts:
                        try:
                            response = create_response(
                                model=self.model,
                                input=prompt,
                                **params,
                            )
                            self._capture_usage(response)
                            text = self._extract_openai_compatible_text(response)
                            self.last_response_preview = (text or self._safe_response_preview(response))[:2000]
                            valid_text = self._valid_generated_text_or_empty(text, source="自定义 OpenAI-compatible responses 接口") if text else ""
                            if valid_text:
                                return valid_text
                            if self.last_error:
                                last_exc = ValueError(self.last_error)
                            else:
                                last_exc = ValueError(f"responses 返回成功但未提取到正文；响应预览：{self.last_response_preview[:500]}")
                        except Exception as exc:
                            last_exc = exc
                            self.last_error = str(exc)
                            logger.warning("Custom OpenAI-compatible responses call failed with params %s: %s", params, exc)
                raise last_exc or ValueError("Custom OpenAI-compatible call failed")

            else:
                return "" #  Should not happen, provider checked in init

        except Exception as e:
            self.last_error = str(e)
            logger.exception(f"Error during {self.llm_provider} API call: {e}")
            return ""
    @retry(wait=wait_random_exponential(min=1, max=60), stop=stop_after_attempt(3))
    def generate_content_with_json_repair(self, original_prompt: str, max_tokens:int = 2000, temperature:float=0.7) -> str:
        """Generates content and attempts to repair JSON errors."""
        response_text = self.generate_content(original_prompt, max_tokens, temperature)
        if response_text:
            json_data = extract_json_from_markdown(response_text)
            if json_data is not None:
                return response_text # Return the original markdown
            else:
                repair_prompt = f"You are a helpful AI that only returns valid JSON.  Fix the following broken JSON:\n\n```json\n{response_text}\n```"
                repaired_response = self.generate_content(repair_prompt, max_tokens=max_tokens, temperature=0.2) #Low temp for corrections
                if repaired_response:
                    repaired_json = extract_json_from_markdown(repaired_response)
                    if repaired_json is not None:
                        # CRITICAL CHANGE:  Return the JSON *string*, not wrapped in Markdown.
                        return repaired_response 
        logger.error("JSON repair failed.")
        return "" # Return empty