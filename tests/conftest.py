from pathlib import Path

from reposage.config import Config


def make_config(tmp_path: Path, **overrides) -> Config:
    base = dict(
        github_user="octocat",
        github_token="",
        data_dir=tmp_path,
        repos_file=tmp_path / "repos.txt",
        embedding_model="unused",
        ollama_model="unused",
        ollama_base_url="http://unused",
        llm_provider="ollama",
        anthropic_api_key="",
        anthropic_model="unused",
        max_tokens=1024,
        web_access_code="",
        web_hourly_request_limit=10,
        web_daily_request_limit=30,
    )
    return Config(**{**base, **overrides})
