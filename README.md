# RepoSage

Clone a GitHub user's public repos and build a local, chunk-aware knowledge
base to answer questions about their code.

**Status:** early stage. Repos get synced, filtered, chunked, embedded, and
stored in a local vector store. Free-text search over the chunks works, and
`repo-sage ask` layers a locally-served LLM (via Ollama) on top to synthesize
answers with citations back to repo/file/line.

## How it works (so far)

1. Fetch the list of repos to sync: repo names listed in `repos.txt`, one per
   line. If `repos.txt` is empty, fall back to every public, non-fork repo
   owned by `GITHUB_USER` (handy once you trust the pipeline; during
   development, listing a repo or two in `repos.txt` keeps `sync` fast).
2. Clone each one into `data/repos/<name>/`, or `git pull --ff-only` it if
   already cloned - so re-running stays cheap and picks up new commits.
3. For each repo, list the files worth looking at: this starts from git's
   own `.gitignore` handling (`git ls-files`) and narrows further to known
   source-code extensions, dropping lockfiles, minified bundles, and
   anything unusually large.
4. Chunk each file. Languages with a tree-sitter query
   (`src/reposage/chunking/queries/`) get split at function/method/class
   boundaries, with a bit of surrounding context attached - a method's chunk
   is tagged with its enclosing class/struct name, and Python decorators
   stay attached to the function they decorate. Currently covers Python, Go,
   and Scala. Anything else (including non-code files like `README.md`)
   falls back to fixed-size overlapping line windows, so every included file
   always produces at least one chunk.
5. Embed each chunk with a local model (Qwen3-Embedding by default - fully
   local, no third-party API) and store it in a local Chroma collection
   shared across every repo. Re-running `embed` is cheap: chunks whose
   content hasn't changed since the last run are skipped, not
   re-embedded, and chunks that no longer exist (renamed/deleted functions
   or files) are pruned from the collection.
6. Answer free-text questions: `search` finds the closest chunks by
   embedding similarity, and `ask` goes further, retrieving the top-k
   chunks and handing them to a local LLM (served by
   [Ollama](https://ollama.com)) to synthesize an answer, citing the
   repo/file/line each part of the answer came from.

## Setup

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync --extra dev
cp .env.example .env
```

Edit `.env`:

- `GITHUB_USER` - the GitHub handle to build a knowledge base for.
- `GITHUB_TOKEN` - optional. `git clone`/`pull` and GitHub's REST API both
  work unauthenticated for public data. Only worth setting if you leave
  `repos.txt` empty, since that triggers a REST call to list every repo, and
  a token raises that rate limit from 60/hr to 5000/hr. A classic PAT with no
  scopes checked is enough - create one at https://github.com/settings/tokens.
- `EMBEDDING_MODEL` - optional, defaults to `Qwen/Qwen3-Embedding-0.6B`.
  Any local sentence-transformers-compatible model name works; larger Qwen3-
  Embedding variants (4B/8B) give better retrieval quality if you have a GPU
  (or patience).
- `OLLAMA_MODEL` / `OLLAMA_BASE_URL` - optional, used by `repo-sage ask`.
  Default to `qwen3:8b` and `http://localhost:11434`. Requires a local
  [Ollama](https://ollama.com) server running with that model pulled
  (`ollama pull qwen3:8b`).

Edit `repos.txt` to list the repos you want included (see comments in the
file for the format).

`chromadb` and `sentence-transformers` are sizeable installs (they pull in
`torch`), and the first `embed` run downloads the embedding model's weights
(a few hundred MB for the default model).

## Usage

```bash
# Clone/update the repos listed in repos.txt into ./data/repos
uv run repo-sage sync

# See the filtered file list for one repo (sanity check before chunking)
uv run repo-sage list-files <repo-name>

# See the chunks that would be produced for one repo
uv run repo-sage chunks <repo-name>

# Chunk, embed, and store one repo's files locally
uv run repo-sage embed <repo-name>

# Search embedded chunks across every repo (or one, with --repo)
uv run repo-sage search "how does X work" --limit 5

# Ask a free-text question and get an LLM-synthesized answer with citations
# (requires a local Ollama server - see OLLAMA_MODEL/OLLAMA_BASE_URL above)
uv run repo-sage ask "how does X work" --limit 5
```

## Development

```bash
uv run pytest
```
