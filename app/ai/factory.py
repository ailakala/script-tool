from app.ai.interface import AIProvider
from app.ai.claude import ClaudeProvider
from app.ai.openai import OpenAIProvider
from app.ai.local import LocalLLMProvider
from app.config import AI_PROVIDER, AI_MODEL


def create_ai_provider(provider: str = "", model: str = "") -> AIProvider:
    provider = provider or AI_PROVIDER
    model = model or AI_MODEL
    if provider == "claude":
        return ClaudeProvider(model=model)
    elif provider == "openai":
        return OpenAIProvider(model=model)
    elif provider == "local":
        return LocalLLMProvider(model=model)
    raise ValueError(f"Unknown AI provider: {provider}")
