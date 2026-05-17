import logging
from openai import AsyncOpenAI
from config import settings

logger = logging.getLogger("uvicorn")

client = None

def _get_client():
    global client
    if client is None:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
    return client

async def stream_llm(messages: list[dict], tools: list[dict] | None = None):
    c = _get_client()
    kwargs = {
        "model": settings.llm_model or "gpt-4o-mini",
        "messages": messages,
        "stream": True,
    }
    if tools:
        kwargs["tools"] = tools

    stream = await c.chat.completions.create(**kwargs)
    tool_calls_buffer = {}

    async for chunk in stream:
        delta = chunk.choices[0].delta
        if delta.content:
            yield {"type": "content", "content": delta.content}
        if delta.tool_calls:
            for tc in delta.tool_calls:
                idx = tc.index
                if idx not in tool_calls_buffer:
                    tool_calls_buffer[idx] = {
                        "id": tc.id,
                        "name": tc.function.name or "",
                        "arguments": tc.function.arguments or ""
                    }
                else:
                    if tc.function.name:
                        tool_calls_buffer[idx]["name"] += tc.function.name
                    if tc.function.arguments:
                        tool_calls_buffer[idx]["arguments"] += tc.function.arguments

    if tool_calls_buffer:
        yield {"type": "tool_calls", "tool_calls": list(tool_calls_buffer.values())}


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
            settings=OpenAILLMService.Settings(
                model=model or "gpt-4o",
            )
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
