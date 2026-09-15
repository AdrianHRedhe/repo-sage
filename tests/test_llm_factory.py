from pathlib import Path

import pytest
from conftest import make_config

from reposage.llm.anthropic_client import AnthropicClient
from reposage.llm.factory import build_llm_client
from reposage.llm.ollama_client import OllamaClient


def test_builds_ollama_client_by_default(tmp_path: Path) -> None:
    config = make_config(tmp_path, llm_provider="ollama")

    assert isinstance(build_llm_client(config), OllamaClient)


def test_builds_anthropic_client_when_configured(tmp_path: Path) -> None:
    config = make_config(tmp_path, llm_provider="anthropic", anthropic_api_key="sk-test")

    assert isinstance(build_llm_client(config), AnthropicClient)


def test_anthropic_without_api_key_raises(tmp_path: Path) -> None:
    config = make_config(tmp_path, llm_provider="anthropic", anthropic_api_key="")

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        build_llm_client(config)


def test_unknown_provider_raises(tmp_path: Path) -> None:
    config = make_config(tmp_path, llm_provider="bogus")

    with pytest.raises(RuntimeError, match="Unknown LLM_PROVIDER"):
        build_llm_client(config)
