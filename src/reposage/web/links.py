import subprocess
from pathlib import Path


def _commit_sha(repo_path: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def github_blob_url(repos_dir: Path, owner: str, repo: str, file_path: str, start_line: int, end_line: int) -> str | None:
    """Permalink to a citation's exact lines on GitHub, anchored to the
    locally cloned repo's current commit so it stays accurate even if the
    repo is updated later. None if the local checkout isn't a git repo
    (e.g. in tests) - callers should omit the link rather than show a
    broken one."""
    sha = _commit_sha(repos_dir / repo)
    if sha is None:
        return None
    anchor = f"L{start_line}" if start_line == end_line else f"L{start_line}-L{end_line}"
    return f"https://github.com/{owner}/{repo}/blob/{sha}/{file_path}#{anchor}"
