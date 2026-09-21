import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from reposage.answer import Answer, Citation, SymbolRef, answer_question
from reposage.config import Config, load_config
from reposage.embedding.model import Embedder
from reposage.llm.client import LLMClient
from reposage.llm.factory import build_llm_client
from reposage.store.chroma_store import ChromaStore
from reposage.web.auth import check_access_code
from reposage.web.budget import BudgetGuard
from reposage.web.links import github_blob_url
from reposage.web.sandbox import (
    MAX_SANDBOX_REPOS_PER_DAY,
    SandboxError,
    find_slot,
    sandbox_config_for,
    submit_sandbox_repo,
    todays_slots,
)

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Block startup until the embedding model is loaded. Importing torch and
    # materialising the model takes ~10s even on native arm64, so warming here
    # means the server only reports "ready" once queries can actually be
    # served, instead of appearing up but 524-timing-out on the first
    # /api/ask. The container HEALTHCHECK is what makes that visible to
    # Docker - see the Dockerfile.
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, get_embedder)
    yield


@lru_cache
def get_config() -> Config:
    return load_config()


# Cached (built once, reused across requests) rather than constructed
# per-call - Embedder/ChromaStore load model weights and open the
# database, too slow to redo on every request. lru_cache also makes these
# trivially overridable in tests via app.dependency_overrides, without
# ever constructing the real (heavy) versions.
@lru_cache
def get_embedder() -> Embedder:
    return Embedder(get_config().embedding_model)


@lru_cache
def get_main_store() -> ChromaStore:
    return ChromaStore(get_config().chroma_dir)


@lru_cache
def get_llm_client() -> LLMClient:
    return build_llm_client(get_config())


@lru_cache
def get_budget_guard() -> BudgetGuard:
    config = get_config()
    return BudgetGuard(config.data_dir / "web_usage.json", config.web_hourly_request_limit, config.web_daily_request_limit)


def require_access_code(
    config: Config = Depends(get_config), x_access_code: str | None = Header(default=None)
) -> None:
    check_access_code(config, x_access_code)


app = FastAPI(title="RepoSage", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class AskRequest(BaseModel):
    question: str
    repo: str | None = None
    source: str = "main"  # "main" | "sandbox"
    # Which of today's sandbox repos to ask about, by slot_id. Only
    # meaningful when source == "sandbox"; omitted means the most recently
    # loaded one, which is both the useful default for someone who just
    # submitted a repo and what keeps a client that predates multiple
    # slots working.
    sandbox_slot: str | None = None


class SandboxSubmitRequest(BaseModel):
    repo_url: str


@app.get("/")
def index() -> FileResponse:
    # no-store, not just no-cache: index.html *is* the whole client (markup,
    # styles and script are inline), and it is served with no ETag, only a
    # Last-Modified. Browsers are free to reuse a response like that without
    # asking, using a heuristic freshness window derived from its age - so
    # after a deploy visitors kept getting the previous build and it looked
    # like the new feature had never shipped. The document is ~30KB and
    # every real page view already costs an LLM call, so never reusing it
    # is cheap insurance against serving a stale app.
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/api/config")
def api_config(config: Config = Depends(get_config)) -> dict:
    return {"access_code_required": bool(config.web_access_code)}


@app.get("/api/repos")
def api_repos(config: Config = Depends(get_config)) -> dict:
    if not config.repos_dir.exists():
        return {"repos": []}
    return {"repos": sorted(p.name for p in config.repos_dir.iterdir() if p.is_dir())}


@app.get("/api/sandbox/status")
def api_sandbox_status(config: Config = Depends(get_config)) -> dict:
    """Today's sandbox slots, oldest first, plus how many remain.

    Slots from previous days are deliberately not reported even though
    their data is still on disk until the next submission expires it -
    `todays_slots` is the same filter /api/ask applies, so the client can
    never offer a repo that asking would reject.
    """
    slots = todays_slots(config)
    return {
        "repos": [asdict(slot) for slot in slots],
        "slots_used": len(slots),
        "slots_per_day": MAX_SANDBOX_REPOS_PER_DAY,
    }


def _symbol_ref_dict(ref: SymbolRef, repos_dir: Path, owner: str) -> dict:
    url = None
    if ref.repo and ref.file_path and ref.start_line is not None and ref.end_line is not None:
        url = github_blob_url(repos_dir, owner, ref.repo, ref.file_path, ref.start_line, ref.end_line)
    return {**asdict(ref), "url": url}


def _citation_dict(citation: Citation, repos_dir: Path, owner: str) -> dict:
    url = github_blob_url(
        repos_dir, owner, citation.repo, citation.file_path, citation.start_line, citation.end_line
    )
    return {
        **asdict(citation),
        "calls": [_symbol_ref_dict(ref, repos_dir, owner) for ref in citation.calls],
        "called_by": [_symbol_ref_dict(ref, repos_dir, owner) for ref in citation.called_by],
        "url": url,
    }


def _answer_to_dict(answer: Answer, repos_dir: Path, owner: str) -> dict:
    return {
        "text": answer.text,
        "citations": [_citation_dict(c, repos_dir, owner) for c in answer.citations],
        "related": [_citation_dict(c, repos_dir, owner) for c in answer.related],
        "explored": answer.explored,
    }


@app.post("/api/sandbox/submit", dependencies=[Depends(require_access_code)])
def api_sandbox_submit(
    payload: SandboxSubmitRequest,
    config: Config = Depends(get_config),
    budget: BudgetGuard = Depends(get_budget_guard),
    embedder: Embedder = Depends(get_embedder),
) -> dict:
    if not budget.allow():
        raise HTTPException(status_code=429, detail="Usage limit reached - try again later.")

    try:
        # Hand over the already-warm embedder rather than letting index_repo
        # build a second one - two copies of the model don't fit in the
        # container's memory limit, and loading one costs ~10s per request.
        state = submit_sandbox_repo(config, payload.repo_url, embedder=embedder)
    except SandboxError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    budget.record()
    return asdict(state)


@app.post("/api/ask", dependencies=[Depends(require_access_code)])
def api_ask(
    payload: AskRequest,
    config: Config = Depends(get_config),
    embedder: Embedder = Depends(get_embedder),
    store: ChromaStore = Depends(get_main_store),
    client: LLMClient = Depends(get_llm_client),
    budget: BudgetGuard = Depends(get_budget_guard),
) -> dict:
    if not budget.allow():
        raise HTTPException(status_code=429, detail="Usage limit reached - try again later.")

    if payload.source == "sandbox":
        if payload.sandbox_slot:
            state = find_slot(config, payload.sandbox_slot)
            if state is None:
                raise HTTPException(
                    status_code=400,
                    detail="That sandbox repo is no longer loaded - pick one of today's.",
                )
        else:
            slots = todays_slots(config)
            if not slots:
                raise HTTPException(status_code=400, detail="No sandbox repo is loaded today.")
            state = slots[-1]

        sandbox_config = sandbox_config_for(config, state.slot_id)
        # Same warm embedder as the main path - it only holds model weights
        # and knows nothing about which repo it is embedding, so sharing it
        # is safe. The *store* is the part that has to stay sandbox-scoped.
        answer = answer_question(
            sandbox_config,
            payload.question,
            repo=state.repo_name,
            limit=8,
            embedder=embedder,
            client=client,
        )
        result = _answer_to_dict(answer, sandbox_config.repos_dir, state.repo_owner)
    else:
        answer = answer_question(
            config, payload.question, repo=payload.repo, limit=8, embedder=embedder, store=store, client=client
        )
        result = _answer_to_dict(answer, config.repos_dir, config.github_user)

    budget.record()
    return result
