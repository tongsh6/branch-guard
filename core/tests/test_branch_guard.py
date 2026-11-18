"""branch-guard 单元与集成测试。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from branch_guard.core import Config, Version  # noqa: E402
from branch_guard.versionfile import (  # noqa: E402
    _parse_pom_version, _update_pom_text, insert_release_note,
    read_project_version, write_project_version,
)

PY = sys.executable
DOLLAR = "$"


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True,
                          encoding="utf-8", errors="replace", check=True)


def init_repo(root: Path, name: str = "repo") -> tuple[Path, Path]:
    remote = root / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True,
                   capture_output=True)
    repo = root / name
    repo.mkdir()
    run_git(repo, "init", "-b", "master")
    run_git(repo, "config", "user.email", "tester@example.com")
    run_git(repo, "config", "user.name", "tester")
    run_git(repo, "remote", "add", "origin", str(remote))
    return repo, remote


def commit_all(repo: Path, message: str) -> None:
    run_git(repo, "add", ".")
    run_git(repo, "commit", "-m", message)


def write_pom(repo: Path, version: str, revision: str = "", changelist: str = "") -> None:
    if revision:
        expression = DOLLAR + "{revision}" + DOLLAR + "{changelist}"
        text = f"""<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>demo</artifactId>
  <version>{expression}</version>
  <properties>
    <revision>{revision}</revision>
    <changelist>{changelist}</changelist>
  </properties>
</project>
"""
    else:
        text = f"""<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>demo</artifactId>
  <version>{version}</version>
</project>
"""
    (repo / "pom.xml").write_text(text, encoding="utf-8")


def write_release_note(repo: Path, version: str, date: str = "2026-10-19") -> None:
    text = f"""================================================================================
v{version}({date})
================================================================================
【新增功能】
TBD

================================================================================
v1.0.0(2026-01-01)
================================================================================
【新增功能】
旧记录
"""
    (repo / "release-note.txt").write_text(text, encoding="utf-8")


def cli(repo: Path, *args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [PY, "-m", "branch_guard", *args],
        cwd=repo, capture_output=True, encoding="utf-8", errors="replace", env=env,
    )


class VersionTests(unittest.TestCase):
    def test_bump(self) -> None:
        base = Version.parse("2.4.0-SNAPSHOT")
        self.assertEqual(base.bump("minor").raw, "2.5.0-SNAPSHOT")
        self.assertEqual(base.bump("patch").raw, "2.4.1-SNAPSHOT")
        self.assertEqual(base.bump("major").raw, "3.0.0-SNAPSHOT")
        self.assertEqual(base.bump("minor", keep_pre=False).raw, "2.5.0")

    def test_same_core(self) -> None:
        self.assertTrue(Version.parse("2.4.0-SNAPSHOT").same_core(Version.parse("2.4.0")))
        self.assertFalse(Version.parse("2.4.1").same_core(Version.parse("2.4.0")))

    def test_invalid(self) -> None:
        from branch_guard.core import BranchGuardError
        with self.assertRaises(BranchGuardError):
            Version.parse("2.4")


class PomTests(unittest.TestCase):
    def test_literal_read_write(self) -> None:
        text = (ROOT / "tests" / "fixtures" / "pom-literal.xml").read_text(encoding="utf-8")
        version, _ = _parse_pom_version(text, "pom.xml")
        self.assertEqual(version.raw, "2.3.0")
        updated, _ = _update_pom_text(text, Version.parse("2.4.0"))
        self.assertIn("<version>2.4.0</version>", updated)
        self.assertIn("<parent>", updated)
        self.assertIn("<version>1.0.0</version>", updated)
        version2, _ = _parse_pom_version(updated, "pom.xml")
        self.assertEqual(version2.raw, "2.4.0")

    def test_revision_read_write(self) -> None:
        text = (ROOT / "tests" / "fixtures" / "pom-revision.xml").read_text(encoding="utf-8")
        version, detail = _parse_pom_version(text, "pom.xml")
        self.assertEqual(version.raw, "2.4.0-SNAPSHOT")
        self.assertIn("revision", detail)
        updated, _ = _update_pom_text(text, Version.parse("2.5.0-SNAPSHOT"))
        self.assertIn("<revision>2.5.0</revision>", updated)
        self.assertIn("<changelist>-SNAPSHOT</changelist>", updated)
        version2, _ = _parse_pom_version(updated, "pom.xml")
        self.assertEqual(version2.raw, "2.5.0-SNAPSHOT")


class ReleaseNoteTests(unittest.TestCase):
    def test_insert_keeps_title_on_line_two(self) -> None:
        text = (ROOT / "tests" / "fixtures" / "release-note.txt").read_text(encoding="utf-8")
        cfg = Config()
        updated = insert_release_note(text, Version.parse("2.4.0"), "2026-11-18", cfg)
        lines = updated.splitlines()
        self.assertEqual(lines[1], "v2.4.0(2026-11-18)")
        self.assertIn("v2.3.0(2026-10-19)", updated)
        self.assertIn("TBD", updated)


class IntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _repo_with_pom(self, version: str = "2.3.0") -> Path:
        repo, _remote = init_repo(self.root)
        write_pom(repo, version)
        write_release_note(repo, version)
        commit_all(repo, "init")
        run_git(repo, "push", "-u", "origin", "master")
        return repo

    def test_check_conflict(self) -> None:
        repo = self._repo_with_pom("2.3.0")
        run_git(repo, "switch", "-c", "feature/a")
        write_pom(repo, "2.4.0")
        commit_all(repo, "feature a")
        run_git(repo, "switch", "master")
        proc = cli(repo, "check", "--repo", str(repo), "--bump", "minor",
                   "--no-fetch", "--json")
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        data = json.loads(proc.stdout)
        conflicts = data["repos"][0]["conflicts"]
        self.assertTrue(any(item["branch"] == "feature/a" for item in conflicts))

    def test_new_branch_success(self) -> None:
        repo = self._repo_with_pom("2.3.0")
        proc = cli(repo, "new-branch", "feature/b", "--repo", str(repo),
                   "--bump", "minor", "--no-fetch", "--date", "2026-11-18", "--json")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        data = json.loads(proc.stdout)
        result = data["repos"][0]
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["target_version"], "2.4.0")
        current = run_git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        self.assertEqual(current, "feature/b")
        self.assertIn("<version>2.4.0</version>", (repo / "pom.xml").read_text(encoding="utf-8"))
        note = (repo / "release-note.txt").read_text(encoding="utf-8").splitlines()
        self.assertEqual(note[1], "v2.4.0(2026-11-18)")

    def test_revision_repo(self) -> None:
        repo, _remote = init_repo(self.root)
        write_pom(repo, "", revision="2.4.0", changelist="-SNAPSHOT")
        write_release_note(repo, "2.4.0-SNAPSHOT")
        commit_all(repo, "init")
        run_git(repo, "push", "-u", "origin", "master")
        proc = cli(repo, "new-branch", "feature/rev", "--repo", str(repo),
                   "--bump", "minor", "--no-fetch", "--date", "2026-11-18", "--json")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        pom = (repo / "pom.xml").read_text(encoding="utf-8")
        self.assertIn("<revision>2.5.0</revision>", pom)
        self.assertIn("<changelist>-SNAPSHOT</changelist>", pom)

    def test_merged_branch_not_counted(self) -> None:
        repo = self._repo_with_pom("2.3.0")
        run_git(repo, "switch", "-c", "feature/a")
        write_pom(repo, "2.4.0")
        commit_all(repo, "feature a")
        run_git(repo, "push", "-u", "origin", "feature/a")
        run_git(repo, "switch", "master")
        run_git(repo, "merge", "--no-ff", "feature/a", "-m", "merge a")
        run_git(repo, "push", "origin", "master")
        proc = cli(repo, "scan", "--repo", str(repo), "--no-fetch", "--json")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        data = json.loads(proc.stdout)
        branches = data["repos"][0]["branches"]
        self.assertFalse(any(item["branch"] == "feature/a" for item in branches))
        self.assertFalse(any(item["branch"] == "origin/feature/a" for item in branches))

    def test_new_branch_worktree(self) -> None:
        repo = self._repo_with_pom("2.3.0")
        wt_root = self.root / "wt-root"
        proc = cli(
            repo, "new-branch", "feature/wt", "--repo", str(repo),
            "--bump", "minor", "--no-fetch", "--worktree",
            "--worktree-dir", str(wt_root), "--date", "2026-11-18", "--json",
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        data = json.loads(proc.stdout)
        wt = Path(data["repos"][0]["worktree_path"])
        self.assertTrue(wt.exists())
        self.assertIn("<version>2.4.0</version>", (wt / "pom.xml").read_text(encoding="utf-8"))
        current = run_git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        self.assertEqual(current, "master")

    def test_dirty_rejected(self) -> None:
        repo = self._repo_with_pom("2.3.0")
        (repo / "dirty.txt").write_text("x", encoding="utf-8")
        proc = cli(repo, "new-branch", "feature/c", "--repo", str(repo),
                   "--bump", "minor", "--no-fetch")
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("工作区不干净", proc.stdout)

    def test_version_txt(self) -> None:
        repo, _remote = init_repo(self.root)
        (repo / "version.txt").write_text("2.0.4\n", encoding="utf-8")
        commit_all(repo, "init")
        run_git(repo, "push", "-u", "origin", "master")
        proc = cli(repo, "new-branch", "feature/vt", "--repo", str(repo),
                   "--bump", "minor", "--no-fetch", "--json")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual((repo / "version.txt").read_text(encoding="utf-8").strip(), "2.1.0")

    def test_package_json(self) -> None:
        repo, _remote = init_repo(self.root)
        (repo / "package.json").write_text('{"name": "demo", "version": "1.2.3"}\n',
                                           encoding="utf-8")
        commit_all(repo, "init")
        run_git(repo, "push", "-u", "origin", "master")
        proc = cli(repo, "new-branch", "feature/pkg", "--repo", str(repo),
                   "--bump", "patch", "--no-fetch", "--json")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        text = (repo / "package.json").read_text(encoding="utf-8")
        self.assertIn('"version": "1.2.4"', text)
        self.assertIn('"name": "demo"', text)


if __name__ == "__main__":
    unittest.main()