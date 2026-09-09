import subprocess
from pathlib import Path

from reposage.config import Config
from reposage.github_api import list_all_nonfork_repo_names
from reposage.repo_list import load_repo_names


def clone_url_for(user: str, name: str) -> str:
    return f"https://github.com/{user}/{name}.git"


def clone_or_update(name: str, clone_url: str, dest: Path) -> None:
    if (dest / ".git").exists():
        print(f"Updating {name}...")
        subprocess.run(
            ["git", "-C", str(dest), "pull", "--ff-only"],
            check=True,
        )
    else:
        print(f"Cloning {name}...")
        subprocess.run(
            ["git", "clone", clone_url, str(dest)],
            check=True,
        )


def resolve_repo_names(config: Config) -> tuple[list[str], bool]:
    """Returns (names, used_everything_fallback)."""
    names = load_repo_names(config.repos_file)
    if names:
        return names, False

    return list_all_nonfork_repo_names(config.github_user, config.github_token), True


def sync_repos(config: Config) -> list[str]:
    names, used_everything_fallback = resolve_repo_names(config)

    if used_everything_fallback:
        print(
            f"{config.repos_file} is empty - falling back to every public, "
            f"non-fork repo owned by {config.github_user}. For day-to-day "
            "development, list specific repos there to avoid downloading "
            "everything."
        )

    config.repos_dir.mkdir(parents=True, exist_ok=True)

    for name in names:
        clone_or_update(name, clone_url_for(config.github_user, name), config.repos_dir / name)

    return names
