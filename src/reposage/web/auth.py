from fastapi import HTTPException

from reposage.config import Config


def check_access_code(config: Config, x_access_code: str | None) -> None:
    """Raises 401 if `config.web_access_code` is set and doesn't match.

    An empty `web_access_code` disables the gate entirely - turning auth
    on/off is a config change, not a code change. Kept as a plain function
    (no FastAPI dependency-resolution involved) so it's directly
    unit-testable; reposage/web/app.py wires it into a route dependency
    that resolves `config`/the header via FastAPI's own DI.
    """
    if not config.web_access_code:
        return
    if x_access_code != config.web_access_code:
        raise HTTPException(status_code=401, detail="Missing or incorrect access code.")
