# App-only image: repos are synced and embedded at runtime into a named
# Docker volume, not baked into the image. This keeps rebuilds fast (~1min)
# when source changes. Seed the volume once with:
#   docker compose run --rm reposage-web repo-sage sync
#   docker compose run --rm reposage-web repo-sage embed --all
# Re-run those any time repos.txt changes or you want fresh embeddings.
#
# BUILD THIS NATIVE. On an Apple Silicon host an amd64 build runs the whole
# app under Rosetta, where embedding is slow enough to look like a hang
# rather than a failure. docker-compose.yml pins `platform: linux/arm64`
# for exactly that reason - see the comment there before changing it.
FROM python:3.12-slim

# git: needed by `repo-sage sync` (and the sandbox's clone_or_update) to
# clone/pull repos.
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

# Run as a dedicated non-root user - this container processes third-party
# content (visitor-submitted repos via the sandbox), so it shouldn't run
# as root even though nothing in the app deliberately executes cloned
# repo content (tree-sitter only parses text; nothing shells out to or
# imports/evals anything from a cloned repo).
RUN groupadd --gid 1000 reposage && useradd --uid 1000 --gid reposage --create-home reposage

WORKDIR /app
RUN chown reposage:reposage /app
USER reposage

# Create data dir as the reposage user so Docker initialises the named volume
# with correct ownership when it's first mounted (empty volume inherits the
# image directory's permissions).
RUN mkdir -p /app/data

# The venv's bin on PATH means `uvicorn`/`repo-sage` run directly. Going
# through `uv run` instead re-resolves and reinstalls the project on every
# single container start and every `docker compose run`, which is both slow
# and a surprising amount of writing for a process that should just boot.
ENV PATH="/app/.venv/bin:$PATH"

COPY --chown=reposage:reposage pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Bake the embedding model (~1.2GB) into the image rather than downloading
# it at runtime. Deliberately placed after the dependency sync and before
# the source COPY, so editing source never invalidates this layer.
#
# The alternative - a named volume for the HF cache - is a trap: a volume
# mounted at a path the image doesn't already own is created root-owned,
# and this container runs as uid 1000, so huggingface_hub cannot write the
# lock files it needs even for a pure cache hit.
#
# Keep in sync with DEFAULT_EMBEDDING_MODEL in src/reposage/config.py.
ARG EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B
ENV EMBEDDING_MODEL=${EMBEDDING_MODEL}
RUN python -c "\
import os;\
from sentence_transformers import SentenceTransformer;\
SentenceTransformer(os.environ['EMBEDDING_MODEL'])"

# The model is in the image, so never let a cache miss turn into a network
# call (or a multi-second timeout) on a request path.
ENV HF_HUB_OFFLINE=1

COPY --chown=reposage:reposage . .
RUN uv sync --frozen --no-dev

EXPOSE 8000

# The app's lifespan hook loads the embedding model before serving, so the
# process is listening well before it is useful. Without a healthcheck,
# cloudflared happily fronts a container that 524s on the first question.
# /api/config is the one unauthenticated, dependency-free route.
HEALTHCHECK --interval=15s --timeout=10s --start-period=180s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/config', timeout=5)"

CMD ["uvicorn", "reposage.web.app:app", "--host", "0.0.0.0", "--port", "8000"]
