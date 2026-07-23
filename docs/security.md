# Security

Streamcatcher handles a genuinely sensitive value — the stream URL — because
RTSP/RTMP URLs routinely embed credentials (`rtsp://user:pass@host/…`). The design
keeps that secret from leaking, and CI guards the repository.

## Stream URLs are secrets

- The URL is stored as a pydantic [`SecretStr`][streamcatcher.config.Settings], so
  it never appears in reprs or tracebacks.
- Only the **credential-stripped** form
  ([`display_url`][streamcatcher.config.Settings.display_url]) is ever logged or
  printed — the host stays visible, the `user:pass` does not.
- A **log-redaction filter** is installed at startup, seeded with the URL's
  embedded username and password, so even an accidental log call can't emit them.
- The [HTTP API](http-api.md) accepts a URL on `POST /session` but **never returns
  it** in any response or error — responses expose only the opaque session id and
  the viewport state.
- **Recording caveat:** `--record --record-mode ffmpeg` passes the URL to an
  `ffmpeg` subprocess, so a credentialed URL is briefly visible in the machine's
  process list (`ps`). The default `opencv` record mode does not spawn a
  subprocess and has no such exposure — prefer it on shared hosts.

## Network posture

- The HTTP server binds `127.0.0.1` by default (localhost only).
- An optional bearer token (`--token` / `STREAMCATCHER_API_TOKEN`) is enforced on
  **every** route when set. With no token, there is no auth — rely on the localhost
  bind, and set a token before exposing the server more widely.
- RTSP is forced over TCP, which is more robust than the default UDP transport for
  high-resolution frames.

## Supply chain & secret scanning

Continuous integration runs on every pull request:

- **[gitleaks](https://github.com/gitleaks/gitleaks)** — scans the diff/history for
  committed secrets.
- **[osv-scanner](https://google.github.io/osv-scanner/)** — checks `uv.lock`
  against the OSV vulnerability database (also re-run weekly to catch
  newly-disclosed CVEs in pinned deps).
- **GitGuardian** — a second, independent secret scan as an external check.

Locally, **pre-commit** hooks scan for secrets and private keys, block large
files, and run `ruff` before anything is committed. See
[Contributing](contributing.md) to enable them.

## Reporting a vulnerability

This is an early-stage personal project. If you find a security issue, please open
a private report via the repository's GitHub Security Advisories rather than a
public issue.
