"""branch-guard 核心：配置、版本解析与 bump 规则。"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_CONFIG_NAMES = ("branch-guard.json", ".branch-guard.json")


def _global_config_path() -> Path | None:
    try:
        return Path.home() / ".branch-guard" / "config.json"
    except RuntimeError:
        return None


class BranchGuardError(Exception):
    """可预期的业务错误：输出中文原因，退出码 2。"""


SEMVER_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?P<pre>[-+][0-9A-Za-z.-]+)?$"
)
BUMP_LEVELS = ("major", "minor", "patch")


@dataclass(frozen=True)
class Version:
    """语义化版本；raw 保留原始写法（如 2.4.0-SNAPSHOT）。"""

    raw: str
    major: int
    minor: int
    patch: int
    pre: str = ""

    @property
    def core(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    @property
    def core_tuple(self) -> tuple[int, int, int]:
        return (self.major, self.minor, self.patch)

    @classmethod
    def parse(cls, raw: str) -> "Version":
        text = (raw or "").strip()
        match = SEMVER_RE.match(text)
        if not match:
            raise BranchGuardError(
                f"无法解析版本号: {raw!r}，期望形如 2.4.0 或 2.4.0-SNAPSHOT"
            )
        return cls(
            raw=text,
            major=int(match.group("major")),
            minor=int(match.group("minor")),
            patch=int(match.group("patch")),
            pre=match.group("pre") or "",
        )

    def bump(self, level: str, keep_pre: bool = True) -> "Version":
        if level not in BUMP_LEVELS:
            raise BranchGuardError(f"不支持的升级级别: {level}，可选 {'/'.join(BUMP_LEVELS)}")
        if level == "major":
            core = (self.major + 1, 0, 0)
        elif level == "minor":
            core = (self.major, self.minor + 1, 0)
        else:
            core = (self.major, self.minor, self.patch + 1)
        pre = self.pre if keep_pre else ""
        return Version(f"{core[0]}.{core[1]}.{core[2]}{pre}", *core, pre=pre)

    def same_core(self, other: "Version") -> bool:
        return self.core_tuple == other.core_tuple

    def __str__(self) -> str:
        return self.raw


def parse_version_or_none(raw: str | None) -> Version | None:
    if not raw:
        return None
    try:
        return Version.parse(raw)
    except BranchGuardError:
        return None


def semantic_gt(a: Version, b: Version) -> bool:
    return a.core_tuple > b.core_tuple


@dataclass
class Config:
    """仓库/全局配置；未知字段仅提示，不中断。"""

    baseline: str = "origin/master"
    remote: str = "origin"
    branch_kind: str = "feature"
    version_source: str = "auto"
    release_note: str = "release-note.txt"
    release_note_line: int = 2
    release_note_pattern: str = r"^v(?P<version>[^()\s]+)\((?P<date>[^)]*)\)\s*$"
    placeholder: str = "TBD"
    bump: str = "minor"
    fetch: bool = True
    allow_dirty: bool = False
    modules: list[str] = field(default_factory=list)
    artifact_name: str = ""
    multi_repo: list[str] = field(default_factory=list)
    dry_run: bool = False
    json: bool = False

    @classmethod
    def load(cls, repo: Path | None = None) -> "Config":
        cfg = cls()
        paths: list[Path] = []
        global_path = _global_config_path()
        if global_path is not None:
            paths.append(global_path)
        if repo is not None:
            for name in REPO_CONFIG_NAMES:
                candidate = repo / name
                if candidate.exists():
                    paths.append(candidate)
                    break
        for path in paths:
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError) as exc:
                raise BranchGuardError(f"配置文件读取失败 {path}: {exc}") from exc
            if not isinstance(data, dict):
                raise BranchGuardError(f"配置文件必须是 JSON 对象: {path}")
            cfg = cfg.merge(data, str(path))
        return cfg

    def merge(self, data: dict[str, Any], source: str) -> "Config":
        allowed = {
            "baseline", "remote", "branchKind", "versionSource", "releaseNote",
            "releaseNoteLine", "releaseNotePattern", "placeholder", "bump",
            "fetch", "allowDirty", "modules", "artifactName", "multiRepo",
        }
        mapping = {
            "baseline": "baseline", "remote": "remote", "branchKind": "branch_kind",
            "versionSource": "version_source", "releaseNote": "release_note",
            "releaseNoteLine": "release_note_line", "releaseNotePattern": "release_note_pattern",
            "placeholder": "placeholder", "bump": "bump", "fetch": "fetch",
            "allowDirty": "allow_dirty", "modules": "modules",
            "artifactName": "artifact_name", "multiRepo": "multi_repo",
        }
        unknown = [key for key in data if key not in allowed]
        if unknown:
            raise BranchGuardError(f"配置文件 {source} 含未知字段: {', '.join(unknown)}")
        for key, attr in mapping.items():
            if key in data:
                setattr(self, attr, data[key])
        if self.bump not in BUMP_LEVELS:
            raise BranchGuardError(f"bump 配置非法: {self.bump}")
        if self.version_source not in ("auto", "pom", "release-note", "version-txt", "package-json"):
            raise BranchGuardError(f"versionSource 配置非法: {self.version_source}")
        return self
