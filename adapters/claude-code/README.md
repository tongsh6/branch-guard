# Claude Code 适配器

## 安装

1. 安装核心：`pip install -e core`（或设置 `PYTHONPATH` 指向仓库的 `core` 目录）。
2. 把 hook 脚本放到任意位置，记录它的绝对路径。
3. 在 `~/.claude/settings.json` 的 `hooks.PreToolUse` 中加入：

````json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "python3 D:/tools/branch-guard/adapters/claude-code/hooks/pre_tool_use.py",
            "timeout": 90
          }
        ]
      }
    ]
  }
}
````

4. 重启 Claude Code。

## 环境变量

| 变量 | 用途 |
|---|---|
| `BRANCH_GUARD_HOME` | 仓库根目录（默认由脚本位置推断） |
| `BRANCH_GUARD_PYTHON` | 指定 Python 解释器（默认 `sys.executable`） |

## 行为

- 只拦截 `Bash` 工具里的建分支命令：`git switch -c`、`git checkout -b`、`git branch <name>`、`git worktree add -b`。
- 命中后调用 `branch_guard check`，把占用分支写进拒绝原因。
- 检查器失败时 fail-closed（仍然拒绝）。
- 其他命令直接放行。
