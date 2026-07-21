---
name: migrate-project-workflow-to-obsidian
description: 将项目仓库中的旧 `.agent` 私有开发工作流安全迁移到同步盘中的 Obsidian 项目目录，核对 Agent Project Workflow 配置与相关全局规则，并更新仓库 `.gitignore`，完成秘密隔离、文件校验、Obsidian 可见性验收和旧目录可恢复收口。用于用户要求“把这个项目改成新的 Obsidian 工作流”“迁移/删除 .agent”“让其他项目也使用 Myproject 下的 TODO、planning、constraints”等场景。
---

# 迁移项目工作流到 Obsidian

把 Obsidian 作为个人开发文档的唯一事实源。一次迁移一个项目，先证明新目录完整可用，再移除旧 `.agent`；不得双写，也不得用愿景替代实际文件校验。

## 依赖

- 先读取当前客户端的用户级规则、当前仓库 `AGENTS.md` / `CLAUDE.md` 和 Agent Project Workflow 配置。
- 读取并复用 `$agent-dev-workflow-init`；不要在本 Skill 中另造第二套目录标准。
- 需要操作 Obsidian UI 时使用 `$computer-use`，从命令面板执行完整重载并实际打开 `TODO.md` 验收。
- 使用本 Skill 的 `scripts/prepare_migration.py` 生成去密迁移包和校验报告。

## 1. 调查现场

修改前只读核对：

1. 确定仓库根目录、当前分支、HEAD、dirty worktree 和 `.gitignore`。
2. 清点 `.agent` 的文件数、大小和目录结构，读取 TODO、计划、约束与说明。
3. 只列出秘密文件的路径、权限和配置键名，不输出秘密值。
4. 查找 `.agent/` 路径引用；区分旧工作流引用与产品合法名称，例如 `.agent-vp-data`、`.agents/skills`。
5. 检查最终 Obsidian 目标是否存在、是否为空、是否已有用户笔记。
6. 确认最终项目目录。用户未指定时默认使用 `Myproject/<仓库目录名>`；不要先迁到临时位置再猜最终路径。

如果目标非空，先比较同名文件并形成合并方案，不得直接覆盖用户笔记。

## 2. 确定数据边界

允许同步到 Obsidian：

- `TODO.md`、`constraints/`、`explanations/`、`planning/`。
- 有长期价值的 `handoff/`。
- 小型、可复用且不含秘密的 `artifacts/`。
- 项目根目录已有的产品笔记与图片。

禁止同步：

- API Key、Token、密码、真实用户数据和本机凭据。
- `.env`、`local-secrets.env`、私钥、证书私钥和其他秘密载体。
- 构建缓存、依赖目录、运行日志和无长期价值的临时输出。

机器本地秘密迁入 `~/.config/agent-project-workflow/local/<仓库名>/` 或系统凭据库，权限至少为 `0600`。Obsidian 和迁移报告都不得记录秘密值。

## 3. 生成迁移包

从 Skill 目录运行：

```bash
python3 scripts/prepare_migration.py --repo-root <仓库根目录>
```

脚本默认排除无法执行文本秘密扫描的二进制文件。只有逐个复核确有长期价值后，才允许使用 `--include-binary` 重新生成迁移包；所有显式包含的二进制文件仍会进入报告和警告。

脚本会在系统临时目录创建：

```text
<临时目录>/
├── project/                 # 可复制到 Obsidian 的内容
└── migration-report.json   # 文件清单、SHA-256、排除项和警告
```

脚本会：

- 排除已知秘密文件、缓存、日志、超限文件、符号链接和未显式允许的二进制文件。
- 隔离疑似包含真实秘密的文本，要求人工复核。
- 把工作流文档中的 `.agent/...` 改为项目工作区相对路径。
- 保留 `.agent-vp-data` 等产品合法名称。
- 建立缺失的标准目录，但不修改 Obsidian、Git 或原 `.agent`。

检查报告中的 `warnings`、`excluded` 和 `suspected_secrets`。存在疑似秘密时不得继续复制，先人工去敏或确认排除。

## 4. 准备目标与全局映射

确认 `~/.config/agent-project-workflow/config.toml` 使用统一项目根目录；旧安装可以继续读取 `~/.codex/project-workflow.toml`：

```toml
version = 1
vault_root = "/本机/Obsidian/仓库路径"
projects_root = "Myproject"

[projects]
# 只有仓库重名或目录特殊时才需要显式映射。
"<仓库绝对路径>" = "Myproject/<项目名>"
```

没有特殊情况时，初始化脚本会自动解析到 `<vault_root>/Myproject/<仓库名>`，无需为每个项目重复添加映射。已有显式映射必须保留，配置权限保持 `0600`。

用初始化脚本只读预览解析结果：

```bash
python3 ~/.agents/skills/agent-dev-workflow-init/scripts/init_agent_workflow.py \
  --repo-root <仓库根目录> \
  --print-workflow-root

python3 ~/.agents/skills/agent-dev-workflow-init/scripts/init_agent_workflow.py \
  --repo-root <仓库根目录> \
  --dry-run
```

解析出的路径必须与用户确认的最终目录完全一致。

## 5. 写入 Obsidian

复制时只把迁移包的 `project/` 内容写入最终目录，不使用 `--delete`：

```bash
rsync -a '<迁移包>/project/' '<Obsidian 最终项目目录>/'
```

如果工具因云端私有资料导出策略拒绝写入：

- 不得改用 Finder、Computer Use、脚本或其他方式绕过。
- 把准确、无 `--delete` 的命令交给用户手动执行。
- 用户完成后继续只读校验。

已有项目笔记不在迁移包中时必须保留。目标目录需要调整时，先确认新目录为空，再整体移动；不要形成 `<项目>/<项目>` 重复嵌套。

## 6. 双重校验

第一次校验文件系统：

```bash
rsync -ainc --omit-dir-times --out-format='%i %n%L' \
  '<迁移包>/project/' '<Obsidian 最终项目目录>/'
```

输出为空才表示迁移包内文件内容一致。额外核对：

- 迁移文件数与目标新增文件数。
- `README.md`、`TODO.md`、三个 planning 状态目录、constraints、explanations、handoff、artifacts。
- 原有项目笔记和图片仍然存在。
- 没有秘密文件、疑似密钥和旧 `.agent/` 工作流路径。

第二次校验 Obsidian UI：

1. 如果目录在 Obsidian 外部移动或复制，不能只看磁盘。
2. 在确认没有未保存编辑后，从命令面板执行“重新加载 Obsidian（不保存当前编辑内容）”。普通 `⌘R` 不足以作为完整重载证据。
3. 展开最终项目目录，确认关键目录和根文档均显示。
4. 实际打开 `TODO.md`，确认正文可读。
5. 再运行一次文件内容比较，防止同步盘回滚或漏掉 artifacts。

在这两轮都通过前，不得删除或移动旧 `.agent`。

## 7. 收口旧工作流

完成校验后：

1. 把旧 `.agent` 移入废纸篓并使用带项目名和日期的唯一目录名；不要直接 `rm`。
2. 移除仓库 `.gitignore` 中只为旧工作流保留的 `.agent/` 行。
3. 按仓库规则在单目标分支提交 `.gitignore`，验证后安全合回开发集成分支。
4. 未经用户明确要求不推送、不创建 PR、标签或 Release。
5. 再确认仓库内没有 `.agent`，Obsidian 文件仍完整，初始化脚本不再报告旧工作流。

废纸篓备份包含机器本地秘密时只用于短期回滚，不作为运行事实源。最终是否清空废纸篓由用户决定。

## 8. 完成标准

只有以下事实全部成立才报告完成：

- `~/.codex` 全局规则和项目映射只指向 Obsidian。
- Obsidian 最终目录中迁移内容完整，无秘密。
- Obsidian 侧栏显示正确，`TODO.md` 已实际打开。
- 仓库内 `.agent` 已消失，`.gitignore` 旧规则已移除。
- 机器本地秘密权限正确。
- Git 工作区干净，提交、合并和远端状态表述真实。

报告迁移文件数、目标路径、秘密处理、校验结果、废纸篓恢复位置和 Git 状态。不要把未复制的 artifacts、未刷新的 Obsidian 或未推送的提交写成完成。
