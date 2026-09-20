# RepoSage

Ask questions about a GitHub user's code and get answers with citations back
to the exact repo, file, and line.

RepoSage clones a user's public repos, splits them into chunks at function
and class boundaries, resolves a caller/callee graph across each repo,
embeds everything into a local vector store, and puts an LLM on top. It runs
as a CLI or as a small public chat website with a "bring your own public
repo" sandbox.

**Status:** early stage, but the whole pipeline works end to end.

## Try it out

A live deployment answers questions about my own public repos, plus the
"bring your own public repo" sandbox:
[adrianhredhe.com/services/repo_sage](https://adrianhredhe.com/services/repo_sage).

## Run the website

Everything runs in Docker. You need Docker and `make`.

```bash
cp .env.example .env    # fill in GITHUB_USER and ANTHROPIC_API_KEY
make up                 # build, start, wait until the model is loaded
make seed               # clone + embed the repos (once, then whenever repos.txt changes)
```

Open <http://localhost:8000>.

> **Use `make`, not `docker compose` directly.** `make` sets the build
> platform, which a bare `docker compose up` gets wrong on Apple Silicon in
> a way that does not error, it just makes the app ~100x slower. See
> [Build natively](#build-natively) below.

To also publish it on the public hostname in `cloudflared/config.yml`:

```bash
make tunnel             # everything make up does, plus the cloudflared tunnel
```

Re-run `make up` (or `make tunnel`) after any code change. It rebuilds every
time, so you never end up with an old image still serving.

### make targets

| Command | What it does |
| --- | --- |
| `make up` | Build, start, block until healthy. The one you want after a change. |
| `make seed` | Clone the repos in `repos.txt` and embed them into the data volume. |
| `make tunnel` | `make up`, plus the public cloudflared tunnel. |
| `make logs` | Follow the app log. |
| `make down` | Stop the stack. |
| `make clean` | Stop the stack and delete the data volume. |
| `make verify` | Assert the running image is really the architecture you asked for. |
| `make shell` | A shell inside the container. |

`make up` blocks on the healthcheck, so when it returns the embedding model
is loaded and `/api/ask` will answer rather than hang.

Seeding is safe to re-run: chunks whose content and lineage are unchanged
are skipped. **Check `repos.txt` before seeding** - it is whatever you were
using for local dev, which may not be what you want a stranger asking
questions about. Leave it empty to use every public, non-fork repo owned by
`GITHUB_USER`.

## Run the CLI

Requires [uv](https://docs.astral.sh/uv/). Uses local Ollama by default, so
no API key and nothing leaves your machine.

```bash
uv sync --extra dev
cp .env.example .env     # fill in GITHUB_USER
uv run repo-sage sync    # clone/update the repos in repos.txt into ./data/repos
uv run repo-sage embed --all
uv run repo-sage ask "how does X work"
```

| Command | What it does |
| --- | --- |
| `repo-sage sync` | Clone or `git pull` the repos into `data/repos/`. |
| `repo-sage embed <repo>` | Chunk and embed one repo (`--all` for every repo). |
| `repo-sage ask "..."` | LLM answer with citations. |
| `repo-sage search "..."` | Raw nearest chunks, no LLM. |
| `repo-sage list-files <repo>` | The filtered file list, to sanity check before chunking. |
| `repo-sage chunks <repo>` | The chunks for one repo, with resolved lineage. |
| `repo-sage eval` | Retrieval quality against the golden sets in `eval/`. |

Heads up on first run: `chromadb` and `sentence-transformers` pull in
`torch`, and the first `embed` downloads a few hundred MB of model weights.

## Configuration

All of it lives in `.env`. Only the first two are ever required.

| Variable | Default | Notes |
| --- | --- | --- |
| `GITHUB_USER` | - | The handle to build a knowledge base for. |
| `ANTHROPIC_API_KEY` | - | Required when `LLM_PROVIDER=anthropic`, which is what the Docker image uses. |
| `LLM_PROVIDER` | `ollama` | `ollama` (local, free, private) or `anthropic` (hosted, faster). |
| `ANTHROPIC_MODEL` | `claude-haiku-4-5-20251001` | Deliberately cheap and fast; every call is billed. |
| `OLLAMA_MODEL` / `OLLAMA_BASE_URL` | `qwen3:8b`, `localhost:11434` | Needs a local [Ollama](https://ollama.com) with that model pulled. |
| `LLM_MAX_TOKENS` | `1024` | Caps response length on either provider. |
| `EMBEDDING_MODEL` | `Qwen/Qwen3-Embedding-0.6B` | Any sentence-transformers model. The 4B/8B variants retrieve better if you have a GPU. |
| `GITHUB_TOKEN` | - | Only needed if `repos.txt` is empty, which triggers a REST call to list repos (60/hr becomes 5000/hr). A scopeless PAT is enough. |
| `WEB_ACCESS_CODE` | - | Unset means anyone who finds the URL can spend your API budget. Recommended for a public deploy. |
| `WEB_HOURLY_REQUEST_LIMIT` / `WEB_DAILY_REQUEST_LIMIT` | `10` / `30` | Bound worst-case spend. `0` disables that tier. |

The limits are sized for a few friends to try it, not for production traffic.
There is no per-IP limiting or job queue, which would be disproportionate at
this scale. A capped budget can still be drained by a stranger before the
person it was meant for gets to it, which is why `WEB_ACCESS_CODE` is worth
setting. Currently keeping the API budget low with no top up to avoid any slip
ups.

## How it works

1. **Sync.** Clone each repo in `repos.txt` (or every public non-fork repo
   owned by `GITHUB_USER`) into `data/repos/`, or fast-forward it if already
   cloned. Clones are blobless (`--filter=blob:none`) and sparse, restricted
   to the source extensions step 2 would keep, so git never downloads the
   assets that dominate most repos - one repo here, 28,720 jpgs of street
   imagery, went from 910MB to 12MB. Repos dropped from `repos.txt` have
   their clone deleted, and `embed --all` then drops their embeddings too.
2. **Select files.** Start from `git ls-files` so `.gitignore` is respected,
   then keep known source extensions, dropping lockfiles, minified bundles,
   and anything unusually large.
3. **Chunk.** Python, Go, and Scala split at function/method/class
   boundaries via tree-sitter queries
   (`src/reposage/chunking/queries/`), with enclosing class names and Python
   decorators kept attached. Everything else falls back to overlapping line
   windows, so every file yields at least one chunk.
4. **Resolve a call graph** across the whole repo, since a caller and callee
   are usually in different files. This is name-only matching, not type or
   scope resolution, so `obj.Close()` matches every `Close` in the repo. It
   is a heuristic for surfacing related code, not an exact call graph.
   (Python and Go only.)
5. **Embed.** Each chunk goes into a local Chroma collection along with a
   short `Calls: ... / Called by: ...` line. Caller and callee *bodies* are
   deliberately not blended in, which would dilute the embedding; the names
   alone add the relational signal. Re-running skips unchanged chunks and
   prunes ones that no longer exist.
6. **Answer.** `ask` retrieves the top-k chunks, hydrates their immediate
   callers and callees with real bodies as a separate "Related code"
   section, and hands it all to the LLM. If that is not enough, the model
   can call read-only tools to list or read more of the repo, capped at 3
   rounds before it must answer.
7. **Evaluate.** `eval` runs per-language golden question sets and reports
   hit-rate@k and mean reciprocal rank, so retrieval changes can be compared
   against a number instead of judged by feel.

The website (`src/reposage/web/`) is a FastAPI app wrapping the same
`answer_question` the CLI uses, serving one static page with no build step.
Its sandbox lets a visitor point it at any *other* public GitHub repo, one
slot per UTC day, cleaned up before the next submission. Private repos fail
to clone anonymously, so no separate check is needed.

## Deployment notes

Three things here cost real debugging time and are worth knowing before you
change them.

### Build natively

If `DOCKER_DEFAULT_PLATFORM` is set in your shell (this repo's author has
`linux/x86_64` exported globally from their dotfiles), Docker honours it
over the daemon default, and a bare `docker compose up` on an Apple Silicon
Mac builds and runs the entire app amd64-under-Rosetta. **Nothing errors.**
Embedding just gets slow enough to be indistinguishable from a hang: a seed
run that should take a minute sat at 99% CPU for two and a half days.

`make` sets the platform variables to agree, and `make verify` asserts the
image you got is the one you asked for. If the two ever disagree again,
`docker compose` now fails fast instead of quietly doing the wrong thing. On
an amd64 host, run `make PLATFORM=linux/amd64 up`.

For comparison, native arm64 on the author's machine: the dependency layer
builds from scratch in ~66s, 89 chunks embed in ~49s, one query embeds in
0.26s.

### Memory

`mem_limit` is 8g, sized from measurement. Loading the fp32 embedding model
peaks at ~4.0GB RSS, and a worst-case encode (a full batch of maximum-length
chunks, which a hostile sandbox submission can force) peaks at ~5.9GB.
`src/reposage/embedding/model.py` caps batch size and sequence length to
hold that ceiling; without those caps, `sentence-transformers`' defaults
(batch 32, a 32k context) get the container OOM-killed mid-request.

`memswap_limit` equals `mem_limit` on purpose. With Docker's default 2x swap
allowance an overrun *thrashes forever* instead of dying, which looks
exactly like a hang.

### What lives where

Repos and embeddings live in the `reposage-data` named volume, so they
survive rebuilds and a rebuild takes about a minute instead of re-embedding
everything. The sandbox slot and usage counters live there too, so a restart
no longer resets them.

The embedding model is baked into the image instead. It is ~1.2GB and never
changes, so it belongs in a layer, and the obvious alternative is a trap: a
named volume mounted where the image has no directory is created root-owned,
and this container runs as uid 1000, so `huggingface_hub` cannot write even
the lock files a cache *hit* needs.

## Development

```bash
uv run pytest
```
