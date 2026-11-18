"""命令行入口。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .core import BranchGuardError, Config
from .runner import Options, RepoResult, check, new_branch, scan_only


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("name", nargs="?", help="新分支名，例如 feature/20261118-xxx")
    parser.add_argument("--repo", action="append", metavar="PATH",
                        help="仓库路径，可重复；默认当前目录或配置中的 multiRepo")
    parser.add_argument("--baseline", help="基线分支，默认 origin/master")
    parser.add_argument("--bump", choices=["major", "minor", "patch"],
                        help="版本升级级别，默认按配置（minor）")
    parser.add_argument("--version", dest="explicit_version", help="显式目标版本")
    parser.add_argument("--no-fetch", action="store_true", help="不执行 git fetch")
    parser.add_argument("--allow-dirty", action="store_true", help="允许工作区有未提交改动")
    parser.add_argument("--allow-old", action="store_true", help="允许目标版本不高于最新 tag")
    parser.add_argument("--no-release-note", action="store_true", help="不改 release-note.txt")
    parser.add_argument("--placeholder", help="release-note 占位内容，默认 TBD")
    parser.add_argument("--date", help="release-note 日期，默认今天")
    parser.add_argument("--no-include-local", action="store_true", help="只扫描远端分支")
    parser.add_argument("--json", action="store_true", help="输出 JSON")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="new-branch",
        description="创建分支前检查版本号是否被未合并分支占用，并完成版本预升级。",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_new = sub.add_parser("new-branch", help="检查 + 创建分支 + 预升级版本")
    _common(p_new)
    p_new.add_argument("--dry-run", action="store_true", help="只检查，不创建分支、不写文件")
    p_new.add_argument("--continue-on-error", action="store_true")
    p_new.add_argument("--worktree", action="store_true", help="创建分支的同时创建 worktree")
    p_new.add_argument("--worktree-dir", help="worktree 根目录，默认 ~/.branch-guard/worktrees/<repo>")

    p_check = sub.add_parser("check", help="只检查，不写任何文件")
    _common(p_check)
    p_check.add_argument("--dry-run", action="store_true", help="兼容参数；check 本身不写文件")

    p_scan = sub.add_parser("scan", help="输出未合并分支的版本占用表")
    _common(p_scan)
    return parser


def _resolve_repos(args) -> list[Path]:
    if args.repo:
        return [Path(item).expanduser().resolve() for item in args.repo]
    cwd = Path.cwd()
    cfg = Config.load(cwd)
    if cfg.multi_repo:
        base = cwd
        for name in ("branch-guard.json", ".branch-guard.json"):
            candidate = cwd / name
            if candidate.exists():
                base = candidate.parent
                break
        repos = []
        for item in cfg.multi_repo:
            path = Path(item)
            repos.append((path if path.is_absolute() else base / path).resolve())
        return repos
    return [cwd]


def _options(args) -> Options:
    return Options(
        name=args.name or "",
        repos=_resolve_repos(args),
        bump=args.bump,
        explicit_version=args.explicit_version,
        baseline=args.baseline,
        do_fetch=not args.no_fetch,
        dry_run=getattr(args, "dry_run", False),
        allow_dirty=args.allow_dirty,
        allow_old=args.allow_old,
        placeholder=args.placeholder,
        date=args.date or "",
        update_release_note=not args.no_release_note,
        include_local=not args.no_include_local,
        continue_on_error=getattr(args, "continue_on_error", False),
        worktree=getattr(args, "worktree", False),
        worktree_dir=getattr(args, "worktree_dir", None),
    )


def _print_result(result: RepoResult, index: int, total: int) -> None:
    head = f"[{index}/{total}] {result.repo}"
    print(head)
    if result.baseline:
        print(f"  基线：{result.baseline} @ {result.baseline_sha}")
    if result.current_version:
        print(f"  当前版本：{result.current_version}（{result.current_source}）")
    if result.target_version:
        print(f"  目标版本：{result.target_version}")
    if result.branch:
        print(f"  分支：{result.branch}")
    if result.status == "dry-run":
        print("  检查通过（dry-run，未执行任何写操作）")
    if result.status == "ok":
        print("  检查通过，已创建分支并写入版本")
    if result.conflicts:
        print(f"  ✗ 目标版本已被占用：")
        for item in result.conflicts:
            print(f"    - {item['branch']}（{item['version']}，{item['date']}，{item['author']}）")
    if result.changed_files:
        print(f"  变更文件：{', '.join(result.changed_files)}")
    if result.diff_stat:
        print(result.diff_stat)
    for warning in result.warnings:
        print(f"  ! {warning}")
    for error in result.errors:
        print(f"  ✗ {error}")
    if result.status == "failed" and not result.errors:
        print("  ✗ 检查未通过")
    print()


def _print_scan(report: dict) -> None:
    print(f"仓库：{report['repo']}")
    if report.get("errors"):
        for error in report["errors"]:
            print(f"  ✗ {error}")
        print()
        return
    print(f"  基线：{report['baseline']} @ {report['baseline_sha']}")
    print(f"  最新 tag：{report.get('latest_tag') or '（无）'}")
    branches = report.get("branches", [])
    print(f"  未合并分支：{len(branches)} 个")
    for item in branches:
        print(f"    {item['branch']:<45} {item['version']:<18} {item['date']}  {item['author']}")
    if report.get("skipped"):
        print(f"  跳过：{len(report['skipped'])} 个")
        for item in report["skipped"][:20]:
            print(f"    {item['branch']}（{item['reason']}）")
    print()


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        opts = _options(args)
        if args.command == "scan":
            reports = scan_only(opts)
            if args.json:
                print(json.dumps({"command": "scan", "repos": reports}, ensure_ascii=False, indent=2))
            else:
                for report in reports:
                    _print_scan(report)
            return 0 if not any(r.get("errors") for r in reports) else 2

        if args.command == "check":
            results = check(opts)
            if args.json:
                print(json.dumps({"command": "check", "repos": [r.to_dict() for r in results]},
                                 ensure_ascii=False, indent=2))
            else:
                for index, result in enumerate(results, 1):
                    _print_result(result, index, len(results))
            return 0 if all(not r.errors for r in results) else 2

        results = new_branch(opts)
        if args.json:
            print(json.dumps({"command": "new-branch", "repos": [r.to_dict() for r in results]},
                             ensure_ascii=False, indent=2))
        else:
            for index, result in enumerate(results, 1):
                _print_result(result, index, len(results))
        return 0 if all(r.status in ("ok", "dry-run") for r in results) else 2
    except BranchGuardError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
