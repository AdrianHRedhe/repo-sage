# RepoSage

Clone a GitHub user's public repos and build a local, chunk-aware knowledge
base to answer questions about their code.

**Status:** early stage. Repos get synced, filtered, and chunked into
function/class-scoped pieces with surrounding context. Embeddings and a
local vector store (Chroma) are planned next.

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

Edit `repos.txt` to list the repos you want included (see comments in the
file for the format).

## Usage

```bash
# Clone/update the repos listed in repos.txt into ./data/repos
uv run repo-sage sync

# See the filtered file list for one repo (sanity check before chunking)
uv run repo-sage list-files <repo-name>

# See the chunks that would be produced for one repo
uv run repo-sage chunks <repo-name>
```

## Development

```bash
uv run pytest
```
