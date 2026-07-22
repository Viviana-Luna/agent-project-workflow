# Agent Project Workflow

一套以 Obsidian 为个人开发事实源、面向多种 AI 编码客户端的项目规划、迁移和单任务执行工作流。

它解决的不是“如何生成更多计划”，而是如何让长期项目中的 TODO、计划、真实代码、验证结果和 Git 状态保持一致，同时把私人上下文与公开仓库分开。

## 核心原则

- **事实分层**：代码与公开规则在 Git；个人 TODO、计划与项目认知在 Obsidian；秘密在系统凭据库或机器本地目录。
- **先调查再修改**：任何非平凡代码任务都先核对真实代码、配置、日志、运行状态和 Git 现场。
- **一次一个目标**：每次只执行一个可验收 TODO，完成实现、测试、审查、提交和文档收口后停止。
- **计划不是任务看板**：checkbox 只写入 `TODO.md`；计划保存背景、边界、方案、验收和风险。
- **多客户端适配**：工作流核心保持工具无关，首版通过适配器连接 Codex、Claude Code、Kimi Code、OpenCode。

## 仓库内容

```text
adapters/     用户级 AI 客户端规则模板
config/       脱敏配置示例
docs/         架构、文档状态和客户端接入说明
scripts/      安装、诊断和验证工具
skills/       初始化、迁移和 TODO 单任务闭环 Skill
templates/    Obsidian 项目工作区模板
tests/        标准库自动化测试
```

## 支持范围

- 操作系统：macOS、Linux、Windows。
- 客户端：Codex、Claude Code、Kimi Code、OpenCode。
- 运行时：工具私有 CPython 3.12，不修改系统 Python。
- 更新策略：只在用户明确检查或安装更新时联网，不自动更新。

管理器只接入规则和 Skill，不负责安装或登录智能体客户端。

## 一键安装

正式 Release 发布后运行：

macOS / Linux：

```bash
curl -fsSL https://github.com/Viviana-Luna/agent-project-workflow/releases/latest/download/install.sh | sh
```

Windows（PowerShell）：

```powershell
irm https://github.com/Viviana-Luna/agent-project-workflow/releases/latest/download/install.ps1 | iex
```

Bootstrap 会安装到用户目录并启动交互向导。向导依次选择 Obsidian Vault、项目根目录和需要接入的客户端；发现已有规则或同名 Skill 时先展示差异，再允许压缩归档后替换或明确确认的无备份直接替换。

安装完成后使用：

```bash
apw
apw install --clients codex,claude-code,kimi-code,opencode
apw clients
apw status
apw update --check
apw update
apw doctor
apw repair
apw uninstall
```

如果 `~/.local/bin` 不在 `PATH`，向导会展示 Shell 配置修改并单独征求确认。

## 从源码预览

尚未发布 Release 或参与开发时，可以在仓库中运行：

```bash
python3 -m apw install \
  --clients codex,claude-code,kimi-code,opencode \
  --dry-run
```

首次非交互安装必须明确提供 Vault：

```bash
python3 -m apw install \
  --clients codex,opencode \
  --vault-root /path/to/obsidian-vault \
  --non-interactive \
  --yes
```

`scripts/install.py` 仅为旧版调用方式保留，新安装统一使用 `apw`。

## 初始化项目工作区

在代码仓库中运行：

```bash
python3 ~/.agents/skills/agent-dev-workflow-init/scripts/init_agent_workflow.py \
  --repo-root . \
  --dry-run

python3 ~/.agents/skills/agent-dev-workflow-init/scripts/init_agent_workflow.py \
  --repo-root .
```

检查工作区一致性：

```bash
python3 scripts/workflow_doctor.py --repo-root .
```

## 配置查找顺序

工具依次查找：

1. `AGENT_PROJECT_WORKFLOW_CONFIG` 环境变量指定的文件。
2. macOS/Linux：`~/.config/agent-project-workflow/config.toml`；Windows：`%LOCALAPPDATA%\agent-project-workflow\config\config.toml`。
3. 兼容旧安装的 `~/.codex/project-workflow.toml`。

Windows 上管理器目录位于 `%LOCALAPPDATA%\agent-project-workflow\`，`current` 版本指针用目录联接（junction）而非符号链接，PATH 写入用户环境变量（注册表）。

默认项目目录是 `<vault_root>/Myproject/<仓库名>`；只有仓库重名或目录特殊时才需要 `[projects]` 显式映射。

## 当前能力

- 创建标准 Obsidian 项目工作区，保留已有文档。
- 将旧 `.agent` 去密迁移到仓库外工作区。
- 从 TODO 选择单个任务并执行完整工程闭环。
- 检查目录、TODO 引用、计划状态、遗留路径和常见秘密载体。
- 交互选择并接入 Codex、Claude Code、Kimi Code、OpenCode。
- 通过托管规则区块保留用户自定义内容。
- 手动检查和安装 GitHub Release 更新，校验 SHA-256 并保留上一版本用于正常更新失败回滚。
- 显式降级必须指定目标版本、允许降级，并完成独立的二次确认。
- 管理客户端增删、状态、诊断、修复和安全卸载。
- 对旧规则和重复 Skill 提供差异预览、压缩归档或明确确认的无备份替换。

## 安全边界

- 不要提交真实 `project-workflow.toml`、Obsidian 项目内容、API Key、Token、凭据、日志或用户数据。
- 迁移脚本的秘密检测只是辅助门禁，不能替代人工复核或专业 secret scanner。
- `apw` 默认不覆盖已有规则和 Skill；旧版 `scripts/install.py` 的 `--force` 仅作为兼容入口保留。
- `apw` 的无备份直接替换必须输入确认短语；该模式不创建长期备份，也不承诺失败恢复。
- 普通启动、`status` 和 `doctor` 不联网，只有 `update` 会访问 GitHub Release。

需要显式降级时使用：

```bash
apw update --version 1.0.0 --allow-downgrade
```

非交互环境还必须同时提供 `--confirm-downgrade`；普通升级不会自动降级。

## 发布构建

```bash
python3 scripts/build_release.py --output dist
python3 dist/apw.pyz --version
cd dist && shasum -a 256 -c SHA256SUMS
```

推送 `v*` 标签后，GitHub Actions 会运行门禁并生成 `apw.pyz`、`install.sh`、`release-manifest.json` 和 `SHA256SUMS`。创建远程、推送、标签和 Release 都不属于本地构建操作，需要单独授权。

## 验证

```bash
python3 -m unittest discover -s tests -v
python3 scripts/validate.py
```

## License

MIT
