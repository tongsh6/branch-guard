#!/usr/bin/env python3
"""Claude Code / Codex PreToolUse hook: 拦截直接创建分支，引导使用 new-branch。"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

PATTERNS = [
    re.compile(r"\bgit\s+switch\b[^\n]*\s(?:-c|--create)\b"),
    re.compile(r"\bgit\s+checkout\b[^\n]*\s(?:-b|-B)\b"),
    re.compile(r"\bgit\s+branch\b\s+(?!-|--)[^\s]+"),
    re.compile(r"\bgit\s+worktree\s+add\b[^\n]*\s(?:-b|--create)\b"),
]
BRANCH_NAME = re.compile(r"(?:-c|--create|-b|-B)\s+([^\s]+)")


def install_root() -> Path:
    home = os.environ.get("BRANCH_GUARD_HOME")
    if home:
        return Path(home).expanduser().resolve()
    # adapters/claude-code/hooks/pre_tool_use.py -> repo root
    return Path(__file__).resolve().parents[3]


def python_command() -> str:
    return os.environ.get("BRANCH_GUARD_PYTHON") or sys.executable


def summarize(stdout: str) -> str:
    try:
        data = json.loads(stdout)
        repo = (data.get("repos") or [{}])[0]
        lines = ["- " + str(item) for item in repo.get("errors", [])]
        for item in (repo.get("conflicts") or [])[:5]:
            lines.append(
                "  - " + str(item.get("branch")) + "（" + str(item.get("version"))
                + "，" + str(item.get("author")) + "，" + str(item.get("date")) + "）"
            )
        return "\n".join(lines) if lines else "版本检查未通过"
    except Exception:
        return "版本检查未通过"


def deny(reason: str) -> int:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }, ensure_ascii=False))
    return 0


def main() -> int:
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return 0
    tool = str(data.get("tool_name") or "")
    if tool.lower() not in ("bash", "shell"):
        return 0
    command = str((data.get("tool_input") or {}).get("command") or "")
    if not command or not any(p.search(command) for p in PATTERNS):
        return 0

    cwd = str(data.get("cwd") or os.getcwd())
    match = BRANCH_NAME.search(command)
    hint = "（疑似分支名：" + match.group(1) + "）" if match else ""
    root = install_root()
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root / "core") + os.pathsep + env.get("PYTHONPATH", "")
    env["PATH"] = env.get("PATH", "") + os.pathsep + str(Path.home() / ".local" / "bin")
    cmd = [
        python_command(), "-m", "branch_guard", "check",
        "--repo", cwd, "--no-fetch", "--allow-dirty", "--bump", "minor", "--json",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, encoding="utf-8",
                              errors="replace", env=env, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return deny(
            "禁止直接创建分支" + hint + "。branch-guard 检查未完成，"
            "请手动执行 new-branch <分支名> --version <确认后的版本>。"
        )
    if proc.returncode == 2:
        return deny(
            "禁止直接创建分支" + hint + "。当前版本检查未通过：\n"
            + summarize(proc.stdout)
            + "\n请改用：new-branch <分支名> --version <负责人确认的版本>（或 --bump minor|patch --worktree）。"
        )
    return deny(
        "禁止直接创建分支" + hint + "。请改用：new-branch <分支名> --version <负责人确认的版本>"
        "（或 --bump minor|patch），由它完成版本占用检查和版本预升级；"
        "直接 git switch -c 不会修改版本号，可能导致 SNAPSHOT 构件被覆盖。"
    )


if __name__ == "__main__":
    sys.exit(main())
