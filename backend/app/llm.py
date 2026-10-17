from openai import AsyncOpenAI
from langsmith.wrappers import wrap_openai
from app.config import settings


def get_llm_client() -> AsyncOpenAI:
    """
    建立指向 Google AI Studio (Gemini) OpenAI 兼容端點的 AsyncOpenAI 客戶端，
    並使用 LangSmith 的 wrap_openai 進行包裝，實現零框架的可觀測性追蹤。
    """
    raw_client = AsyncOpenAI(
        api_key=settings.GEMINI_API_KEY,
        base_url=settings.LLM_BASE_URL,
        max_retries=0,
        timeout=25.0,
    )
    if settings.LANGSMITH_API_KEY and settings.LANGSMITH_TRACING.lower() == "true":
        return wrap_openai(raw_client)
    return raw_client


llm_client = get_llm_client()
