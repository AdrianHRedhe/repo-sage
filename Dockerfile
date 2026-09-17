# Builds a self-contained showcase image: the owner's public repos are
# synced, chunked, and embedded at BUILD time (not at container startup),
# so the deployed container needs no GitHub network access at runtime -
# only the Anthropic API and, if the sandbox is used, github.com for
# visitor-submitted repo clones.
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

COPY --chown=reposage:reposage pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY --chown=reposage:reposage . .
RUN uv sync --frozen --no-dev

# Bake the owner's own repos in at build time. Pass GITHUB_TOKEN as a
# build secret to avoid the 60/hr unauthenticated GitHub REST rate limit
# on rebuilds - only needed if repos.txt is empty (sync-everything mode).
# Deliberately curate repos.txt for the deployed build (rather than
# leaving it empty) if only some public repos should be showcased.
# mode=0444: the secret mount defaults to root-only (0400), unreadable by
# the non-root user this step now runs as.
#
# The embed step downloads the sentence-transformers model (Qwen3-Embedding-0.6B,
# 1GB+) from Hugging Face on first use. Without a cache mount, every rebuild
# re-downloads it from scratch even though it never changes - on a slow
# connection this turned a routine rebuild into an hours-long one. uid/gid
# 1000 match the reposage user created above so it can write into the cache.
ARG GITHUB_USER
RUN --mount=type=secret,id=github_token,mode=0444 \
    --mount=type=cache,target=/home/reposage/.cache/huggingface,uid=1000,gid=1000 \
    GITHUB_USER=${GITHUB_USER} \
    GITHUB_TOKEN=$(cat /run/secrets/github_token 2>/dev/null || echo "") \
    uv run repo-sage sync && \
    for d in data/repos/*/; do \
      uv run repo-sage embed "$(basename "$d")"; \
    done

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "reposage.web.app:app", "--host", "0.0.0.0", "--port", "8000"]
