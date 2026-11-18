---
name: branch-guard
description: 创建分支前检查版本号是否被其他未合并分支占用，并用 new-branch 完成版本预升级。
---

# branch-guard

创建分支（feature / release / bugfix）时，先检查目标版本是否已被其他未合并分支占用，再用统一命令完成版本预升级，避免同名 SNAPSHOT 构件被覆盖。

## 何时使用

- 需要新建任何 git 分支时（feature、bugfix、release）。
- 多仓 Feature 准备阶段，需要为多个仓库批量建分支并预升级版本。
- 需要确认某个目标版本是否已被占用时，使用只读的 check / scan。

## 唯一允许的入口

    new-branch <分支名> --bump minor|patch|major [--repo PATH ...]

- --bump minor：兼容新增功能（PATCH 归零）。
- --bump patch：仅兼容修复。
- --bump major：不兼容变更。
- 可用 --version X.Y.Z 显式指定目标版本。
- 多仓用 --repo 重复指定，或在仓库根 branch-guard.json 的 multiRepo 中配置。\n- 需要 worktree 时加 --worktree（默认 ~/.branch-guard/worktrees/<repo>，可用 --worktree-dir 或 BRANCH_GUARD_WORKTREE_ROOT 覆盖）。

禁止直接执行 git switch -c、git checkout -b、git branch <name>、git worktree add -b；这些命令不会修改版本号。

## 执行流程

1. 确认工作区干净；有未提交改动时先处理，或显式 --allow-dirty。
2. 工具会 fetch 基线（默认 origin/master），读取当前项目版本，推导目标版本。
3. 扫描所有未合并分支的项目版本；目标版本被占用则拒绝，并列出占用分支、作者、提交。
4. 通过后创建分支（从基线起点），写入 pom（字面 version 或 revision，changelist 不动）、release-note 第 2 行占位、version.txt / package.json（按实际版本源）。
5. 工具只改文件，不提交、不推送。

## 失败处理

- 版本冲突：把占用分支和版本报告给用户，由用户裁决；不要自动跳到下一个版本号，也不要反复重试。用户裁决后，用 --version 显式指定新版本（例如 --version 3.27.0）；再次执行仍会校验新版本是否被占用。
- 未 bump（目标版本等于当前版本）：确认变更级别后重新执行。
- 版本回退（目标版本不高于最新 tag）：先核对 master/tag，必要时 --allow-old 并说明理由。
- 工作区不干净：先处理或确认 --allow-dirty。
- 检查器异常：如实报告，不要绕过检查直接建分支。

## 与工作台发布规则的关系

- 版本推导仍以刷新后的 origin/master 和远端 tag 为依据；占用检查只用于防止并行分支同名覆盖，不改变发布版本推导规则。
- MINOR 升级 PATCH 归零；混合变更按最高级别只算一次。
- Maven 的 changelist 默认值由 CI/CD 控制，不修改、不清空。
- release 阶段服务依赖保留开发版本（SNAPSHOT），生产发布完成合并 master 时才转正式版。
- 工具默认只改文件；提交、推送、创建 tag、发布制品仍需用户明确授权。

## 只读检查

    new-branch check --repo <路径> --bump minor --dry-run
    new-branch scan  --repo <路径>

check 返回码 2 表示检查未通过（占用 / 未 bump / 回退 / 工作区脏）。
