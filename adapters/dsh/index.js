import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = process.env.BRANCH_GUARD_HOME || join(HERE, "..", "..");
const CORE = join(ROOT, "core");

export const name = "branch-guard";
export const inject = ["tools"];

const PATTERNS = [
  /\bgit\s+switch\b[^\n]*\s(?:-c|--create)\b/,
  /\bgit\s+checkout\b[^\n]*\s(?:-b|-B)\b/,
  /\bgit\s+branch\b\s+(?!-|--)[^\s]+/,
  /\bgit\s+worktree\s+add\b[^\n]*\s(?:-b|--create)\b/,
];
const SHELL_TOOL = /bash|shell|pwsh|terminal/i;
const WORKTREE_TOOL = /worktree/i;

export function detect(command) {
  return PATTERNS.some((re) => re.test(command));
}

function summarize(stdout) {
  try {
    const data = JSON.parse(stdout);
    const repo = (data.repos || [{}])[0];
    const lines = [];
    for (const err of repo.errors || []) lines.push("- " + String(err));
    for (const c of (repo.conflicts || []).slice(0, 5)) {
      lines.push("  - " + String(c.branch) + "（" + String(c.version) + "，" + String(c.author) + "，" + String(c.date) + "）");
    }
    return lines.length ? lines.join("\n") : "版本检查未通过";
  } catch {
    return "版本检查未通过";
  }
}

function pythonCandidates() {
  const env = process.env.BRANCH_GUARD_PYTHON;
  if (env) return [[env, []]];
  const candidates = [];
  candidates.push(["py", ["-3"]], ["python3", []], ["python", []]);
  return candidates;
}

async function checkVersion(repo) {
  const args = [
    "-m", "branch_guard", "check",
    "--repo", repo, "--no-fetch", "--allow-dirty", "--bump", "minor", "--json",
  ];
  const env = { ...process.env };
  env.PYTHONPATH = CORE;
  env.PATH = (env.PATH || "") + ";C:\\Program Files\\Git\\cmd;C:\\Windows\\System32";
  let lastError = null;
  for (const [file, prefix] of pythonCandidates()) {
    try {
      const result = await execFileAsync(file, [...prefix, ...args], { env, timeout: 30000, windowsHide: true });
      return summarize(result.stdout);
    } catch (error) {
      const stdout = error && error.stdout ? String(error.stdout) : "";
      if (stdout.trim()) return summarize(stdout);
      lastError = error;
      const message = error && error.message ? String(error.message) : "";
      if (message.includes("ENOENT")) continue;
      throw error;
    }
  }
  throw lastError || new Error("python not found");
}

export function apply(ctx) {
  ctx.on("tools/pre-execute", async (exec, next) => {
    const toolName = String(exec.name || "");
    if (WORKTREE_TOOL.test(toolName)) {
      return {
        kind: "deny",
        reason: "禁止直接创建 worktree 分支。请使用 new-branch <分支名> --worktree 创建分支与 worktree，并完成版本预升级。",
      };
    }
    if (!SHELL_TOOL.test(toolName)) return next();
    const args = exec.arguments || {};
    const command = String(args.command || "");
    if (!command || !detect(command)) return next();
    const repo = String(args.workdir || args.cwd || process.cwd());
    try {
      const detail = await checkVersion(repo);
      return {
        kind: "deny",
        reason: "禁止直接创建分支。\n" + detail + "\n请改用 new-branch <分支名> --version <负责人确认的版本>（或 --bump minor|patch --worktree）。",
      };
    } catch {
      return {
        kind: "deny",
        reason: "禁止直接创建分支。branch-guard 检查器暂时不可用，请手动执行 new-branch <分支名> --version <负责人确认的版本>。",
      };
    }
  });
}
