# Codex / ChatGPT 适配器

Codex（含 ChatGPT 桌面版的 Codex 运行时）读取用户级 `~/.codex/hooks.json`，格式是 Claude 插件 hooks 风格：`description` + `hooks`，**没有** `version` 字段。

## 安装

1. 安装核心（`pip install -e core` 或设置 `PYTHONPATH`）。
2. 把 `adapters/claude-code/hooks/pre_tool_use.py` 放到任意位置。
3. 写入 `~/.codex/hooks.json`：

````json
{
  "description": "branch-guard: 创建分支前检查版本占用",
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "python3 D:/tools/branch-guard/adapters/claude-code/hooks/pre_tool_use.py"
          }
        ]
      }
    ]
  }
}
````

4. 重启 Codex / ChatGPT 桌面版，在 Hooks 面板确认已加载。

## 注意

- 不要写成 `{"version": 1, "hooks": ...}`，Codex 会报 `unknown field 'version'` 并忽略整个文件。
- 事件名是 `PreToolUse`，工具名匹配 `Bash`。
- Codex 的 hook 执行环境 PATH 可能很精简；脚本内部会补 `Git\cmd`，必要时设置 `BRANCH_GUARD_PYTHON`。
