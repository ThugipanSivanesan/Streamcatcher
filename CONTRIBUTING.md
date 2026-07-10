# Contributing

Thanks for your interest in Streamcatcher! This is an early-stage project built in
small, tested vertical slices. This guide covers the local setup and the workflow
the project follows.

## Prerequisites

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)** for environment and dependency management

## Setup

```console
git clone https://github.com/ThugipanSivanesan/Streamcatcher
cd Streamcatcher
uv sync --extra api          # create the environment, including the optional API extra
pre-commit install           # enable local git hooks
```

`uv sync` reads the locked dependencies from `uv.lock`. Add `--group docs` if you
want to build the documentation locally (see [below](#documentation)).

## Everyday commands

```console
uv run streamcatcher --help          # run the CLI
uv run pytest                        # tests (offline: no network, no credentials)
uv run ruff check .                  # lint
uv run ruff format --check .         # formatting check (drop --check to apply)
pre-commit run --all-files           # run every hook against the whole tree
```

The test suite is fully offline and headless: OpenCV, the window, and the network
are all faked, so `uv run pytest` works anywhere — including CI — without a camera.

## Workflow

- **Branch per change.** Work on a feature branch off `main` (e.g.
  `feat/<slice>` or `docs/<topic>`); never commit directly to `main`.
- **Test-driven.** Add or update tests alongside the code; keep the suite green and
  coverage high (the project sits around 97%).
- **Open a PR.** CI must be green before merge — see [below](#continuous-integration).
  Slices are squash-merged so `main` stays a clean, linear history.
- **Keep secrets out.** Never commit real stream URLs or credentials; the test
  fixtures use placeholders like `changeme` on purpose.

### Coding style

- Ruff enforces lint and formatting (line length 100). Match the surrounding code's
  naming, structure, and comment density.
- Public functions and classes get docstrings — they render into the
  [API reference](https://github.com/ThugipanSivanesan/Streamcatcher) via
  mkdocstrings, so keep them accurate.
- Keep the package **offline-first**: `cv2` and the web stack (`fastapi`,
  `uvicorn`) are imported lazily so importing the package never requires them.

## Continuous integration

Every pull request runs:

- **Lint & test** — `ruff check`, `ruff format --check`, and `pytest`.
- **Secret scan** — [gitleaks](https://github.com/gitleaks/gitleaks) (plus
  GitGuardian as an external check).
- **Dependency vuln scan** — [osv-scanner](https://google.github.io/osv-scanner/)
  against `uv.lock`.
- **Docs build** — `mkdocs build --strict`, so broken links or references fail fast.

## Documentation

The docs are a [mkdocs-material](https://squidfunk.github.io/mkdocs-material/) site
under `docs/`, with an API reference generated from docstrings by
[mkdocstrings](https://mkdocstrings.github.io/).

```console
uv sync --group docs                 # install the docs toolchain
uv run mkdocs serve                  # live-preview at http://127.0.0.1:8000
uv run mkdocs build --strict         # what CI runs; fails on broken refs/links
```

`CHANGELOG.md` and `CONTRIBUTING.md` live at the repo root and are pulled into the
site, so edit them there.

### Publishing

The site deploys to GitHub Pages via the `Docs` workflow
(`.github/workflows/docs.yml`) on pushes to `main` that touch the docs. Enable it
once under **Settings → Pages → Source: GitHub Actions**. You can also publish
manually with `uv run mkdocs gh-deploy`.

## Reporting security issues

Please report vulnerabilities privately via GitHub Security Advisories rather than a
public issue. See the security notes in the
[documentation](https://github.com/ThugipanSivanesan/Streamcatcher).
