"""Console configuration: workspace, agent, locations and (optional) private overrides.

Nothing client-specific is built in. Paths and wording come from CLI flags or an optional
JSON config file kept in private storage.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_AGENT = "WizExpert"
DEFAULT_OUTPUT_ROOTS = ("deliverables",)
# Directories never listed or served as outputs (evidence, history, tooling, secrets).
DEFAULT_EXCLUDE_DIRS = (
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "evidence",
    "archives",
    "snapshots",
    "inventories",
    "staging",
)


def default_state_dir() -> Path:
    return Path(os.environ.get("WIZEXPERT_CONSOLE_HOME") or Path.home() / ".wizexpert-console")


def default_copilot_home() -> Path:
    return Path(os.environ.get("COPILOT_HOME") or Path.home() / ".copilot")


def default_vscode_user_dir() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", "")) / "Code" / "User"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Code" / "User"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "Code" / "User"


@dataclass
class ConsoleConfig:
    workspace: Path
    agent: str = DEFAULT_AGENT
    state_dir: Path = field(default_factory=default_state_dir)
    copilot_home: Path = field(default_factory=default_copilot_home)
    vscode_user_dir: Path = field(default_factory=default_vscode_user_dir)
    output_roots: tuple[str, ...] = DEFAULT_OUTPUT_ROOTS
    exclude_dirs: tuple[str, ...] = DEFAULT_EXCLUDE_DIRS
    deny_names: tuple[str, ...] = ()  # exact file names that are never listed or served
    prompts: dict[str, str] = field(default_factory=dict)  # category id -> template override
    allow_cli_fallback: bool = False
    code_command: str = "code"
    auto_install_helper: bool = False
    start_timeout: float = 90.0
    open_wait_ms: int = 2500
    new_chat_wait_ms: int = 1500
    status_sync_hours: float = 24.0
    # Owner identifier (as shown as assignee in Wiz) whose cases the status sync checks.
    # Empty: the sync refuses to run. Set it in the private console config, never here.
    status_sync_assignee: str = ""

    @property
    def session_state(self) -> Path:
        return self.copilot_home / "session-state"

    @property
    def agent_host_db(self) -> Path:
        return self.vscode_user_dir / "globalStorage" / "agent-host.db"

    @property
    def bridge_config(self) -> Path:
        return Path(os.environ.get("WIZEXPERT_CONSOLE_BRIDGE") or self.state_dir / "bridge.json")

    def resolved_workspace(self) -> Path:
        return Path(self.workspace).resolve()


def load_overrides(config: ConsoleConfig, path: Path) -> ConsoleConfig:
    """Apply a private JSON file (agent, output_roots, deny_names, prompts, ...)."""
    data: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("The console config must be a JSON object.")
    allowed = {
        "agent", "output_roots", "exclude_dirs", "deny_names", "prompts",
        "start_timeout", "status_sync_hours", "status_sync_assignee",
    }
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ValueError("Unknown console config key(s): " + ", ".join(unknown))
    if "agent" in data:
        config.agent = str(data["agent"])
    for key in ("output_roots", "exclude_dirs", "deny_names"):
        if key in data:
            setattr(config, key, tuple(str(v) for v in data[key]))
    if "prompts" in data and isinstance(data["prompts"], dict):
        config.prompts = {str(k): str(v) for k, v in data["prompts"].items()}
    if "start_timeout" in data:
        config.start_timeout = float(data["start_timeout"])
    if "status_sync_assignee" in data:
        assignee = str(data["status_sync_assignee"]).strip()
        if assignee and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._@-]{0,63}", assignee):
            raise ValueError("status_sync_assignee may only use letters, digits, . _ @ -.")
        config.status_sync_assignee = assignee
    if "status_sync_hours" in data:
        config.status_sync_hours = max(0.0, float(data["status_sync_hours"]))
    return config
