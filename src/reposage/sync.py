import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from reposage.config import Config
from reposage.filters.languages import EXTENSION_LANGUAGE
from reposage.github_api import list_all_nonfork_repo_names
from reposage.repo_list import load_repo_names

# gitignore-style patterns handed to `git sparse-checkout`, so a clone only
# ever materialises files we might actually chunk. Derived from
# EXTENSION_LANGUAGE rather than written out by hand, so adding a language
# stays a one-line change there and the two can't drift apart.
#
# This is a bandwidth and disk fix, not a filtering one - list_included_files
# still decides what gets chunked, and still re-checks everything itself.
# Paired with --filter=blob:none, git never downloads the blobs for anything
# outside the set. Measured on the worst repo here (28,720 jpgs of street
# imagery): 910MB of a 1.0GB data volume became 12MB, and a full-history
# `git pull --ff-only` still works afterwards because both the filter and
# the sparse rules persist in the clone's own config.
SPARSE_CHECKOUT_PATTERNS: list[str] = [
    # Nested .gitignore files, so the `--others --exclude-standard` half of
    # list_included_files still honours them.
    ".gitignore",
    *(f"*{extension}" for extension in sorted(EXTENSION_LANGUAGE)),
]


@dataclass(frozen=True)
class SyncResult:
    synced: list[str]
    removed: list[str]
    failed: dict[str, str]


def clone_url_for(user: str, name: str) -> str:
    return f"https://github.com/{user}/{name}.git"


def _git(dest: Path, *args: str, timeout: int | None = None) -> None:
    subprocess.run(["git", "-C", str(dest), *args], check=True, timeout=timeout)


def _is_blobless_sparse(dest: Path) -> bool:
    """True if `dest` was cloned with the blobless+sparse setup below.

    A checkout made before that setup existed is an ordinary full clone with
    every blob already on disk, and fast-forwarding one only ever keeps it
    that way - so clone_or_update re-clones those instead of pulling.
    """
    for key, expected in (
        ("remote.origin.partialclonefilter", "blob:none"),
        ("core.sparseCheckout", "true"),
    ):
        result = subprocess.run(
            ["git", "-C", str(dest), "config", "--get", key],
            capture_output=True,
            text=True,
        )
        if result.stdout.strip() != expected:
            return False
    return True


def clone_or_update(
    name: str,
    clone_url: str,
    dest: Path,
    shallow: bool = False,
    timeout: int | None = None,
    sparse_patterns: list[str] | None = None,
) -> None:
    """shallow/timeout are for cloning repos we don't otherwise trust the
    size or availability of (reposage/web/sandbox.py cloning an arbitrary
    visitor-supplied public repo) - the default sync path (the user's own
    configured repos) doesn't need either.

    `sparse_patterns` restricts what lands in the working tree *and*, via
    the blobless partial clone, what is downloaded at all. Both callers pass
    SPARSE_CHECKOUT_PATTERNS; it stays optional so a caller that wants a
    plain clone can still have one.
    """
    if (dest / ".git").exists():
        if sparse_patterns and not _is_blobless_sparse(dest):
            print(f"Re-cloning {name} (existing clone predates the sparse checkout)...")
            shutil.rmtree(dest)
        else:
            print(f"Updating {name}...")
            _git(dest, "pull", "--ff-only", timeout=timeout)
            return

    print(f"Cloning {name}...")
    clone_command = ["git", "clone"]
    if shallow:
        clone_command += ["--depth", "1"]
    if sparse_patterns:
        # --no-checkout so the sparse rules are in place before anything is
        # materialised; checking out first downloads every blob once, which
        # is the entire cost we're avoiding.
        clone_command += ["--filter=blob:none", "--no-checkout"]
    clone_command += [clone_url, str(dest)]
    subprocess.run(clone_command, check=True, timeout=timeout)

    if sparse_patterns:
        _git(dest, "sparse-checkout", "set", "--no-cone", *sparse_patterns, timeout=timeout)
        _git(dest, "checkout", timeout=timeout)


def resolve_repo_names(config: Config) -> tuple[list[str], bool]:
    """Returns (names, used_everything_fallback)."""
    names = load_repo_names(config.repos_file)
    if names:
        return names, False

    return list_all_nonfork_repo_names(config.github_user, config.github_token), True


def prune_removed_repos(config: Config, keep_names: list[str]) -> list[str]:
    """Delete clones under repos_dir that `keep_names` no longer lists.

    Without this a repo dropped from repos.txt stays cloned forever, and
    because `embed --all` walks repos_dir rather than repos.txt it also
    stays embedded and keeps turning up in answers. Left alone long enough
    the leftovers dominate: this data volume was still carrying four repos
    from a much earlier run against an empty repos.txt.

    Returns the names removed. Callers must not pass an empty keep list -
    see the guard in sync_repos.
    """
    if not config.repos_dir.exists():
        return []

    keep = set(keep_names)
    removed = []
    for path in sorted(config.repos_dir.iterdir()):
        if path.is_dir() and path.name not in keep:
            shutil.rmtree(path)
            removed.append(path.name)

    return removed


def sync_repos(config: Config) -> SyncResult:
    names, used_everything_fallback = resolve_repo_names(config)

    if used_everything_fallback:
        print(
            f"{config.repos_file} is empty - falling back to every public, "
            f"non-fork repo owned by {config.github_user}. For day-to-day "
            "development, list specific repos there to avoid downloading "
            "everything."
        )

    config.repos_dir.mkdir(parents=True, exist_ok=True)

    # Pruned before cloning, not after, so the disk the leftovers were
    # holding is available to the clones that replace them.
    #
    # Guarded on a non-empty list on purpose. An empty `names` here means
    # either repos.txt is empty *and* GitHub reported no public repos, or
    # something upstream returned nothing unexpectedly - and "delete every
    # clone" is not a recovery to perform automatically on that evidence.
    removed = prune_removed_repos(config, names) if names else []
    for name in removed:
        print(f"Removing {name} (no longer listed)...")

    synced: list[str] = []
    failed: dict[str, str] = {}
    for name in names:
        try:
            clone_or_update(
                name,
                clone_url_for(config.github_user, name),
                config.repos_dir / name,
                sparse_patterns=SPARSE_CHECKOUT_PATTERNS,
            )
            synced.append(name)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            # A repo that is renamed, deleted, private, or simply not public
            # yet shouldn't stop the other dozen from updating - one bad
            # entry used to abort the whole run, and `make seed` with it.
            # Not swallowed either: the caller reports these and exits
            # non-zero, so a typo in repos.txt still reads as a failure
            # rather than as a repo that happens to contain no code.
            print(f"Failed to sync {name}: {error}")
            failed[name] = type(error).__name__

    return SyncResult(synced=synced, removed=removed, failed=failed)
