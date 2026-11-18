## 分支创建门禁（branch-guard）

创建任何新分支前，必须使用 branch-guard，禁止直接执行 git switch -c、git checkout -b、git branch <name>、git worktree add -b。

- 命令：new-branch <分支名> --bump minor|patch|major [--repo PATH ...]，或 new-branch <分支名> --worktree 同时创建 worktree。
- 目标版本必须未被其他未合并分支占用；冲突时报告占用分支，由用户裁决，不得自动跳版本或反复重试。
- new-branch 只改文件，不提交、不推送；提交与推送仍需用户明确授权。
- 不修改 Maven 的 changelist 默认值，它由 CI/CD 控制。
