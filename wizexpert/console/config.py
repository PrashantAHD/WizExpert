"""Console configuration: workspace, agent, locations and (optional) private overrides.

Nothing client-specific is built in. Paths and wording come from CLI flags or an optional
JSON config file kept in private storage.
"""

from __future__ import annotations

import contextlib
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


ASSIGNEE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._@-]{0,63}")


PROFILE_NAME_PATTERN = re.compile(r"[A-Za-z0-9 ._'-]{1,60}")
PROFILE_ID_PATTERN = re.compile(r"[A-Za-z0-9._@-]{1,64}")


def profile_path(state_dir: Path) -> Path:
    return Path(state_dir) / "profile.json"


def validate_profile(name: str, user_id: str) -> tuple[str, str]:
    """Return the cleaned (name, user_id) or raise ValueError. Display only."""
    name, user_id = str(name).strip(), str(user_id).strip()
    if not PROFILE_NAME_PATTERN.fullmatch(name) or not name:
        raise ValueError("Name must be 1-60 characters: letters, digits, space . _ ' -")
    if not PROFILE_ID_PATTERN.fullmatch(user_id):
        raise ValueError("User ID must be 1-64 characters: letters, digits . _ @ -")
    return name, user_id


def save_profile(state_dir: Path, name: str, user_id: str) -> Path:
    name, user_id = validate_profile(name, user_id)
    path = profile_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"name": name, "user_id": user_id}), encoding="utf-8")
    return path


MAX_PHOTO_BYTES = 1024 * 1024
PHOTO_TYPES = {".png": "image/png", ".jpg": "image/jpeg"}


def photo_extension(data: bytes) -> str:
    """Return '.png' or '.jpg' from magic bytes, or raise ValueError."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    raise ValueError("Photo must be a PNG or JPEG image.")


def find_photo(state_dir: Path) -> Path | None:
    for ext in PHOTO_TYPES:
        path = Path(state_dir) / f"profile-photo{ext}"
        if path.is_file():
            return path
    return None


def remove_photo(state_dir: Path) -> None:
    for ext in PHOTO_TYPES:
        with contextlib.suppress(OSError):
            (Path(state_dir) / f"profile-photo{ext}").unlink()


def save_photo(state_dir: Path, data: bytes) -> Path:
    """Validate and atomically store the display-only profile photo."""
    if not data or len(data) > MAX_PHOTO_BYTES:
        raise ValueError("Photo must be between 1 byte and 1 MB.")
    ext = photo_extension(data)
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    target = state_dir / f"profile-photo{ext}"
    tmp = state_dir / f"profile-photo{ext}.tmp"
    tmp.write_bytes(data)
    os.replace(tmp, target)
    for other in PHOTO_TYPES:
        if other != ext:
            with contextlib.suppress(OSError):
                (state_dir / f"profile-photo{other}").unlink()
    return target


def load_profile(state_dir: Path) -> dict[str, Any]:
    """Never raises; a missing or invalid profile reads as not configured."""
    empty: dict[str, Any] = {"configured": False, "name": "", "user_id": "", "has_photo": False}
    try:
        data = json.loads(profile_path(state_dir).read_text(encoding="utf-8"))
        name, user_id = validate_profile(data["name"], data["user_id"])
    except (OSError, ValueError, KeyError, TypeError):
        return empty
    return {
        "configured": True,
        "name": name,
        "user_id": user_id,
        "has_photo": find_photo(state_dir) is not None,
    }


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
        if assignee and not ASSIGNEE_PATTERN.fullmatch(assignee):
            raise ValueError("status_sync_assignee may only use letters, digits, . _ @ -.")
        config.status_sync_assignee = assignee
    if "status_sync_hours" in data:
        config.status_sync_hours = max(0.0, float(data["status_sync_hours"]))
    return config
