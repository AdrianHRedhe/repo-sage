import requests

REST_URL = "https://api.github.com"


def list_all_nonfork_repo_names(user: str, token: str) -> list[str]:
    """List every public, non-fork repo name owned by `user`.

    Used as the dev-time fallback when repos.txt is empty: rather than
    requiring every repo to be listed explicitly up front, an empty config
    means "everything". Works without a token (public data), just at GitHub's
    much lower unauthenticated rate limit (60/hr vs 5000/hr).
    """
    headers = {"Authorization": f"bearer {token}"} if token else {}

    names: list[str] = []
    page = 1
    while True:
        response = requests.get(
            f"{REST_URL}/users/{user}/repos",
            params={"type": "public", "per_page": 100, "page": page},
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        batch = response.json()
        if not batch:
            break

        names.extend(item["name"] for item in batch if not item["fork"])
        page += 1

    return names
