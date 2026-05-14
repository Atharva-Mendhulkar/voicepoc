import logging
from config import settings

logger = logging.getLogger("uvicorn")

def create_llm_service():
    provider = settings.llm_provider.lower()
    model = settings.llm_model

    logger.info(f"llm.create provider={provider} model={model}")

    if provider == "openai":
        from pipecat.services.openai.llm import OpenAILLMService
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY must be set when LLM_PROVIDER=openai")
        return OpenAILLMService(
            api_key=settings.openai_api_key,
            model=model or "gpt-4o",
        )

    elif provider == "ollama":
        from pipecat.services.ollama.llm import OLLamaLLMService
        return OLLamaLLMService(
            model=model or "qwen3.5:9b",
            base_url="http://host.docker.internal:11434/v1",
        )

    elif provider == "anthropic":
        from pipecat.services.anthropic.llm import AnthropicLLMService
        return AnthropicLLMService(
            api_key=settings.anthropic_api_key,
            model=model or "claude-3-5-sonnet-20240620",
        )

    elif provider == "google" or provider == "gemini":
        from pipecat.services.google.llm import GoogleLLMService
        return GoogleLLMService(
            api_key=settings.google_api_key,
            model=model or "gemini-1.5-flash",
        )

    else:
        raise ValueError(
            f"Unknown LLM provider: {provider!r}. Valid: openai, ollama, anthropic, google"
        )
