import click

from reposage.config import load_config
from reposage.sync import sync_repos


@click.group()
def main() -> None:
    """Build a local, chunk-aware knowledge base from a GitHub user's repos."""


@main.command()
def sync() -> None:
    """Clone (or update) the repos listed in repos.txt into the local data dir.

    If repos.txt is empty, falls back to every public, non-fork repo owned
    by GITHUB_USER.
    """
    config = load_config()
    repos = sync_repos(config)
    click.echo(f"Synced {len(repos)} repo(s) into {config.repos_dir}")
