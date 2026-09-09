import subprocess
from pathlib import Path

from reposage.filters.languages import language_for

MAX_FILE_SIZE_BYTES = 1_000_000

# Known-noise filenames we want excluded even if a repo doesn't gitignore
# them - lockfiles are machine-generated and add no explanatory value.
DENY_FILENAMES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Cargo.lock",
    "poetry.lock",
    "Gemfile.lock",
    "go.sum",
    "composer.lock",
}


def _is_minified(filename: str) -> bool:
    return ".min." in filename


def list_included_files(repo_path: Path) -> list[Path]:
    """Return paths (relative to repo_path) worth chunking/embedding.

    Starts from git's own gitignore engine (tracked + untracked-but-not-
    ignored files, respecting nested .gitignore/global excludes), then
    narrows to known source-code extensions and drops lockfiles, minified
    files, and anything oversized.
    """
    result = subprocess.run(
        ["git", "-C", str(repo_path), "ls-files", "--cached", "--others", "--exclude-standard"],
        check=True,
        capture_output=True,
        text=True,
    )

    included: list[Path] = []
    for line in result.stdout.splitlines():
        rel_path = Path(line)

        if rel_path.name in DENY_FILENAMES or _is_minified(rel_path.name):
            continue

        if language_for(rel_path.suffix) is None:
            continue

        full_path = repo_path / rel_path
        if not full_path.is_file() or full_path.stat().st_size > MAX_FILE_SIZE_BYTES:
            continue

        included.append(rel_path)

    return sorted(included)
