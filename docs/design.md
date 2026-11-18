# 设计：一核多端

## 核心

`core/branch_guard` 只做四件事：

1. 解析项目版本（pom / release-note / version.txt / package.json）；
2. 扫描未合并分支的项目版本，判断目标版本是否被占用；
3. 创建分支（或 worktree）并写回目标版本；
4. 输出可读报告与 JSON。

核心不关心 AI 工具，也不做提交、推送、CI。

## 适配器

各端只负责在「AI 请求创建分支或 worktree」时把命令拦下：

| 端 | 拦截点 | 强度 |
|---|---|---|
| Claude Code | `PreToolUse` hook，匹配 `Bash` | 强制 |
| Codex / ChatGPT | `~/.codex/hooks.json` 的 `PreToolUse`（Claude 插件兼容格式） | 强制 |
| DSH | Cordis 插件监听 `tools/pre-execute` | 强制 |
| Kimi Code | skill + AGENTS 规则 | 软约束 |

强制拦截端在检查器失败时 fail-closed；Kimi 端依赖模型遵循规则。

## 版本源

不同仓库的版本声明不同，核心用适配器模式探测：先 pom、再 release-note、再 version.txt、最后 package.json。前端项目的 package.json 可能只是脚手架版本，release-note 才是发布口径；Maven 的 `changelist` 由 CI/CD 控制，核心只改 `revision`。

## 取舍

- 不在核心内查询制品仓库/CI：本机场景足够，且避免网络与凭据依赖。
- 不自动跳版本：版本冲突由负责人裁决，工具只报告。
- 只改文件不提交：提交与推送仍由使用者授权。
