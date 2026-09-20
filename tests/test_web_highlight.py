import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ASSERTIONS = Path(__file__).parent / "highlight_code_assertions.mjs"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_highlight_code_assertions_pass() -> None:
    """Run the highlightCode assertions against the real page.

    The highlighter lives in the one dependency-free HTML file the web app
    ships, so testing it means running JavaScript. Rather than adopt a JS
    test runner for a single function, the assertions are a plain node
    script (tests/highlight_code_assertions.mjs) that evaluates the page's
    own <script> with a stubbed DOM; this just drives it and surfaces the
    failure. Skipped where node is absent, which keeps the suite runnable
    on a bare Python environment - CI's ubuntu-latest has node.
    """
    result = subprocess.run(
        ["node", str(ASSERTIONS)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
