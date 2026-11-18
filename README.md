# branch-guard

创建 Git 分支前检查「目标版本是否已被其他未合并分支占用」，并完成版本预升级（pom / release-note / version.txt / package.json）。

用于防止多个迭代分支共用同一个 SNAPSHOT 版本，导致 CI 构建或制品部署互相覆盖。

## 一核多端

````
core/                 Python CLI（检查、占用扫描、版本写回）
adapters/claude-code/ Claude Code PreToolUse hook
adapters/codex/       Codex / ChatGPT 桌面版 hooks.json（Claude 插件兼容格式）
adapters/dsh/         DSH Cordis 插件（tools/pre-execute）
adapters/kimi-code/   Kimi Code skill + AGENTS 规则
bin/                  new-branch 命令包装（cmd / ps1）
````

核心是同一个 `new-branch` 命令；各端只负责在「AI 创建分支或 worktree」时把命令拦下并引导到它。

## 安装

需要 Python 3.10+。

````powershell
# 安装核心（任选其一）
pip install -e core
# 或直接使用
py -3 -m branch_guard --help   # 需要 PYTHONPATH 指向 core
````

把 `bin` 加入 PATH：

````powershell
pwsh -File install.ps1
````

## 快速开始

````powershell
# 创建分支并预升级版本
new-branch feature/20261118-xxx --bump minor --repo D:/path/to/repo

# 创建分支 + worktree
new-branch feature/20261118-xxx --bump minor --worktree   # 默认 ~/.branch-guard/worktrees/<repo>

# 只检查
new-branch check --repo D:/path/to/repo --bump minor --dry-run
new-branch scan  --repo D:/path/to/repo
````

多仓用 `--repo` 重复指定，或在仓库根 `branch-guard.json` 的 `multiRepo` 中配置。

## 版本源

自动探测顺序：

1. `pom.xml`：根 project/version；若为属性表达式则读 `properties/revision + changelist`
2. `release-note.txt`：第 2 行 `vX.Y.Z(日期)`（前端/小程序口径）
3. `version.txt`
4. `package.json` 的 `version`

可用 `branch-guard.json` 的 `versionSource` 显式指定。

## 判断规则

- R1 占用：目标版本核心值出现在任一未合并分支上 → 拒绝
- R2 未 bump：目标版本与当前版本核心相同 → 拒绝
- R3 回退：目标版本不高于最新 tag → 拒绝（`--allow-old` 跳过）

占用扫描范围：本地与远端分支；排除基线分支本身、已合并到基线的分支。

## 配置

全局：`~/.branch-guard/config.json`
仓库：仓库根 `branch-guard.json` 或 `.branch-guard.json`

字段见 [examples/branch-guard.json](examples/branch-guard.json)。

## 适配器

- [Claude Code](adapters/claude-code/README.md)
- [Codex / ChatGPT](adapters/codex/README.md)
- [DSH](adapters/dsh/README.md)
- [Kimi Code](adapters/kimi-code/README.md)

各端拦截强度不同：Claude Code、Codex、DSH 可以在工具执行前强制拦截；Kimi Code 目前只有 skill + 规则（软约束）。

## 边界

- 只做本地分支扫描，不查询 CI / 制品仓库。
- `new-branch` 只改文件，不提交、不推送。
- 不改 Maven 的 `changelist` 默认值；它由 CI/CD 控制。
- 版本冲突时报告占用分支，由使用者裁决；工具不自动跳版本。

## 开发

````powershell
cd core
python -m unittest discover -s tests -v
````

## License

MIT
