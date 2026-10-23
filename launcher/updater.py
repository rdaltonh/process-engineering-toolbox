"""Self-update for the launcher: fast-forward the repo checkout with git.

Only pulls code. New dependencies are installed by the desktop launcher's
dependency sync on the next start, and code changes apply once the server
restarts, so the UI asks the user to close and reopen the toolbox.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

GIT_TIMEOUT_S = 60
# Keep git from opening a console window when the server runs hidden (Windows).
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass
class UpdateResult:
    ok: bool
    message: str
    commits: list[str] = field(default_factory=list)  # "<hash> <subject>", newest first
    deps_changed: bool = False


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8",
        timeout=GIT_TIMEOUT_S, creationflags=_NO_WINDOW,
        stdin=subprocess.DEVNULL,
    )


def current_version(root: Path) -> str:
    """Short commit hash and date, e.g. '741ce0a (2026-10-22)', or 'unknown'."""
    try:
        out = _git(root, "log", "-1", "--format=%h (%cs)")
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else "unknown"


def pull(root: Path) -> UpdateResult:
    """`git pull --ff-only` and report the commits that came in."""
    try:
        head = _git(root, "rev-parse", "HEAD")
        if head.returncode != 0:
            return UpdateResult(False, f"Not a git checkout: {head.stderr.strip()}")
        old = head.stdout.strip()
        pulled = _git(root, "pull", "--ff-only")
        if pulled.returncode != 0:
            return UpdateResult(False, pulled.stderr.strip() or pulled.stdout.strip() or "git pull failed.")
        new = _git(root, "rev-parse", "HEAD").stdout.strip()
        if new == old:
            return UpdateResult(True, "Already up to date.")
        log = _git(root, "log", "--format=%h %s", f"{old}..{new}").stdout.splitlines()
        changed = _git(root, "diff", "--name-only", old, new).stdout.splitlines()
    except FileNotFoundError:
        return UpdateResult(False, "git was not found on PATH.")
    except subprocess.TimeoutExpired:
        return UpdateResult(False, f"git did not respond within {GIT_TIMEOUT_S} s (network problem?).")
    n = len(log)
    return UpdateResult(
        True, f"Pulled {n} new commit{'s' if n != 1 else ''}.", commits=log,
        deps_changed="pyproject.toml" in changed,
    )
