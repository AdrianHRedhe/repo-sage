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


@main.command(name="list-files")
@click.argument("repo_name")
def list_files(repo_name: str) -> None:
    """Print the filtered file list that would be chunked for one repo."""
    from reposage.filters.include import list_included_files

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
    """Print the chunks that would be produced for one repo, including
    their resolved caller/callee lineage (debug tool)."""
    from reposage.callgraph import attach_lineage
    from reposage.chunking.chunk import format_symbol_label
    from reposage.chunking.repo_chunks import chunk_repo
    from reposage.store.chroma_store import chunk_id

    config = load_config()
    repo_path = config.repos_dir / repo_name
    if not repo_path.exists():
        raise click.ClickException(
            f"'{repo_name}' not found under {config.repos_dir}. Run `repo-sage sync` first."
        )

    chunks_by_file = chunk_repo(repo_name, repo_path)
    all_chunks = [c for file_chunks in chunks_by_file.values() for c in file_chunks]
    enriched_by_id = attach_lineage(all_chunks)

    for chunk in all_chunks:
        chunk = enriched_by_id[chunk_id(chunk)]
        label = format_symbol_label(chunk.symbol, chunk.parent_symbol)
        click.echo(f"{chunk.file_path}:{chunk.start_line}-{chunk.end_line}  {chunk.node_type:<10} {label}")
        if chunk.calls:
            click.echo(f"    calls:      {', '.join(chunk.calls)}")
        if chunk.called_by:
            click.echo(f"    called by:  {', '.join(chunk.called_by)}")


@main.command()
@click.argument("repo_name", required=False)
@click.option("--all", "all_repos", is_flag=True, help="Embed every synced repo instead of one.")
def embed(repo_name: str | None, all_repos: bool) -> None:
    """Chunk, embed, and store synced repos' files in the local Chroma collection.

    `--all` exists so seeding a fresh deployment is one command rather than a
    shell loop over `data/repos/*/` - that glob silently expands to itself when
    the directory is empty, which made a mis-seeded container run
    `embed "*"` instead of failing.
    """
    from reposage.index import index_repo

    config = load_config()

    if all_repos == bool(repo_name):
        raise click.UsageError("Pass either a repo name or --all, not both.")

    if all_repos:
        repo_names = sorted(
            path.name
            for path in (config.repos_dir.iterdir() if config.repos_dir.exists() else [])
            if path.is_dir()
        )
        if not repo_names:
            raise click.ClickException(
                f"No synced repos under {config.repos_dir}. Run `repo-sage sync` first."
            )
    else:
        if not (config.repos_dir / repo_name).exists():
            raise click.ClickException(
                f"'{repo_name}' not found under {config.repos_dir}. Run `repo-sage sync` first."
            )
        repo_names = [repo_name]

    for name in repo_names:
        stats = index_repo(config, name)
        click.echo(
            f"{name}: embedded {stats.embedded}, skipped {stats.skipped} unchanged, "
            f"deleted {stats.deleted} stale chunk(s) into {config.chroma_dir}"
        )


@main.command()
@click.argument("query")
@click.option("--repo", default=None, help="Only search chunks from this repo.")
@click.option("--limit", default=10, show_default=True, help="Number of results to show.")
def search(query: str, repo: str | None, limit: int) -> None:
    """Search embedded chunks for the closest matches to a free-text query."""
    from reposage.chunking.chunk import format_symbol_label
    from reposage.embedding.model import Embedder
    from reposage.store.chroma_store import ChromaStore

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
    from reposage.answer import answer_question

    config = load_config()
    answer = answer_question(config, question, repo=repo, limit=limit)

    click.echo(answer.text)
    if answer.citations:
        click.echo("\nSources:")
        for c in answer.citations:
            click.echo(f"  {c.repo}/{c.file_path}:{c.start_line}-{c.end_line}  {c.label}")
    if answer.related:
        click.echo("\nRelated code (callers/callees):")
        for c in answer.related:
            click.echo(f"  {c.repo}/{c.file_path}:{c.start_line}-{c.end_line}  {c.label}")
    if answer.explored:
        click.echo("\nExplored further:")
        for call in answer.explored:
            click.echo(f"  {call}")


def _echo_summary(label: str, summary: "EvalSummary", limit: int) -> None:
    hits = sum(r.hit for r in summary.results)
    click.echo(f"Hit rate@{limit}: {summary.hit_rate:.0%}  ({hits}/{len(summary.results)})")
    click.echo(f"Mean reciprocal rank: {summary.mean_reciprocal_rank:.3f}")


@main.command(name="eval")
@click.option(
    "--golden",
    "golden_path",
    default="eval",
    show_default=True,
    help="Path to a golden_*.json file, or a directory of them (one per language).",
)
@click.option("--limit", default=5, show_default=True, help="Number of chunks retrieved per question.")
def eval_cmd(golden_path: str, limit: int) -> None:
    """Measure retrieval quality against golden question/answer sets.

    Retrieves the top-k chunks for each golden question and checks whether
    the expected file/symbol shows up (and at what rank), so retrieval
    changes can be compared before/after instead of judged by feel.
    """
    from pathlib import Path

    from reposage.eval import EvalSummary, discover_golden_files, load_golden_cases, run_eval

    config = load_config()
    path = Path(golden_path)
    golden_files = discover_golden_files(path) if path.is_dir() else [path]
    if not golden_files:
        raise click.ClickException(f"No golden_*.json files found in {path}")

    all_results = []
    for golden_file in golden_files:
        label = golden_file.stem.removeprefix("golden_")
        cases = load_golden_cases(golden_file)
        if not cases:
            continue

        summary = run_eval(config, cases, limit=limit)
        all_results.extend(summary.results)

        click.echo(f"== {label} ({golden_file.name}) ==")
        for result in summary.results:
            status = f"hit  (rank {result.rank})" if result.hit else "miss"
            click.echo(f"[{status:<14}] {result.case.repo}: {result.case.question}")
        _echo_summary(label, summary, limit)
        click.echo()

    if len(golden_files) > 1:
        click.echo("== overall ==")
        _echo_summary("overall", EvalSummary(results=all_results), limit)
