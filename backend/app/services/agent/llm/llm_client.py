import logging
from dataclasses import dataclass
from typing import Any

from litellm import completion

logger = logging.getLogger(__name__)


@dataclass
class LLMConfig:
    model: str = "gpt-3.5-turbo"
    api_key: str | None = None
    api_url: str | None = None
    temperature: float = 0.7
    max_tokens: int = 1000

    @classmethod
    def from_handler(cls, handler: Any) -> "LLMConfig":
        return cls(
            model=handler.model or "gpt-3.5-turbo",
            api_key=handler.api_key,
            api_url=handler.api_url,
        )


class LLMClient:
    """
    LLM 客户端 - 使用 litellm 统一接口

    支持多种 LLM 提供商:
    - OpenAI: gpt-3.5-turbo, gpt-4, etc.
    - Anthropic: claude-2, claude-instant-1
    - Azure: azure/gpt-35-turbo
    - 本地模型: ollama/llama2, etc.
    """

    def __init__(self, config: LLMConfig):
        self.config = config
        self._conversation_history: list[dict[str, str]] = []

    def chat(
        self,
        message: str,
        system_prompt: str | None = None,
        context: str | None = None,
    ) -> str:
        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        if context:
            context_message = f"Context:\n{context}\n\n"
            messages.append({"role": "system", "content": context_message})

        messages.extend(self._conversation_history)
        messages.append({"role": "user", "content": message})

        try:
            kwargs: dict[str, Any] = {
                "model": self.config.model,
                "messages": messages,
                "temperature": self.config.temperature,
                "max_tokens": self.config.max_tokens,
            }

            if self.config.api_key:
                kwargs["api_key"] = self.config.api_key

            if self.config.api_url:
                kwargs["api_base"] = self.config.api_url

            response = completion(**kwargs)

            content = response.choices[0].message.content

            self._conversation_history.append({"role": "user", "content": message})
            self._conversation_history.append({"role": "assistant", "content": content})

            return content

        except Exception as e:
            logger.error(f"[LLMClient] Error calling LLM: {e}")
            raise

    def chat_with_history(
        self,
        messages: list[dict[str, str]],
        system_prompt: str | None = None,
    ) -> str:
        full_messages = []

        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})

        full_messages.extend(messages)

        try:
            kwargs: dict[str, Any] = {
                "model": self.config.model,
                "messages": full_messages,
                "temperature": self.config.temperature,
                "max_tokens": self.config.max_tokens,
            }

            if self.config.api_key:
                kwargs["api_key"] = self.config.api_key

            if self.config.api_url:
                kwargs["api_base"] = self.config.api_url

            response = completion(**kwargs)
            return response.choices[0].message.content

        except Exception as e:
            logger.error(f"[LLMClient] Error calling LLM: {e}")
            raise

    def clear_history(self):
        self._conversation_history.clear()

    def get_history(self) -> list[dict[str, str]]:
        return list(self._conversation_history)

    def set_history(self, history: list[dict[str, str]]):
        self._conversation_history = list(history)

    def estimate_tokens(self, text: str) -> int:
        return len(text) // 4
