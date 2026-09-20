import json
import re
import shutil
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from reposage.config import Config
from reposage.embedding.model import Embedder
from reposage.filters.include import list_included_files
from reposage.index import index_repo
from reposage.sync import SPARSE_CHECKOUT_PATTERNS, clone_or_update, clone_url_for

# Bounds on what the sandbox will clone+embed - it's cloning a repo the
# owner hasn't vetted, so these exist purely to keep one submission from
# tying up the server for an unreasonable amount of time or disk space.
MAX_SANDBOX_FILES = 300
CLONE_TIMEOUT_SECONDS = 60

_GITHUB_REPO_URL = re.compile(
    r"^https://github\.com/(?P<owner>[\w.-]+)/(?P<name>[\w.-]+?)(?:\.git)?/?$"
)


class SandboxError(Exception):
    """A submission was rejected - message is safe to show the visitor."""


@dataclass(frozen=True)
class SandboxState:
    repo_owner: str
    repo_name: str
    loaded_at: str  # UTC date, "YYYY-MM-DD" - the one-slot-per-day business rule
    slot_id: str  # unique per attempt - the actual storage path key, see sandbox_config_for
    status: str  # "ready" | "processing"


def parse_github_repo_url(url: str) -> tuple[str, str]:
    """Accepts only `https://github.com/<owner>/<name>` (optional
    trailing `.git`/`/`) - no SSH URLs, no other hosts. This is
    deliberately the same shape `clone_url_for` builds, so a submission
    can only ever target GitHub's own public clone endpoint.

    `name` later becomes a path segment (sandbox_config.repos_dir / name)
    - reject "." and ".." explicitly, since [\\w.-]+ otherwise accepts them
    and neither is a real GitHub repo name anyway. submit_sandbox_repo
    also re-checks the resulting path stays inside repos_dir as a second,
    independent layer (the same belt-and-suspenders pattern reposage/tools.py
    uses for read_file/list_files), rather than relying on this regex alone.
    """
    match = _GITHUB_REPO_URL.match(url.strip())
    if not match:
        raise SandboxError(
            "Please provide a public GitHub repo URL like https://github.com/<owner>/<repo>."
        )
    owner, name = match.group("owner"), match.group("name")
    if owner in (".", "..") or name in (".", ".."):
        raise SandboxError(
            "Please provide a public GitHub repo URL like https://github.com/<owner>/<repo>."
        )
    return owner, name


def _sandbox_root(config: Config) -> Path:
    return config.data_dir / "sandbox"


def sandbox_config_for(config: Config, slot_id: str) -> Config:
    """A Config whose repos_dir/chroma_dir are scoped to one sandbox
    "slot" (`data/sandbox/<slot_id>/...`).

    Every submission attempt gets its own never-before-used slot_id
    (see submit_sandbox_repo), not just a per-day one: chromadb caches its
    underlying connection per persist-path for the lifetime of the
    process (SharedSystemClient), so deleting and recreating the *same*
    chroma_dir out from under a long-running server reuses a stale
    connection to the now-gone file and fails ("readonly database"). That
    hazard isn't limited to day boundaries - a same-day retry after a
    failed attempt (e.g. a too-large repo, cleaned up, then a different
    repo submitted right after) would hit it too if attempts shared a
    path. A fresh slot_id per attempt sidesteps it unconditionally: this
    process can never reopen a path it has already deleted.
    """
    return replace(config, data_dir=_sandbox_root(config) / slot_id)


def _state_path(config: Config) -> Path:
    return _sandbox_root(config) / "state.json"


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _new_slot_id(date: str) -> str:
    return f"{date}-{uuid4().hex[:8]}"


def read_sandbox_state(config: Config) -> SandboxState | None:
    path = _state_path(config)
    if not path.exists():
        return None
    return SandboxState(**json.loads(path.read_text()))


def _write_state(config: Config, state: SandboxState) -> None:
    path = _state_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state)))


def _remove_slot(config: Config, slot_id: str) -> None:
    shutil.rmtree(_sandbox_root(config) / slot_id, ignore_errors=True)


def cleanup_sandbox(config: Config) -> None:
    """Removes whatever sandbox data is currently recorded (if any) and
    clears the state file. Safe to call when nothing is loaded."""
    existing = read_sandbox_state(config)
    if existing:
        _remove_slot(config, existing.slot_id)
    _state_path(config).unlink(missing_ok=True)


def submit_sandbox_repo(
    config: Config, repo_url: str, embedder: Embedder | None = None
) -> SandboxState:
    """Clone, chunk, and embed a visitor-submitted public repo into a
    dedicated sandbox store, separate from the owner's own showcase data -
    one slot per UTC day, cleaned up before the next submission.

    Raises SandboxError (safe to show the visitor) if today's slot is
    already taken by a different repo, or the repo is too large for the
    sandbox. A private repo isn't special-cased - it simply fails to
    clone anonymously, which `clone_or_update` surfaces as a
    subprocess.CalledProcessError, not a SandboxError.
    """
    owner, name = parse_github_repo_url(repo_url)
    today = _today()

    existing = read_sandbox_state(config)
    if existing and existing.loaded_at == today:
        if (existing.repo_owner, existing.repo_name) == (owner, name):
            return existing
        raise SandboxError(
            f"Today's sandbox slot is already taken by {existing.repo_owner}/{existing.repo_name} - "
            "try again tomorrow, or ask about that one."
        )

    if existing:
        cleanup_sandbox(config)

    slot_id = _new_slot_id(today)
    sandbox_config = sandbox_config_for(config, slot_id)
    sandbox_config.repos_dir.mkdir(parents=True, exist_ok=True)
    repos_dir = sandbox_config.repos_dir.resolve()
    repo_path = (repos_dir / name).resolve()
    if not repo_path.is_relative_to(repos_dir):
        raise SandboxError("Invalid repo name.")

    try:
        # Sparse here matters more than it does for the owner's own repos:
        # MAX_SANDBOX_FILES is only checked *after* the clone lands, so an
        # image- or dataset-heavy submission could otherwise write gigabytes
        # into the volume within CLONE_TIMEOUT_SECONDS before being rejected.
        # Blobless + sparse means those bytes are never fetched at all.
        clone_or_update(
            name,
            clone_url_for(owner, name),
            repo_path,
            shallow=True,
            timeout=CLONE_TIMEOUT_SECONDS,
            sparse_patterns=SPARSE_CHECKOUT_PATTERNS,
        )

        file_count = len(list_included_files(repo_path))
        if file_count > MAX_SANDBOX_FILES:
            raise SandboxError(
                f"That repo has {file_count} chunkable files, over the sandbox limit of "
                f"{MAX_SANDBOX_FILES} - too large to embed on demand here."
            )

        index_repo(sandbox_config, name, embedder=embedder)
    except Exception:
        _remove_slot(config, slot_id)
        raise

    state = SandboxState(repo_owner=owner, repo_name=name, loaded_at=today, slot_id=slot_id, status="ready")
    _write_state(config, state)
    return state
