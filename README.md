# RepoSage

Clone a GitHub user's public repos and build a local, chunk-aware knowledge
base to answer questions about their code.

**Status:** early stage. Repos get synced, filtered, chunked (with a
heuristic caller/callee graph resolved across each repo), embedded, and
stored in a local vector store. Free-text search over the chunks works, and
`repo-sage ask` layers an LLM on top (local via Ollama, or hosted via the
Anthropic API - switchable with `LLM_PROVIDER`) to synthesize answers with
citations back to repo/file/line. `repo-sage eval` measures retrieval
quality against per-language golden question sets. A small FastAPI app
(`src/reposage/web/`, see "Deploying the demo website" below) wraps the
same Q&A in a public-facing chat page, plus a bounded "bring your own
public repo" sandbox.

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
5. Resolve a heuristic call graph across the whole repo (not just one
   file at a time, since a caller and callee are frequently in different
   files): for Python and Go, another tree-sitter query
   (`chunking/queries/{go,python}_calls.scm`) finds every call site in a
   chunk, and matches the called name against every other chunk's symbol
   in the repo. This is name-only matching, not real type/scope
   resolution - `obj.Close()` matches every `Close` defined anywhere in
   the repo - so it's a heuristic for surfacing likely-related code, not
   an exact call graph. (Scala isn't covered yet.)
6. Embed each chunk with a local model (Qwen3-Embedding by default - fully
   local, no third-party API) and store it in a local Chroma collection
   shared across every repo. What actually gets embedded is the chunk's
   text plus a short `Calls: ...` / `Called by: ...` line naming its
   resolved lineage - full caller/callee bodies aren't blended in, since
   that would dilute the embedding and hurt precision for the chunk
   itself; just the names give a little extra relational signal. Re-running
   `embed` is cheap: chunks whose content *and* lineage haven't changed
   since the last run are skipped, not re-embedded, and chunks that no
   longer exist (renamed/deleted functions or files) are pruned from the
   collection.
7. Answer free-text questions: `search` finds the closest chunks by
   embedding similarity, and `ask` goes further, retrieving the top-k
   chunks and handing them to an LLM to synthesize an answer, citing the
   repo/file/line each part of the answer came from. The LLM provider is
   swappable behind one interface (`reposage/llm/client.py`): `ollama`
   (local, free, private, the default) or `anthropic` (hosted, needs
   `ANTHROPIC_API_KEY`, faster/higher quality) - set with `LLM_PROVIDER`.
   The retrieved chunks' immediate callers/callees are also hydrated with
   their real bodies and added as a separate "Related code" section, so
   the model sees actual related code even when it wasn't the closest
   embedding match itself. If that still isn't enough, the model can call
   read-only tools to list files in, or read more of, the synced repo
   itself - capped at 3 rounds of tool calls before it must give a final
   answer. Response length is capped (`LLM_MAX_TOKENS`) on both providers
   as a cost/runaway-generation guard.
8. Measure retrieval quality: `eval` runs golden question/answer sets, one
   per language (`eval/golden_go.json`, `eval/golden_python.json`, ...),
   against whatever's currently embedded and reports hit-rate@k and mean
   reciprocal rank per language plus overall, so changes to chunking or
   retrieval can be compared against a number instead of judged by feel.

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
- `LLM_PROVIDER` - optional, used by `repo-sage ask`. `ollama` (default,
  local/free/private) or `anthropic` (hosted, faster/higher quality).
- `OLLAMA_MODEL` / `OLLAMA_BASE_URL` - used when `LLM_PROVIDER=ollama`.
  Default to `qwen3:8b` and `http://localhost:11434`. Requires a local
  [Ollama](https://ollama.com) server running with that model pulled
  (`ollama pull qwen3:8b`).
- `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` - used when
  `LLM_PROVIDER=anthropic`. API key is required in that case; model
  defaults to `claude-haiku-4-5-20251001` (deliberately cheap/fast, since
  every call is billed).
- `LLM_MAX_TOKENS` - optional, caps response length on either provider.
  Defaults to 1024.

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

# See the chunks that would be produced for one repo, with resolved
# caller/callee lineage
uv run repo-sage chunks <repo-name>

# Chunk, embed, and store one repo's files locally
uv run repo-sage embed <repo-name>

# Search embedded chunks across every repo (or one, with --repo)
uv run repo-sage search "how does X work" --limit 5

# Ask a free-text question and get an LLM-synthesized answer with citations
# (local Ollama by default; set LLM_PROVIDER=anthropic to use the hosted API)
uv run repo-sage ask "how does X work" --limit 5

# Measure retrieval quality against per-language golden question sets
# (eval/golden_go.json, eval/golden_python.json, ...), so retrieval
# changes can be compared before/after instead of judged by feel
uv run repo-sage eval --limit 5
```

## Development

```bash
uv run pytest
```

## Deploying the demo website

`src/reposage/web/` is a small FastAPI app (`GET /`, `/api/repos`,
`/api/ask`, `/api/sandbox/*`) wrapping the same `answer_question` used by
the CLI - a single static page (`web/static/index.html`, no build step) to
chat with the owner's own pre-embedded repos, plus a bounded "bring your
own repo" sandbox: a visitor can point it at any *other* public GitHub
repo, one slot per UTC day, cleaned up before the next submission (private
repos simply fail to clone anonymously - no separate check needed).

Design choices worth knowing before deploying:

- **Anthropic, not Ollama, for the hosted deployment.** Running a local
  model for public traffic on a small box isn't practical; the Docker
  image defaults `LLM_PROVIDER=anthropic` with the cheap/fast
  `claude-haiku-4-5-20251001`. (Ollama stays the default for local/CLI use
  - see above.)
- **A request budget exists because real people other than you will be
  able to reach this.** `WEB_HOURLY_REQUEST_LIMIT` / `WEB_DAILY_REQUEST_LIMIT`
  (defaults 10/hour, 30/day) bound worst-case spend; either can be set to
  0 to disable that tier. Sized for "a few friends/recruiters try it," not
  production traffic - there's no per-IP limiting or job queue, since that
  would be disproportionate at this scale.
- **`WEB_ACCESS_CODE` is recommended for a real deployment**, even with
  the budget cap - a capped budget can still be exhausted by a stranger
  before the friend/recruiter it's meant for gets to try it. It's an
  env var, so turning the gate on/off doesn't touch code; leave it unset
  to run fully open.
- **The showcase repos live in a named volume, seeded once**, not baked
  into the image - `make seed` runs `repo-sage sync` (using whatever
  `repos.txt` says - leave it empty to use the existing "every public,
  non-fork repo" fallback, exactly "download all my public repos") and
  `repo-sage embed --all` inside the container, writing into the
  `reposage-data` volume. Rebuilds then take about a minute instead of
  re-embedding everything. **Check what's in `repos.txt` before seeding** -
  it's whatever you've been using for local dev, which may not be what you
  want a recruiter asking questions about.
- **The embedding model is baked into the image**, though. It's ~1.2GB and
  never changes, so it belongs in a layer, and the obvious alternative is a
  trap: a named volume mounted where the image has no directory is created
  root-owned, and this container runs as uid 1000, so `huggingface_hub`
  cannot write even the lock files a cache *hit* needs.

Build and run:

```bash
cp .env.example .env   # fill in GITHUB_USER, ANTHROPIC_API_KEY, WEB_ACCESS_CODE, ...
make up                # build, start, wait until the model is loaded
make seed              # once, and again whenever repos.txt changes
```

`make up` blocks on the container healthcheck, so when it returns the
embedding model is loaded and `/api/ask` will answer rather than hang. It
then asserts the built image's architecture matches the platform it asked
for - see the next point for why that check earns its keep.

### Build the image natively, and check that you did

Use `make`, not bare `docker compose`. If `DOCKER_DEFAULT_PLATFORM` is set
in your shell (this repo's author has `linux/x86_64` exported globally from
their dotfiles), Docker honours it over the daemon default, and a plain
`docker compose up` on an Apple Silicon Mac builds and runs the whole app
amd64-under-Rosetta. **Nothing errors.** Embedding just gets slow enough to
be indistinguishable from a hang - a seed run that should take a minute sat
at 99% CPU for two and a half days - which is why this went undiagnosed for
so long. `make` sets the platform variables to agree; if they ever disagree
again, `docker compose` now fails fast instead of quietly doing the wrong
thing. On an amd64 host, use `make PLATFORM=linux/amd64 up`.

Native arm64 numbers on the author's machine, for comparison: the
dependency layer builds from scratch in ~66s, 89 real chunks embed in ~49s,
and a single query embeds in 0.26s.

### Memory

`mem_limit` is 8g, sized from measurement rather than taste: loading the
fp32 embedding model peaks at ~4.0GB RSS, and a worst-case encode - a full
batch of maximum-length chunks, which a hostile sandbox submission can
force - peaks at ~5.9GB. `src/reposage/embedding/model.py` caps batch size
and sequence length to keep that ceiling where it is; without those caps,
`sentence-transformers`' defaults (batch 32, a 32k context) get the
container OOM-killed mid-request. `memswap_limit` equals `mem_limit` on
purpose: with Docker's default 2x swap allowance an overrun *thrashes
forever* instead of dying, which looks exactly like a hang.

The `reposage-data` volume persists repos and embeddings across rebuilds;
the sandbox slot and usage counters live in it too, so a restart no longer
resets them.
