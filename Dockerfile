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

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev

# Bake the owner's own repos in at build time. Pass GITHUB_TOKEN as a
# build secret to avoid the 60/hr unauthenticated GitHub REST rate limit
# on rebuilds - only needed if repos.txt is empty (sync-everything mode).
# Deliberately curate repos.txt for the deployed build (rather than
# leaving it empty) if only some public repos should be showcased.
ARG GITHUB_USER
RUN --mount=type=secret,id=github_token \
    GITHUB_USER=${GITHUB_USER} \
    GITHUB_TOKEN=$(cat /run/secrets/github_token 2>/dev/null || echo "") \
    uv run repo-sage sync && \
    for d in data/repos/*/; do \
      uv run repo-sage embed "$(basename "$d")"; \
    done

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "reposage.web.app:app", "--host", "0.0.0.0", "--port", "8000"]
