"""占用扫描：收集未合并分支的项目版本。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import gitops
from .core import BranchGuardError, Config, Version
from .versionfile import read_project_version


@dataclass
class BranchVersion:
    branch: str
    sha: str
    date: str
    author: str
    version: Version
    source: str


@dataclass
class ScanResult:
    baseline: str = ""
    baseline_sha: str = ""
    latest_tag: str = ""
    branches: list[BranchVersion] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    conflicts: list[BranchVersion] = field(default_factory=list)


def scan(repo: Path, cfg: Config, baseline: str, do_fetch: bool,
         target: Version | None = None, include_local: bool = True) -> ScanResult:
    if do_fetch:
        gitops.fetch(repo, cfg.remote)
    result = ScanResult(baseline=baseline, baseline_sha=gitops.rev_parse(repo, baseline))
    result.latest_tag = gitops.latest_semver_tag(repo)

    merged = gitops.merged_refs(repo, baseline)
    refs: list[gitops.BranchRef] = gitops.remote_branches(repo, cfg.remote)
    if include_local:
        for item in gitops.local_branches(repo):
            item.ref = item.ref  # 本地分支名
            refs.append(item)

    seen: set[str] = set()
    seen_sha: set[str] = set()
    current = gitops.current_branch(repo)
    for item in refs:
        if item.ref in seen or item.ref in merged:
            continue
        seen.add(item.ref)
        if item.sha in seen_sha:
            continue
        if item.ref in (baseline, "origin/HEAD", "HEAD", current):
            continue
        if item.sha == result.baseline_sha:
            continue
        if gitops.is_ancestor(repo, item.sha, result.baseline_sha):
            continue
        try:
            read = read_project_version(
                repo, cfg, ref=item.ref, read_at_ref=lambda r, p: gitops.read_blob(repo, r, p)
            )
        except (BranchGuardError, gitops.GitError) as exc:
            result.skipped.append((item.ref, str(exc).splitlines()[0]))
            continue
        seen_sha.add(item.sha)
        result.branches.append(
            BranchVersion(item.ref, item.sha, item.date, item.author, read.version, read.source)
        )
        if target is not None and read.version.same_core(target):
            result.conflicts.append(result.branches[-1])
    return result
