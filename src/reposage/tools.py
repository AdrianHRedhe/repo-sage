from pathlib import Path
from typing import Any

from reposage.config import Config
from reposage.filters.include import list_included_files

MAX_LISTED_FILES = 200
MAX_READ_CHARS = 20_000

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": (
                "List the source files available in a synced repo. Use this "
                "when the retrieved context doesn't mention a file you "
                "suspect is relevant."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "Repo name, e.g. csv2md"},
                },
                "required": ["repo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read a file from a synced repo, optionally a specific line "
                "range. Use this when the retrieved context doesn't give "
                "enough detail to answer confidently."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "Repo name, e.g. csv2md"},
                    "path": {"type": "string", "description": "File path relative to the repo root"},
                    "start_line": {"type": "integer", "description": "1-indexed, optional"},
                    "end_line": {"type": "integer", "description": "1-indexed, inclusive, optional"},
                },
                "required": ["repo", "path"],
            },
        },
    },
]


def _resolve_repo_path(config: Config, repo: str) -> Path:
    repos_dir = config.repos_dir.resolve()
    repo_path = (repos_dir / repo).resolve()
    if not repo_path.is_relative_to(repos_dir) or not repo_path.is_dir():
        raise ValueError(f"unknown repo '{repo}'")
    return repo_path


def _resolve_file_path(repo_path: Path, path: str) -> Path:
    file_path = (repo_path / path).resolve()
    if not file_path.is_relative_to(repo_path):
        raise ValueError(f"path '{path}' escapes the repo")
    return file_path


def list_files_tool(config: Config, repo: str) -> str:
    try:
        repo_path = _resolve_repo_path(config, repo)
    except ValueError as e:
        return f"Error: {e}"

    files = list_included_files(repo_path)
    shown = "\n".join(p.as_posix() for p in files[:MAX_LISTED_FILES])
    if len(files) > MAX_LISTED_FILES:
        shown += f"\n... and {len(files) - MAX_LISTED_FILES} more"
    return shown or "(no chunkable files found)"


def read_file_tool(
    config: Config, repo: str, path: str, start_line: int | None = None, end_line: int | None = None
) -> str:
    try:
        repo_path = _resolve_repo_path(config, repo)
        file_path = _resolve_file_path(repo_path, path)
    except ValueError as e:
        return f"Error: {e}"

    if not file_path.is_file():
        return f"Error: '{path}' not found in repo '{repo}'."

    lines = file_path.read_text(errors="replace").splitlines()
    start = max(start_line or 1, 1)
    end = min(end_line or len(lines), len(lines))
    text = "\n".join(lines[start - 1 : end])

    if len(text) > MAX_READ_CHARS:
        text = text[:MAX_READ_CHARS] + "\n... (truncated)"

    return f"{repo}/{path}:{start}-{end}\n{text}"


def run_tool(config: Config, name: str, arguments: dict[str, Any]) -> str:
    """Dispatch a model-requested tool call by name. Every tool here is
    read-only - the model can look around a synced repo, never change it."""
    if name == "list_files":
        return list_files_tool(config, arguments.get("repo", ""))
    if name == "read_file":
        return read_file_tool(
            config,
            arguments.get("repo", ""),
            arguments.get("path", ""),
            arguments.get("start_line"),
            arguments.get("end_line"),
        )
    return f"Error: unknown tool '{name}'"
