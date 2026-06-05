from typing import AsyncIterator

from openai import AsyncOpenAI

from app.ai.interface import AIProvider
from app.config import OPENAI_API_KEY


class OpenAIProvider(AIProvider):
    def __init__(self, model: str = "gpt-4o"):
        self._model = model
        self._client = AsyncOpenAI(api_key=OPENAI_API_KEY or "not-configured")

    def model_name(self) -> str:
        return self._model

    async def generate(self, prompt: str, system: str = "",
                       output_format: str = "json") -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = await self._client.chat.completions.create(
            model=self._model, messages=messages, max_tokens=4096
        )
        return response.choices[0].message.content or ""

    async def generate_stream(self, prompt: str, system: str = "") -> AsyncIterator[str]:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        stream = await self._client.chat.completions.create(
            model=self._model, messages=messages, max_tokens=4096, stream=True
        )
        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
