from functools import lru_cache

from app.config import get_settings
from app.services.llm.base import LLMProvider


@lru_cache
def get_provider() -> LLMProvider:
    settings = get_settings()
    if settings.llm_provider == "claude":
        from app.services.llm.claude import ClaudeProvider

        return ClaudeProvider(settings)
    from app.services.llm.demo import DemoProvider

    return DemoProvider()
