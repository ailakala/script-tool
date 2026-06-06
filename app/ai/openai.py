from typing import AsyncIterator

from openai import AsyncOpenAI

from app.ai.interface import AIProvider
from app.config import OPENAI_API_KEY, OPENAI_BASE_URL


class OpenAIProvider(AIProvider):
    def __init__(self, model: str = "gpt-4o"):
        self._model = model
        kwargs = {"api_key": OPENAI_API_KEY or "not-configured"}
        if OPENAI_BASE_URL:
            kwargs["base_url"] = OPENAI_BASE_URL
        self._client = AsyncOpenAI(**kwargs)

    def model_name(self) -> str:
        return self._model

    async def generate(self, prompt: str, system: str = "",
                       output_format: str = "json") -> str:
        messages = []
        if system:
            # 确保 prompt 包含 "JSON" 关键字（DeepSeek 等 API 要求）
            if "json" not in system.lower():
                system += " Output valid JSON only, no markdown wrapping."
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        kwargs = {
            "model": self._model,
            "messages": messages,
            "max_tokens": 16384,
        }
        if output_format == "json":
            kwargs["response_format"] = {"type": "json_object"}

        response = await self._client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or ""

    async def generate_stream(self, prompt: str, system: str = "") -> AsyncIterator[str]:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        stream = await self._client.chat.completions.create(
            model=self._model, messages=messages, max_tokens=16384, stream=True
        )
        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
