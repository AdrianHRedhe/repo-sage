import click

from reposage.chunking.chunk_file import chunk_file
from reposage.config import load_config
from reposage.filters.include import list_included_files
from reposage.filters.languages import language_for
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


@main.command(name="list-files")
@click.argument("repo_name")
def list_files(repo_name: str) -> None:
    """Print the filtered file list that would be chunked for one repo."""
    config = load_config()
    repo_path = config.repos_dir / repo_name
    if not repo_path.exists():
        raise click.ClickException(
            f"'{repo_name}' not found under {config.repos_dir}. Run `repo-sage sync` first."
        )

    for path in list_included_files(repo_path):
        click.echo(path)


@main.command()
@click.argument("repo_name")
def chunks(repo_name: str) -> None:
    """Print the chunks that would be produced for one repo (debug tool)."""
    config = load_config()
    repo_path = config.repos_dir / repo_name
    if not repo_path.exists():
        raise click.ClickException(
            f"'{repo_name}' not found under {config.repos_dir}. Run `repo-sage sync` first."
        )

    for rel_path in list_included_files(repo_path):
        language = language_for(rel_path.suffix)
        if language is None:
            continue

        for chunk in chunk_file(repo_name, repo_path, rel_path, language):
            label = chunk.symbol or "(file)"
            if chunk.parent_symbol:
                label = f"{chunk.parent_symbol}.{label}"
            click.echo(f"{chunk.file_path}:{chunk.start_line}-{chunk.end_line}  {chunk.node_type:<10} {label}")
