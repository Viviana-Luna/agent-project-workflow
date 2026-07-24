---
name: agent-dev-workflow-init
description: 初始化、整理或调整基于 Obsidian 与同步盘的项目开发工作区。首次接入时让用户选择 Obsidian Vault 和 Vault 内的完整项目路径，持久化仓库精确映射，并创建 TODO、constraints、explanations、planning、handoff 与 artifacts；后续用于安全预览和迁移项目文档位置、接管已有工作区、补齐目录、校正路径或维护仓库公开入口。旧 `.agent` 的内容迁移与删除应改用 `$migrate-project-workflow-to-obsidian`。
---

# 初始化 Obsidian 项目工作流

## 职责

本 Skill 只负责初始化或整理新工作区：

- 解析当前仓库对应的 Obsidian 项目目录。
- 首次初始化时要求用户选择并持久化项目文档位置。
- 后续安全改绑或整体迁移项目工作区，不静默合并、覆盖或遗留双重事实源。
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

配置由首次项目初始化创建，不由 `apw install` 创建。格式如下：

```toml
version = 1
vault_root = "/本机/Obsidian/仓库路径"

[projects]
"/本机/代码/muse" = "Myproject/muse"
"/本机/代码/公司产品/backend" = "Rsit/公司产品/backend"
```

按以下规则处理：

1. 用 `[projects]` 中与仓库绝对路径完全匹配的映射定位工作区。
2. 没有映射时停止，让用户选择 Vault 内的完整相对路径；可以根据代码目录提出建议，但不得代替用户决定放入 `Myproject`、`Rsit` 或其他目录。
3. 选择确认后把精确映射写入配置，最终工作区为 `<vault_root>/<项目映射>`。

旧配置中的 `projects_root` 只用于识别可能需要迁移的历史默认工作区，不再作为新项目回退规则。`--project-path` 是相对于 `vault_root` 的完整项目路径；`--project-name` 仅作为旧参数别名保留。`--workflow-root` 只允许路径诊断，不持久化映射。

不同电脑各自维护本机配置，绝对路径不得写入仓库。配置缺失时先让用户选择 Vault；项目无映射时先让用户选择项目路径。路径无效或目标落在代码仓库内部时必须停止，不得回退到仓库创建 `.agent`。

## 标准结构

```text
<Obsidian>/<用户选择的项目路径>/
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

先调查仓库根目录、配置、现有映射、旧默认工作区、候选目标和 dirty worktree。发现旧 `.agent` 时只报告，改用迁移 Skill。

项目已有映射时，先只看解析结果：

```bash
python3 ~/.agents/skills/agent-dev-workflow-init/scripts/init_agent_workflow.py \
  --repo-root . \
  --print-workflow-root
```

项目没有映射时，必须先询问用户：

- 配置不存在：选择 Obsidian Vault。
- 选择 Vault 内的完整项目路径，例如 `Myproject/muse` 或 `Rsit/产品线/backend`。
- 同名仓库可能冲突时，优先保留必要的产品层级。

首次初始化先预览：

```bash
python3 ~/.agents/skills/agent-dev-workflow-init/scripts/init_agent_workflow.py \
  --repo-root . \
  --vault-root "<首次配置时选择的 Vault>" \
  --project-path "<用户选择的 Vault 内相对路径>" \
  --dry-run
```

已有配置时省略 `--vault-root`。确认预览中的配置文件、仓库绝对路径、相对映射和最终目录后，再用相同参数去掉 `--dry-run`。

调整已有项目位置时，先预览整体移动：

```bash
python3 ~/.agents/skills/agent-dev-workflow-init/scripts/init_agent_workflow.py \
  --repo-root . \
  --project-path "<新的 Vault 内相对路径>" \
  --relocate \
  --dry-run
```

用户确认后去掉 `--dry-run`。脚本只在旧工作区存在且新目标不存在时整体移动；先移动目录，再原子更新配置，配置写入失败时回滚目录。旧目录与目标目录同时存在时停止，不自动合并。

旧映射目录已经不存在、目标目录已存在且经核对确实属于当前项目时，使用 `--adopt-existing --dry-run` 预览，再经用户确认后显式接管。不得用该参数绕过两个非空工作区的内容比较。

脚本只创建缺失内容，不覆盖已有 Obsidian 文档。仓库已有公开入口也会保留；只有带旧托管标记的历史片段会被清理。除非用户明确使用 `--remove-development`，否则不删除 `DEVELOPMENT.md`。

## 验收

- 配置包含当前仓库的精确 `[projects]` 映射，解析路径与用户选择完全一致。
- 标准目录和入口文档存在，已有用户笔记内容未变化。
- 改变位置后只有新映射作为当前事实源；未静默合并、覆盖或留下仍被配置引用的旧目录。
- 仓库内没有新建 `.agent`，公开文档没有本机绝对路径和个人计划。
- `AGENTS.md` 与 `CLAUDE.md` 的公共约束一致。
- 若检测到旧 `.agent`，只报告并转交迁移 Skill，不把初始化说成迁移完成。
