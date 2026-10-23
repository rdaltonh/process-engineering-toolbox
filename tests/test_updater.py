"""launcher/updater.py against throwaway git repos (needs git on PATH)."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "launcher"))
import updater  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout


def _commit(repo: Path, name: str, text: str, msg: str) -> None:
    (repo / name).write_text(text)
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", msg)


@pytest.fixture
def repos(tmp_path):
    """(upstream working repo, local clone) sharing a bare origin."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    upstream = tmp_path / "upstream"
    _git(tmp_path, "clone", "-q", str(origin), str(upstream))
    _git(upstream, "checkout", "-q", "-b", "main")
    _commit(upstream, "pyproject.toml", "v1", "initial")
    _git(upstream, "push", "-q", "origin", "main")
    local = tmp_path / "local"
    _git(tmp_path, "clone", "-q", str(origin), str(local))
    return upstream, local


def test_already_up_to_date(repos):
    _, local = repos
    r = updater.pull(local)
    assert r.ok and r.commits == [] and r.message == "Already up to date."


def test_pulls_new_commits_without_deps_change(repos):
    upstream, local = repos
    _commit(upstream, "a.py", "1", "add a")
    _commit(upstream, "b.py", "2", "add b")
    _git(upstream, "push", "-q", "origin", "main")
    r = updater.pull(local)
    assert r.ok and not r.deps_changed
    assert [c.split(" ", 1)[1] for c in r.commits] == ["add b", "add a"]
    assert (local / "b.py").exists()


def test_flags_pyproject_change(repos):
    upstream, local = repos
    _commit(upstream, "pyproject.toml", "v2", "bump deps")
    _git(upstream, "push", "-q", "origin", "main")
    assert updater.pull(local).deps_changed


def test_diverged_history_fails_cleanly(repos):
    upstream, local = repos
    _commit(upstream, "a.py", "upstream", "upstream change")
    _git(upstream, "push", "-q", "origin", "main")
    _commit(local, "c.py", "local", "local change")
    r = updater.pull(local)
    assert not r.ok and r.message


def test_not_a_repo(tmp_path):
    r = updater.pull(tmp_path)
    assert not r.ok and "Not a git checkout" in r.message
    assert updater.current_version(tmp_path) == "unknown"


def test_current_version(repos):
    _, local = repos
    assert updater.current_version(local) != "unknown"
