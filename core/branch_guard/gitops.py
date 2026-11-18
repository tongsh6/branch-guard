"""Git 操作封装。"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .core import BranchGuardError


class GitError(BranchGuardError):
    pass


@dataclass
class BranchRef:
    ref: str
    sha: str
    date: str
    author: str


def run(repo: Path, args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    cmd = ["git", *args]
    try:
        proc = subprocess.run(
            cmd, cwd=str(repo), capture_output=True, encoding="utf-8",
            errors="replace", timeout=120,
        )
    except FileNotFoundError as exc:
        raise GitError("找不到 git 命令，请确认已安装并在 PATH 中") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"git 命令超时: {' '.join(cmd)}") from exc
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise GitError(f"git 命令失败: {' '.join(cmd)}\n{detail}")
    return proc


def text(repo: Path, args: list[str], check: bool = True) -> str:
    return run(repo, args, check=check).stdout.strip()


def assert_repo(repo: Path) -> None:
    if not (repo / ".git").exists():
        top = run(repo, ["rev-parse", "--show-toplevel"], check=False)
        if top.returncode != 0:
            raise BranchGuardError(f"不是 git 仓库: {repo}")


def fetch(repo: Path, remote: str) -> None:
    proc = run(repo, ["fetch", "--prune", remote], check=False)
    if proc.returncode != 0:
        raise GitError(f"git fetch {remote} 失败: {(proc.stderr or proc.stdout).strip()}")


def rev_parse(repo: Path, ref: str) -> str:
    return text(repo, ["rev-parse", ref])


def current_branch(repo: Path) -> str:
    return text(repo, ["rev-parse", "--abbrev-ref", "HEAD"])


def status_porcelain(repo: Path) -> str:
    return text(repo, ["status", "--porcelain"])


def remote_branches(repo: Path, remote: str) -> list[BranchRef]:
    fmt = "%(refname:short)|%(objectname)|%(committerdate:iso8601)|%(authorname)"
    out = text(repo, ["for-each-ref", f"refs/remotes/{remote}", f"--format={fmt}"])
    result: list[BranchRef] = []
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) < 4:
            continue
        ref, sha, date, author = parts[0], parts[1], parts[2], "|".join(parts[3:])
        if ref.endswith("/HEAD"):
            continue
        result.append(BranchRef(ref, sha, date, author))
    return result


def local_branches(repo: Path) -> list[BranchRef]:
    fmt = "%(refname:short)|%(objectname)|%(committerdate:iso8601)|%(authorname)"
    out = text(repo, ["for-each-ref", "refs/heads", f"--format={fmt}"])
    result: list[BranchRef] = []
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) < 4:
            continue
        result.append(BranchRef(parts[0], parts[1], parts[2], "|".join(parts[3:])))
    return result


def merged_refs(repo: Path, baseline: str) -> set[str]:
    proc = run(repo, ["branch", "-r", "--merged", baseline,
                      "--format=%(refname:short)"], check=False)
    if proc.returncode != 0:
        return set()
    return {line.strip() for line in proc.stdout.splitlines() if line.strip()}


def is_ancestor(repo: Path, sha: str, baseline: str) -> bool:
    proc = run(repo, ["merge-base", "--is-ancestor", sha, baseline], check=False)
    return proc.returncode == 0


def read_blob(repo: Path, ref: str, path: str) -> str:
    proc = run(repo, ["show", f"{ref}:{path}"], check=False)
    if proc.returncode != 0:
        raise GitError(f"{ref}:{path} 不存在")
    return proc.stdout


def worktree_add(repo: Path, branch: str, path: Path, start: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    proc = run(repo, ["worktree", "add", "-b", branch, str(path), start], check=False)
    if proc.returncode != 0:
        raise GitError(f"创建 worktree 失败 {path}: {(proc.stderr or proc.stdout).strip()}")


def create_branch(repo: Path, name: str, start: str) -> None:
    proc = run(repo, ["switch", "-c", name, start], check=False)
    if proc.returncode != 0:
        raise GitError(f"创建分支失败 {name}（起点 {start}）: {(proc.stderr or proc.stdout).strip()}")


def branch_exists(repo: Path, name: str) -> bool:
    proc = run(repo, ["rev-parse", "--verify", f"refs/heads/{name}"], check=False)
    return proc.returncode == 0


def diff_stat(repo: Path) -> str:
    return text(repo, ["diff", "--stat"])


def latest_semver_tag(repo: Path) -> str:
    out = text(repo, ["tag", "--list"], check=False)
    from .core import Version, BranchGuardError as _Err
    best = None
    best_raw = ""
    for raw in out.splitlines():
        candidate = raw.strip()
        for prefix in ("v", "V"):
            if candidate.startswith(prefix):
                candidate = candidate[1:]
                break
        try:
            ver = Version.parse(candidate)
        except _Err:
            continue
        if best is None or ver.core_tuple > best.core_tuple:
            best, best_raw = ver, raw.strip()
    return best_raw
