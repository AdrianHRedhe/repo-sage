from pathlib import Path


def load_repo_names(path: Path) -> list[str]:
    """Parse the repo allowlist: one repo name per line, '#' comments and
    blank lines ignored. Returns an empty list if the file is empty/missing
    - callers treat that as "no explicit list, sync everything"."""
    if not path.exists():
        return []

    names = []
    for line in path.read_text().splitlines():
        stripped = line.split("#", 1)[0].strip()
        if stripped:
            names.append(stripped)

    return names
