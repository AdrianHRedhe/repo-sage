from dataclasses import asdict
from functools import lru_cache
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from reposage.answer import Answer, answer_question
from reposage.config import Config, load_config
from reposage.embedding.model import Embedder
from reposage.llm.client import LLMClient
from reposage.llm.factory import build_llm_client
from reposage.store.chroma_store import ChromaStore
from reposage.web.auth import check_access_code
from reposage.web.budget import BudgetGuard
from reposage.web.sandbox import SandboxError, read_sandbox_state, sandbox_config_for, submit_sandbox_repo

STATIC_DIR = Path(__file__).parent / "static"


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


app = FastAPI(title="RepoSage")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class AskRequest(BaseModel):
    question: str
    repo: str | None = None
    source: str = "main"  # "main" | "sandbox"


class SandboxSubmitRequest(BaseModel):
    repo_url: str


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


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
    state = read_sandbox_state(config)
    if state is None:
        return {"loaded": False}
    return {"loaded": True, **asdict(state)}


def _answer_to_dict(answer: Answer) -> dict:
    return {
        "text": answer.text,
        "citations": [asdict(c) for c in answer.citations],
        "related": [asdict(c) for c in answer.related],
        "explored": answer.explored,
    }


@app.post("/api/sandbox/submit", dependencies=[Depends(require_access_code)])
def api_sandbox_submit(
    payload: SandboxSubmitRequest,
    config: Config = Depends(get_config),
    budget: BudgetGuard = Depends(get_budget_guard),
) -> dict:
    if not budget.allow():
        raise HTTPException(status_code=429, detail="Usage limit reached - try again later.")

    try:
        state = submit_sandbox_repo(config, payload.repo_url)
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
        state = read_sandbox_state(config)
        if state is None:
            raise HTTPException(status_code=400, detail="No sandbox repo is loaded today.")

        sandbox_config = sandbox_config_for(config, state.slot_id)
        answer = answer_question(sandbox_config, payload.question, repo=state.repo_name, limit=8, client=client)
    else:
        answer = answer_question(
            config, payload.question, repo=payload.repo, limit=8, embedder=embedder, store=store, client=client
        )

    budget.record()
    return _answer_to_dict(answer)
