from typing import TYPE_CHECKING

from reposage.llm.anthropic_client import AnthropicClient
from reposage.llm.client import LLMClient
from reposage.llm.ollama_client import OllamaClient

if TYPE_CHECKING:
    from reposage.config import Config


def build_llm_client(config: "Config") -> LLMClient:
    if config.llm_provider == "anthropic":
        if not config.anthropic_api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Required when LLM_PROVIDER=anthropic - "
                "set it in .env, or switch LLM_PROVIDER back to 'ollama'."
            )
        return AnthropicClient(model=config.anthropic_model, api_key=config.anthropic_api_key, max_tokens=config.max_tokens)

    if config.llm_provider == "ollama":
        return OllamaClient(model=config.ollama_model, base_url=config.ollama_base_url, max_tokens=config.max_tokens)

    raise RuntimeError(f"Unknown LLM_PROVIDER '{config.llm_provider}'. Expected 'ollama' or 'anthropic'.")
