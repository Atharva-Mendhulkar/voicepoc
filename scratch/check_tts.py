from pipecat.services.openai.llm import OpenAILLMService
import inspect

print("OpenAILLMService methods:", [m for m in dir(OpenAILLMService) if not m.startswith("_")])
