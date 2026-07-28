"""The package version must come from the installed distribution metadata.

It used to be hardcoded in ``__init__.py`` and drifted from ``pyproject.toml``
(and so from the version the API advertises), which is what these guard against.

The metadata is only as good as the install, and that is a real failure mode
rather than a hypothetical one: console scripts in ``.venv/bin`` can carry a
shebang pointing at *another* interpreter, in which case pytest runs this
checkout's ``src`` (via the ``pythonpath`` setting) while resolving distribution
metadata from a foreign environment. ``test_metadata_comes_from_this_checkout``
below names that condition explicitly so it reports itself instead of hiding as
a skip.
"""

import json
import tomllib
from importlib.metadata import distribution, version
from pathlib import Path

import streamcatcher

REPO_ROOT = Path(__file__).resolve().parents[1]


def _resolved_distribution_url() -> str | None:
    """The source *directory* the installed ``streamcatcher`` distribution points at.

    ``None`` whenever the install didn't come from a directory, which means there
    is no checkout to compare against: a PyPI install has no ``direct_url.json``
    at all, and one built from a wheel or sdist records ``archive_info`` rather
    than ``dir_info`` (PEP 610). Only a directory install — editable or not — is
    a checkout.
    """
    direct_url = distribution("streamcatcher").read_text("direct_url.json")
    if direct_url is None:
        return None
    payload = json.loads(direct_url)
    if "dir_info" not in payload:
        return None
    return payload.get("url")


def test_metadata_comes_from_this_checkout():
    """The environment resolves *this* source tree, not another one on the machine.

    A mismatch means the tests are reading a foreign install's metadata; recreate
    the environment (``rm -rf .venv && uv sync --all-extras``) rather than
    relaxing this assertion.
    """
    resolved = _resolved_distribution_url()
    if resolved is None:
        return  # not installed from a directory — no checkout to compare against
    assert resolved == REPO_ROOT.as_uri(), (
        f"streamcatcher resolves to {resolved}, not this checkout "
        f"({REPO_ROOT.as_uri()}). The environment is reading another install's "
        f"metadata; recreate it with 'rm -rf .venv && uv sync --all-extras'."
    )


def test_version_comes_from_the_distribution_metadata():
    # A re-hardcoded literal would drift from the metadata; this catches that.
    assert streamcatcher.__version__ == version("streamcatcher")


def test_version_matches_pyproject():
    declared = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())["project"]["version"]
    assert streamcatcher.__version__ == declared
