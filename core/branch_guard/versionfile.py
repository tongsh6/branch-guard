"""版本源适配：pom、release-note、version.txt、package.json 的读取与写入。"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .core import BranchGuardError, Config, Version

PACKAGE_VERSION_RE = re.compile(r'("version"\s*:\s*")([^"]*)(")')
TAG_RE = re.compile(r"<!--.*?-->|<!\[CDATA\[.*?\]\]>|<[^>]+>", re.S)
DOLLAR_BRACE = "$" + "{"


@dataclass
class VersionRead:
    version: Version
    source: str          # pom | release-note | version-txt | package-json
    path: str            # 相对仓库根的路径
    detail: str = ""


def detect_source(repo: Path, cfg: Config) -> str:
    if cfg.version_source != "auto":
        return cfg.version_source
    if (repo / "pom.xml").exists():
        return "pom"
    note = repo / cfg.release_note
    if note.exists() and read_release_note_version(_read_text(note), cfg) is not None:
        return "release-note"
    if (repo / "version.txt").exists():
        return "version-txt"
    if (repo / "package.json").exists():
        return "package-json"
    raise BranchGuardError(
        f"仓库 {repo} 找不到可识别的版本源（pom.xml / {cfg.release_note} / version.txt / package.json）"
    )


def read_project_version(repo: Path, cfg: Config, ref: str | None = None,
                         read_at_ref=None) -> VersionRead:
    """读取项目版本；ref 非空时通过回调 read_at_ref(ref, path) 读该提交的文件。"""
    source = detect_source(repo, cfg)
    if source == "pom":
        text = _read(repo, "pom.xml", ref, read_at_ref)
        version, detail = _parse_pom_version(text, "pom.xml")
        return VersionRead(version, "pom", "pom.xml", detail)
    if source == "release-note":
        path = cfg.release_note
        text = _read(repo, path, ref, read_at_ref)
        version = read_release_note_version(text, cfg)
        if version is None:
            raise BranchGuardError(f"{path} 第 {cfg.release_note_line} 行不是 v版本(日期) 格式")
        return VersionRead(version, "release-note", path, f"第 {cfg.release_note_line} 行")
    if source == "version-txt":
        text = _read(repo, "version.txt", ref, read_at_ref)
        return VersionRead(Version.parse(text.strip()), "version-txt", "version.txt")
    if source == "package-json":
        text = _read(repo, "package.json", ref, read_at_ref)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise BranchGuardError(f"package.json 解析失败: {exc}") from exc
        version = data.get("version")
        if not version:
            raise BranchGuardError("package.json 缺少 version 字段")
        return VersionRead(Version.parse(str(version)), "package-json", "package.json")
    raise BranchGuardError(f"未知版本源: {source}")


def write_project_version(repo: Path, cfg: Config, target: Version,
                          update_release_note: bool = True,
                          date: str = "") -> list[str]:
    """写入目标版本，返回变更文件列表。失败时尽量保持文件原样。"""
    source = detect_source(repo, cfg)
    changed: list[str] = []
    if source == "pom":
        path = repo / "pom.xml"
        original = _read_text(path)
        updated, _detail = _update_pom_text(original, target)
        if updated != original:
            _write_text(path, updated, original)
            changed.append("pom.xml")
    elif source == "release-note":
        path = repo / cfg.release_note
        original = _read_text(path)
        updated = insert_release_note(original, target, date, cfg)
        _write_text(path, updated, original)
        changed.append(cfg.release_note)
        return changed
    elif source == "version-txt":
        path = repo / "version.txt"
        original = _read_text(path)
        _write_text(path, target.raw + "\n", original)
        changed.append("version.txt")
    elif source == "package-json":
        path = repo / "package.json"
        original = _read_text(path)
        updated, count = PACKAGE_VERSION_RE.subn(
            lambda m: m.group(1) + target.raw + m.group(3), original, count=1
        )
        if count != 1:
            raise BranchGuardError("package.json 中未找到可替换的 version 字段")
        _write_text(path, updated, original)
        changed.append("package.json")

    if update_release_note and source != "release-note":
        note_path = repo / cfg.release_note
        if note_path.exists():
            original = _read_text(note_path)
            updated = insert_release_note(original, target, date, cfg)
            _write_text(note_path, updated, original)
            changed.append(cfg.release_note)
    return changed


def read_release_note_version(text: str, cfg: Config) -> Version | None:
    lines = text.splitlines()
    pattern = re.compile(cfg.release_note_pattern)
    candidates: list[str] = []
    if 1 <= cfg.release_note_line <= len(lines):
        candidates.append(lines[cfg.release_note_line - 1])
    for line in lines[:20]:
        if line not in candidates:
            candidates.append(line)
    for line in candidates:
        match = pattern.match(line.strip())
        if match:
            try:
                return Version.parse(match.group("version"))
            except BranchGuardError:
                continue
    return None


def insert_release_note(text: str, target: Version, date: str, cfg: Config) -> str:
    """在文件顶部插入新版本占位块，保持最新版本在第一/第二行。"""
    if not date:
        from datetime import date as _date
        date = _date.today().isoformat()
    lines = text.splitlines()
    sep = ""
    if lines and re.fullmatch(r"[=\-*]{6,}", lines[0].strip()):
        sep = lines[0]
    title = f"v{target.raw}({date})"
    block_lines = []
    if sep:
        block_lines.append(sep)
    block_lines.append(title)
    if sep:
        block_lines.append(sep)
    block_lines.extend(["【新增功能】", cfg.placeholder, ""])
    return "\n".join(block_lines) + "\n" + text


def _read(repo: Path, rel: str, ref: str | None, read_at_ref) -> str:
    if ref is None:
        return _read_text(repo / rel)
    if read_at_ref is None:
        raise BranchGuardError("内部错误：缺少 read_at_ref 回调")
    return read_at_ref(ref, rel)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise BranchGuardError(f"文件编码不是 UTF-8: {path}: {exc}") from exc
    except OSError as exc:
        raise BranchGuardError(f"读取失败 {path}: {exc}") from exc


def _write_text(path: Path, new: str, original: str) -> None:
    try:
        path.write_text(new, encoding="utf-8", newline="")
    except OSError as exc:
        try:
            path.write_text(original, encoding="utf-8")
        except OSError:
            pass
        raise BranchGuardError(f"写入失败 {path}: {exc}") from exc


def _parse_pom_version(text: str, path: str) -> tuple[Version, str]:
    root_version = _project_child_text(text, "version")
    props = _properties(text)
    if root_version and not root_version.startswith(DOLLAR_BRACE):
        return Version.parse(root_version), f"{path} 根 project/version"
    revision = (props.get("revision") or "").strip()
    if revision:
        changelist = (props.get("changelist") or "").strip()
        return (Version.parse(revision + changelist),
                f"{path} revision{revision} + changelist{changelist or '(空)'}")
    if root_version:
        raise BranchGuardError(
            f"{path} 的版本是属性表达式 {root_version}，未找到 revision 属性；"
            "请在 branch-guard.json 显式配置 versionSource 或补充 revision"
        )
    raise BranchGuardError(f"{path} 未找到根 project/version 或 revision 属性")


def _update_pom_text(text: str, target: Version) -> tuple[str, str]:
    root_version = _project_child_text(text, "version")
    props = _properties(text)
    revision = (props.get("revision") or "").strip()
    if root_version and not root_version.startswith(DOLLAR_BRACE):
        return _replace_project_child_text(text, "version", target.raw), "替换根 project/version"
    if revision:
        return _replace_property_text(text, "revision", target.core), \
            "替换 properties/revision，changelist 保持不变"
    raise BranchGuardError("pom.xml 没有可写的根 version 或 revision")


def _tokenize(text: str):
    """产出 (kind, name, start, end)；kind: open|close|selfclose。"""
    for match in TAG_RE.finditer(text):
        raw = match.group(0)
        if raw.startswith("<!--") or raw.startswith("<![CDATA["):
            continue
        body = raw[1:-1].strip()
        if body.startswith("?") or body.startswith("!"):
            continue
        kind = "open"
        if body.startswith("/"):
            kind = "close"
            body = body[1:].strip()
        selfclose = body.endswith("/")
        if selfclose:
            body = body[:-1].strip()
        name_match = re.match(r"[A-Za-z_][\w:.-]*", body)
        if not name_match:
            continue
        name = name_match.group(0)
        if selfclose:
            kind = "selfclose"
        yield kind, name, match.start(), match.end()


def _read_project_child(text: str, tag: str) -> str | None:
    stack: list[str] = []
    for kind, name, start, end in _tokenize(text):
        if kind == "close":
            if stack:
                stack.pop()
            continue
        if kind == "selfclose":
            continue
        if len(stack) == 1 and stack[0] == "project" and name == tag:
            close = text.find(f"</{name}>", end)
            if close == -1:
                return None
            return text[end:close].strip()
        stack.append(name)
    return None


def _project_child_text(text: str, tag: str) -> str | None:
    return _read_project_child(text, tag)


def _properties(text: str) -> dict[str, str]:
    stack: list[str] = []
    props: dict[str, str] = {}
    for kind, name, start, end in _tokenize(text):
        if kind == "close":
            if stack:
                stack.pop()
            continue
        if kind == "selfclose":
            continue
        if len(stack) == 2 and stack[0] == "project" and stack[1] == "properties":
            close = text.find(f"</{name}>", end)
            if close != -1:
                props[name] = text[end:close]
        stack.append(name)
    return props


def _replace_project_child_text(text: str, tag: str, value: str) -> str:
    stack: list[str] = []
    for kind, name, start, end in _tokenize(text):
        if kind == "close":
            if stack:
                stack.pop()
            continue
        if kind == "selfclose":
            continue
        if len(stack) == 1 and stack[0] == "project" and name == tag:
            close = text.find(f"</{name}>", end)
            if close == -1:
                break
            return text[:end] + value + text[close:]
        stack.append(name)
    raise BranchGuardError(f"pom.xml 中未找到根 project/{tag} 元素")


def _replace_property_text(text: str, prop: str, value: str) -> str:
    stack: list[str] = []
    for kind, name, start, end in _tokenize(text):
        if kind == "close":
            if stack:
                stack.pop()
            continue
        if kind == "selfclose":
            continue
        if len(stack) == 2 and stack[0] == "project" and stack[1] == "properties" and name == prop:
            close = text.find(f"</{name}>", end)
            if close == -1:
                break
            return text[:end] + value + text[close:]
        stack.append(name)
    raise BranchGuardError(f"pom.xml 中未找到 properties/{prop} 元素")
