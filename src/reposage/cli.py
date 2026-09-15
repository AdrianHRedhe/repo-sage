from pathlib import Path

import click

from reposage.answer import answer_question
from reposage.chunking.chunk import format_symbol_label
from reposage.chunking.chunk_file import chunk_file
from reposage.config import load_config
from reposage.embedding.model import Embedder
from reposage.eval import load_golden_cases, run_eval
from reposage.filters.include import list_included_files
from reposage.filters.languages import language_for
from reposage.index import index_repo
from reposage.store.chroma_store import ChromaStore
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
            label = format_symbol_label(chunk.symbol, chunk.parent_symbol)
            click.echo(f"{chunk.file_path}:{chunk.start_line}-{chunk.end_line}  {chunk.node_type:<10} {label}")


@main.command()
@click.argument("repo_name")
def embed(repo_name: str) -> None:
    """Chunk, embed, and store one synced repo's files in the local Chroma collection."""
    config = load_config()
    repo_path = config.repos_dir / repo_name
    if not repo_path.exists():
        raise click.ClickException(
            f"'{repo_name}' not found under {config.repos_dir}. Run `repo-sage sync` first."
        )

    stats = index_repo(config, repo_name)
    click.echo(
        f"Embedded {stats.embedded}, skipped {stats.skipped} unchanged, "
        f"deleted {stats.deleted} stale chunk(s) into {config.chroma_dir}"
    )


@main.command()
@click.argument("query")
@click.option("--repo", default=None, help="Only search chunks from this repo.")
@click.option("--limit", default=10, show_default=True, help="Number of results to show.")
def search(query: str, repo: str | None, limit: int) -> None:
    """Search embedded chunks for the closest matches to a free-text query."""
    config = load_config()
    embedder = Embedder(config.embedding_model)
    store = ChromaStore(config.chroma_dir)

    result = store.query(embedder.embed_query(query), n_results=limit, repo=repo)

    ids = result["ids"][0]
    if not ids:
        click.echo("No results. Have you run `repo-sage embed <repo>` yet?")
        return

    for id_, metadata, distance in zip(ids, result["metadatas"][0], result["distances"][0]):
        label = format_symbol_label(metadata["symbol"], metadata["parent_symbol"])
        click.echo(
            f"{distance:.3f}  {metadata['repo']}/{metadata['file_path']}"
            f":{metadata['start_line']}-{metadata['end_line']}  {label}"
        )


@main.command()
@click.argument("question")
@click.option("--repo", default=None, help="Only use chunks from this repo as context.")
@click.option("--limit", default=8, show_default=True, help="Number of chunks to retrieve as context.")
def ask(question: str, repo: str | None, limit: int) -> None:
    """Answer a free-text question about the indexed repos, with citations.

    If the retrieved chunks aren't enough, the model can read further into
    a synced repo itself (read-only, a few rounds of tool calls at most).

    Requires a local Ollama server running with the configured model pulled
    (see OLLAMA_MODEL/OLLAMA_BASE_URL in .env.example).
    """
    config = load_config()
    answer = answer_question(config, question, repo=repo, limit=limit)

    click.echo(answer.text)
    if answer.citations:
        click.echo("\nSources:")
        for c in answer.citations:
            click.echo(f"  {c.repo}/{c.file_path}:{c.start_line}-{c.end_line}  {c.label}")
    if answer.explored:
        click.echo("\nExplored further:")
        for call in answer.explored:
            click.echo(f"  {call}")


@main.command(name="eval")
@click.option(
    "--golden",
    "golden_path",
    default="eval/golden.json",
    show_default=True,
    help="Path to the golden question/answer set.",
)
@click.option("--limit", default=5, show_default=True, help="Number of chunks retrieved per question.")
def eval_cmd(golden_path: str, limit: int) -> None:
    """Measure retrieval quality against a golden question/answer set.

    Retrieves the top-k chunks for each golden question and checks whether
    the expected file/symbol shows up (and at what rank), so retrieval
    changes can be compared before/after instead of judged by feel.
    """
    config = load_config()
    cases = load_golden_cases(Path(golden_path))
    if not cases:
        raise click.ClickException(f"No golden cases found in {golden_path}")

    summary = run_eval(config, cases, limit=limit)

    for result in summary.results:
        status = f"hit  (rank {result.rank})" if result.hit else "miss"
        click.echo(f"[{status:<14}] {result.case.repo}: {result.case.question}")

    click.echo(f"\nHit rate@{limit}: {summary.hit_rate:.0%}  ({sum(r.hit for r in summary.results)}/{len(summary.results)})")
    click.echo(f"Mean reciprocal rank: {summary.mean_reciprocal_rank:.3f}")
