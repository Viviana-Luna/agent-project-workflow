---
name: agent-dev-workflow-init
description: 初始化或整理基于 Obsidian 与同步盘的个人项目开发工作区，在统一的 Myproject 项目根目录下为仓库创建 TODO、constraints、explanations、planning、handoff 与 artifacts，并维护仓库公开协作入口。用于新项目首次接入、缺失目录补齐、工作区结构校正或路径解析检查；旧 `.agent` 的搬迁与删除应改用 `$migrate-project-workflow-to-obsidian`。
---

# 初始化 Obsidian 项目工作流

## 职责

本 Skill 只负责初始化或整理新工作区：

- 解析当前仓库对应的 Obsidian 项目目录。
- 创建缺失的标准目录和基础文档。
- 保留已有项目笔记，不覆盖用户内容。
- 维护仓库缺失的公开 `README.md`、`AGENTS.md` 和 `CLAUDE.md` 入口。
- 提示旧 `.agent` 残留，但不迁移、不删除。

发现旧 `.agent` 时，停止初始化后的进一步收口，改用 `$migrate-project-workflow-to-obsidian` 完成去密、复制、校验和可恢复删除。不要在两个 Skill 中维护两套迁移流程。

## 路径规则

工作区配置按以下顺序查找：

1. `AGENT_PROJECT_WORKFLOW_CONFIG` 指定的文件。
2. `~/.config/agent-project-workflow/config.toml`。
3. 兼容旧安装的 `~/.codex/project-workflow.toml`。

配置格式：

```toml
version = 1
vault_root = "/本机/Obsidian/仓库路径"
projects_root = "Myproject"

[projects]
# 可选：只有仓库重名或需要特殊目录时才写显式映射。
# "/本机/代码/muse" = "Myproject/muse"
```

解析顺序只有两层：

1. `[projects]` 中与仓库绝对路径完全匹配的映射。
2. 没有映射时使用 `<vault_root>/<projects_root>/<仓库名>`。

`projects_root` 缺失时按 `Myproject` 处理，兼容旧配置。`--workflow-root` 可以临时指定绝对目标；`--project-name` 是相对于 `vault_root` 的完整项目路径，不会自动补 `projects_root`。

不同电脑各自维护本机配置，绝对路径不得写入仓库。配置缺失、路径无效或目标落在代码仓库内部时必须停止，不得回退到仓库创建 `.agent`。

## 标准结构

```text
<Obsidian>/Myproject/<仓库名>/
├── README.md
├── TODO.md
├── constraints/
│   └── README.md
├── explanations/
│   └── README.md
├── planning/
│   ├── README.md
│   ├── 计划模板.md
│   ├── 计划中/
│   ├── 执行中/
│   └── 已完成/
├── handoff/
│   └── README.md
└── artifacts/
    └── README.md
```

- `TODO.md` 只保留未完成任务。
- `planning/` 保存实施方案和完成摘要，不维护 checkbox 流水。
- `constraints/` 保存长期规则，`explanations/` 保存产品与设计说明。
- `handoff/` 保存交接材料；`artifacts/` 只保存值得长期同步的小型产物。
- 项目根目录可以继续保存产品总览、学习笔记和图片。

API Key、令牌、密码和真实用户数据不得进入 Obsidian。机器本地秘密放在系统凭据库或 `~/.config/agent-project-workflow/local/<仓库名>/`，并限制权限。

## 执行

先只看解析结果：

```bash
python3 ~/.agents/skills/agent-dev-workflow-init/scripts/init_agent_workflow.py \
  --repo-root . \
  --print-workflow-root
```

再预览写入：

```bash
python3 ~/.agents/skills/agent-dev-workflow-init/scripts/init_agent_workflow.py \
  --repo-root . \
  --dry-run
```

确认后初始化：

```bash
python3 ~/.agents/skills/agent-dev-workflow-init/scripts/init_agent_workflow.py \
  --repo-root .
```

脚本只创建缺失内容，不覆盖已有 Obsidian 文档。仓库已有公开入口也会保留；只有带旧托管标记的历史片段会被清理。除非用户明确使用 `--remove-development`，否则不删除 `DEVELOPMENT.md`。

## 验收

- 解析路径位于 `<vault_root>/Myproject/<仓库名>` 或显式映射目录。
- 标准目录和入口文档存在，已有用户笔记内容未变化。
- 仓库内没有新建 `.agent`，公开文档没有本机绝对路径和个人计划。
- `AGENTS.md` 与 `CLAUDE.md` 的公共约束一致。
- 若检测到旧 `.agent`，只报告并转交迁移 Skill，不把初始化说成迁移完成。
