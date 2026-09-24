"""Version guard.

The version lives in two places (pyproject.toml and server.SERVER_VERSION) and the tag has to
match both, so assert they agree rather than trusting a release checklist.
"""
import re
from pathlib import Path

import videofetch_mcp
from videofetch_mcp.server import SERVER_NAME, SERVER_VERSION

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_version_is_bumped_to_0_1_0():
    assert videofetch_mcp.__version__ == "0.1.0"
    assert SERVER_VERSION == "0.1.0"


def test_pyproject_version_matches_server_version():
    declared = re.search(r'^version = "([^"]+)"', PYPROJECT.read_text(), re.M).group(1)
    assert declared == SERVER_VERSION, (
        f"pyproject version {declared} != SERVER_VERSION {SERVER_VERSION} — "
        "bump both before tagging mcp-v*"
    )


def test_server_name_is_the_mcp_registration_name():
    # `claude mcp add videofetch ...` and the docs use this exact string.
    assert SERVER_NAME == "videofetch"
