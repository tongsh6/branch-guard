# Kimi Code 适配器

Kimi Code 的插件清单（`kimi.plugin.json`）目前只支持 `skills` 和 `interface`，没有 hooks 字段，所以这里是 **skill + AGENTS 规则** 的软约束，不是工具级强制拦截。

## 安装

1. 安装核心（`pip install -e core` 或设置 `PYTHONPATH`）。
2. 复制 skill 到用户级 skills 目录：

````powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.kimi-code\skills\branch-guard" | Out-Null
Copy-Item .\adapters\kimi-code\SKILL.md "$env:USERPROFILE\.kimi-code\skills\branch-guard\SKILL.md"
````

3. 把 `AGENTS.snippet.md` 的内容追加到 `~/.kimi-code/AGENTS.md`。
4. 新开 Kimi Code 会话。

## 验证

让 Kimi 执行建分支操作，观察它是否主动调用 `new-branch`。软约束没有强制拦截，需要人工复核。
