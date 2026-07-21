"""管理器使用的公开常量。"""

from __future__ import annotations


APP_NAME = "agent-project-workflow"
STATE_SCHEMA_VERSION = 1
RELEASE_MANIFEST_SCHEMA_VERSION = 1
REPOSITORY_URL = "https://github.com/Viviana-Luna/agent-project-workflow"
LATEST_MANIFEST_URL = f"{REPOSITORY_URL}/releases/latest/download/release-manifest.json"
MANAGED_START = "<!-- agent-project-workflow:start -->"
MANAGED_END = "<!-- agent-project-workflow:end -->"
DIRECT_REPLACE_PHRASE = "直接替换"
LAUNCHER_MARKER = "# agent-project-workflow:launcher"
