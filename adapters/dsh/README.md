# DSH 适配器

DSH 的 `tools/pre-execute` 是官方提供的工具执行前策略点，插件可以返回 `{ kind: "deny", reason }` 强制拦截。

## 安装

1. 安装核心（`pip install -e core` 或设置 `PYTHONPATH`）。
2. 把本目录放到 profile 的 `node_modules/dsh-branch-guard`（junction 或复制）。
3. 在 `~/.dsh/profiles/desktop/cordis.patch.yml` 末尾加入：

````yaml
- insert:
    - id: branch-guard
      name: "dsh-branch-guard"
````

注意必须是 `insert` 语法；直接写 `- id: branch-guard` 会被当作覆盖不存在的条目而静默跳过。

4. 重启 DSH，或让 dsh-hmr 重新加载 patch。

## 环境变量

| 变量 | 用途 |
|---|---|
| `BRANCH_GUARD_HOME` | 仓库根目录（默认由插件位置推断） |
| `BRANCH_GUARD_PYTHON` | 指定 Python 解释器 |

## 行为

- 拦截所有 shell 工具里的建分支命令；
- 直接拦截 `create_worktree`，提示改用 `new-branch --worktree`；
- 检查器失败时 fail-closed。
