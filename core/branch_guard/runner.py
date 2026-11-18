"""new-branch / check / scan 的流程编排。"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import gitops
from .core import BUMP_LEVELS, BranchGuardError, Config, Version
from .occupancy import ScanResult, scan
from .versionfile import read_project_version, write_project_version


@dataclass
class Options:
    name: str = ""
    repos: list[Path] = field(default_factory=list)
    bump: str | None = None
    explicit_version: str | None = None
    baseline: str | None = None
    do_fetch: bool = True
    dry_run: bool = False
    allow_dirty: bool = False
    allow_old: bool = False
    branch_kind: str = "feature"
    placeholder: str | None = None
    date: str = ""
    update_release_note: bool = True
    include_local: bool = True
    continue_on_error: bool = False
    worktree: bool = False
    worktree_dir: str | None = None


@dataclass
class RepoPlan:
    repo: Path
    cfg: Config
    baseline: str = ""
    baseline_sha: str = ""
    current_version: Version | None = None
    current_source: str = ""
    target_version: Version | None = None
    scan_result: ScanResult | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class RepoResult:
    repo: Path
    status: str                      # ok | dry-run | failed | skipped
    baseline: str = ""
    baseline_sha: str = ""
    current_version: str = ""
    current_source: str = ""
    target_version: str = ""
    branch: str = ""
    worktree_path: str = ""
    changed_files: list[str] = field(default_factory=list)
    diff_stat: str = ""
    conflicts: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "repo": str(self.repo),
            "status": self.status,
            "baseline": self.baseline,
            "baseline_sha": self.baseline_sha,
            "current_version": self.current_version,
            "current_source": self.current_source,
            "target_version": self.target_version,
            "branch": self.branch,
            "worktree_path": self.worktree_path,
            "changed_files": self.changed_files,
            "diff_stat": self.diff_stat,
            "conflicts": self.conflicts,
            "skipped": self.skipped,
            "errors": self.errors,
            "warnings": self.warnings,
        }


def _resolve_baseline(repo: Path, cfg: Config, override: str | None) -> str:
    candidate = override or cfg.baseline
    proc = gitops.run(repo, ["rev-parse", "--verify", candidate], check=False)
    if proc.returncode == 0:
        return candidate
    for fallback in ("origin/master", "origin/main", "master", "main"):
        if fallback == candidate:
            continue
        check = gitops.run(repo, ["rev-parse", "--verify", fallback], check=False)
        if check.returncode == 0:
            return fallback
    raise BranchGuardError(f"基线分支不存在: {candidate}（可尝试 --baseline origin/master）")


def _build_plan(repo: Path, opts: Options) -> RepoPlan:
    cfg = Config.load(repo)
    if opts.baseline:
        cfg.baseline = opts.baseline
    if opts.placeholder is not None:
        cfg.placeholder = opts.placeholder
    plan = RepoPlan(repo=repo, cfg=cfg)
    if not opts.allow_dirty and not opts.worktree:
        dirty = gitops.status_porcelain(repo)
        if dirty:
            plan.errors.append("工作区不干净，请先提交或暂存；确认无影响可加 --allow-dirty")
            return plan
    plan.baseline = _resolve_baseline(repo, cfg, opts.baseline)
    plan.baseline_sha = gitops.rev_parse(repo, plan.baseline)
    current = read_project_version(repo, cfg)
    plan.current_version = current.version
    plan.current_source = f"{current.source} ({current.path})"

    bump = opts.bump or cfg.bump
    if opts.explicit_version:
        target = Version.parse(opts.explicit_version)
    else:
        if bump not in BUMP_LEVELS:
            plan.errors.append(f"--bump 非法: {bump}")
            return plan
        target = current.version.bump(bump)
    plan.target_version = target

    if target.same_core(current.version) and not opts.explicit_version:
        plan.errors.append(
            f"目标版本 {target} 与当前版本 {current.version} 核心相同，没有 bump；"
            "请确认 --bump 或 --version"
        )
        return plan

    try:
        plan.scan_result = scan(
            repo, cfg, plan.baseline, opts.do_fetch, target,
            include_local=opts.include_local,
        )
    except (BranchGuardError, gitops.GitError) as exc:
        plan.errors.append(f"扫描分支版本失败: {exc}")
        return plan

    sr = plan.scan_result
    if sr.latest_tag and not opts.allow_old:
        from .core import parse_version_or_none
        tag_version = parse_version_or_none(
            sr.latest_tag[1:] if sr.latest_tag[:1] in ("v", "V") else sr.latest_tag
        )
        if tag_version is not None and target.core_tuple <= tag_version.core_tuple:
            plan.errors.append(
                f"目标版本 {target} 不高于最新发布 tag {sr.latest_tag}；"
                "请确认版本推导，或加 --allow-old 跳过该检查"
            )
    if sr.conflicts:
        plan.errors.append(
            f"目标版本 {target} 已被 {len(sr.conflicts)} 个未合并分支占用"
        )
    return plan


def check(opts: Options) -> list[RepoResult]:
    results: list[RepoResult] = []
    for repo in opts.repos:
        try:
            plan = _build_plan(repo, opts)
            result = _plan_to_result(plan)
        except BranchGuardError as exc:
            result = RepoResult(repo=repo, status="failed", errors=[str(exc)])
        results.append(result)
    return results


def new_branch(opts: Options) -> list[RepoResult]:
    if not opts.repos:
        raise BranchGuardError("未指定仓库：使用 --repo 或当前目录")
    if not opts.name:
        raise BranchGuardError("缺少分支名")
    plans = []
    for repo in opts.repos:
        try:
            plans.append(_build_plan(repo, opts))
        except BranchGuardError as exc:
            plan = RepoPlan(repo=repo, cfg=Config.load(repo) if repo.exists() else Config())
            plan.errors.append(str(exc))
            plans.append(plan)

    results: list[RepoResult] = []
    has_error = any(p.errors for p in plans)
    if has_error:
        for plan in plans:
            results.append(_plan_to_result(plan, status="failed"))
        return results

    for plan in plans:
        result = _plan_to_result(plan, status="dry-run" if opts.dry_run else "ok")
        if opts.dry_run:
            results.append(result)
            continue
        try:
            _execute(plan, opts, result)
        except (BranchGuardError, gitops.GitError) as exc:
            result.status = "failed"
            result.errors.append(str(exc))
        results.append(result)
        if result.status == "failed" and not opts.continue_on_error:
            break
    return results


def _worktree_path(repo: Path, opts: Options) -> Path:
    slug = re.sub(r"[\\/:*?\"<>|\s]+", "-", opts.name).strip("-") or "branch"
    if opts.worktree_dir:
        return Path(opts.worktree_dir).expanduser().resolve() / slug
    env_root = os.environ.get("BRANCH_GUARD_WORKTREE_ROOT")
    base = Path(env_root).expanduser() if env_root else Path.home() / ".branch-guard" / "worktrees"
    return base / repo.name / slug


def _execute(plan: RepoPlan, opts: Options, result: RepoResult) -> None:
    repo, cfg, target = plan.repo, plan.cfg, plan.target_version
    assert target is not None
    if gitops.branch_exists(repo, opts.name):
        raise BranchGuardError(f"本地分支已存在: {opts.name}")
    if opts.worktree:
        wt_path = _worktree_path(repo, opts)
        gitops.worktree_add(repo, opts.name, wt_path, plan.baseline)
        result.branch = opts.name
        result.worktree_path = str(wt_path)
        changed = write_project_version(
            wt_path, cfg, target,
            update_release_note=opts.update_release_note,
            date=opts.date,
        )
        result.changed_files = changed
        readback = read_project_version(wt_path, cfg)
        if not readback.version.same_core(target):
            raise BranchGuardError(
                f"写入后校验失败：worktree 文件版本为 {readback.version}，期望 {target}"
            )
        result.diff_stat = gitops.diff_stat(wt_path)
        return
    gitops.create_branch(repo, opts.name, plan.baseline)
    result.branch = opts.name
    changed = write_project_version(
        repo, cfg, target,
        update_release_note=opts.update_release_note,
        date=opts.date,
    )
    result.changed_files = changed
    readback = read_project_version(repo, cfg)
    if not readback.version.same_core(target):
        raise BranchGuardError(
            f"写入后校验失败：文件版本为 {readback.version}，期望 {target}"
        )
    result.diff_stat = gitops.diff_stat(repo)


def _plan_to_result(plan: RepoPlan, status: str = "") -> RepoResult:
    if not status:
        status = "failed" if plan.errors else "ok"
    result = RepoResult(repo=plan.repo, status=status)
    result.baseline = plan.baseline
    result.baseline_sha = plan.baseline_sha[:10] if plan.baseline_sha else ""
    if plan.current_version:
        result.current_version = plan.current_version.raw
    result.current_source = plan.current_source
    if plan.target_version:
        result.target_version = plan.target_version.raw
    result.errors = list(plan.errors)
    result.warnings = list(plan.warnings)
    if plan.scan_result:
        result.conflicts = [
            {"branch": c.branch, "version": c.version.raw, "date": c.date,
             "author": c.author, "sha": c.sha[:10]}
            for c in plan.scan_result.conflicts
        ]
        result.skipped = [
            {"branch": b, "reason": r} for b, r in plan.scan_result.skipped[:50]
        ]
    return result


def scan_only(opts: Options) -> list[dict]:
    out = []
    for repo in opts.repos:
        cfg = Config.load(repo)
        if opts.baseline:
            cfg.baseline = opts.baseline
        try:
            baseline = _resolve_baseline(repo, cfg, opts.baseline)
            sr = scan(repo, cfg, baseline, opts.do_fetch, None,
                      include_local=opts.include_local)
            out.append({
                "repo": str(repo),
                "baseline": baseline,
                "baseline_sha": sr.baseline_sha[:10],
                "latest_tag": sr.latest_tag,
                "branches": [
                    {"branch": b.branch, "version": b.version.raw, "sha": b.sha[:10],
                     "date": b.date, "author": b.author, "source": b.source}
                    for b in sr.branches
                ],
                "skipped": [{"branch": b, "reason": r} for b, r in sr.skipped[:50]],
                "errors": [],
            })
        except (BranchGuardError, gitops.GitError) as exc:
            out.append({"repo": str(repo), "errors": [str(exc)]})
    return out
