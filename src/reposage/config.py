from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
import os

from reposage.llm.anthropic_client import DEFAULT_ANTHROPIC_MODEL, DEFAULT_MAX_TOKENS
from reposage.llm.ollama_client import DEFAULT_OLLAMA_BASE_URL

load_dotenv()

DEFAULT_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-0.6B"
DEFAULT_OLLAMA_MODEL = "qwen3:8b"
DEFAULT_LLM_PROVIDER = "ollama"


@dataclass(frozen=True)
class Config:
    github_user: str
    github_token: str
    data_dir: Path
    repos_file: Path
    embedding_model: str
    ollama_model: str
    ollama_base_url: str
    llm_provider: str
    anthropic_api_key: str
    anthropic_model: str
    max_tokens: int

    @property
    def repos_dir(self) -> Path:
        return self.data_dir / "repos"

    @property
    def chroma_dir(self) -> Path:
        return self.data_dir / "chroma"


def load_config() -> Config:
    github_user = os.environ.get("GITHUB_USER", "").strip()
    if not github_user:
        raise RuntimeError(
            "GITHUB_USER is not set. Copy .env.example to .env and fill it in."
        )

    # Optional: git clone/pull and the REST API work fine without it for
    # public data, just at a much lower REST rate limit. Only relevant when
    # repos.txt is empty and we fall back to listing every repo via REST.
    github_token = os.environ.get("GITHUB_TOKEN", "").strip()

    data_dir = Path(os.environ.get("DATA_DIR", "./data")).resolve()
    repos_file = Path(os.environ.get("REPOS_FILE", "./repos.txt")).resolve()
    embedding_model = os.environ.get("EMBEDDING_MODEL", "").strip() or DEFAULT_EMBEDDING_MODEL
    ollama_model = os.environ.get("OLLAMA_MODEL", "").strip() or DEFAULT_OLLAMA_MODEL
    ollama_base_url = os.environ.get("OLLAMA_BASE_URL", "").strip() or DEFAULT_OLLAMA_BASE_URL

    llm_provider = os.environ.get("LLM_PROVIDER", "").strip().lower() or DEFAULT_LLM_PROVIDER
    anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    anthropic_model = os.environ.get("ANTHROPIC_MODEL", "").strip() or DEFAULT_ANTHROPIC_MODEL
    max_tokens_raw = os.environ.get("LLM_MAX_TOKENS", "").strip()
    max_tokens = int(max_tokens_raw) if max_tokens_raw else DEFAULT_MAX_TOKENS

    return Config(
        github_user=github_user,
        github_token=github_token,
        data_dir=data_dir,
        repos_file=repos_file,
        embedding_model=embedding_model,
        ollama_model=ollama_model,
        ollama_base_url=ollama_base_url,
        llm_provider=llm_provider,
        anthropic_api_key=anthropic_api_key,
        anthropic_model=anthropic_model,
        max_tokens=max_tokens,
    )
