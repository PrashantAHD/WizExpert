"""List a case's deliverable files and open them in the matching local app (read-only).

Only direct files of one Risk Issues case folder are offered; names are re-resolved and
contained on every open. Apps come from a fixed allow-list, are launched with argument lists
(never a shell) and fall back to ``os.startfile`` (the OS default handler).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess  # nosec B404
from pathlib import Path
from typing import Any

from . import imports
from .config import ConsoleConfig
from .sessions import confine, is_denied

IMAGES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".svg"})
APP_BY_EXT: dict[str, str] = {
    ".pdf": "chrome",
    ".html": "chrome",
    ".htm": "chrome",
    ".xlsx": "excel",
    ".xls": "excel",
    ".csv": "excel",
    ".pptx": "powerpoint",
    ".ppt": "powerpoint",
    ".docx": "word",
    ".doc": "word",
    **dict.fromkeys(IMAGES, "default"),
}
ALLOWED_EXTENSIONS = frozenset({*APP_BY_EXT, ".md", ".txt", ".eml", ".msg"})
_ENV = ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")
_CHROME = ("Google/Chrome/Application/chrome.exe",)
_OFFICE = {
    "excel": "EXCEL.EXE",
    "powerpoint": "POWERPNT.EXE",
    "word": "WINWORD.EXE",
}
_OFFICE_DIRS = (
    "Microsoft Office/root/Office16",
    "Microsoft Office/Office16",
    "Microsoft Office/root/Office15",
)


def app_for(path: Path | str, with_app: str | None = None) -> str:
    """The app key for a file; ``with_app='chrome'`` is the only override (images/others)."""
    ext = Path(path).suffix.lower()
    if with_app == "chrome" and (ext in IMAGES or ext in APP_BY_EXT or ext in ALLOWED_EXTENSIONS):
        return "chrome"
    if with_app not in (None, "", "default"):
        raise ValueError("Unknown application.")
    return APP_BY_EXT.get(ext, "default")


def _find_exe(app: str) -> str | None:
    bases = [Path(v) for k in _ENV if (v := os.environ.get(k))]
    if app == "chrome":
        for base in bases:
            for rel in _CHROME:
                if (base / rel).is_file():
                    return str(base / rel)
        return shutil.which("chrome")
    exe = _OFFICE.get(app)
    if exe:
        for base in bases:
            for sub in _OFFICE_DIRS:
                if (base / sub / exe).is_file():
                    return str(base / sub / exe)
    return None


#: Deliverable categories shown in the console -> folder under the output root.
#: "monthly" files are flat in the category folder; its "folder" is the month (e.g. 2026-10).
CATEGORY_DIRS: dict[str, str] = {
    "risk-issues": imports.RISK_DIR,
    "weekly": imports.WEEKLY_DIR,
    "monthly": imports.MONTHLY_DIR,
}
_NO_FOLDER = "No such deliverables folder."


def _category_folder(config: ConsoleConfig, category: str, folder: str) -> Path:
    directory = CATEGORY_DIRS.get(category) if isinstance(category, str) else None
    base = imports._base(config, directory) if directory else None
    if base is None or not isinstance(folder, str):
        raise ValueError(_NO_FOLDER)
    if category == "monthly":
        if not re.fullmatch(r"20\d\d-(0[1-9]|1[0-2])", folder):
            raise ValueError(_NO_FOLDER)
        return base
    if not imports.SAFE_NAME.fullmatch(folder):
        raise ValueError(_NO_FOLDER)
    found = confine(base / folder, base)
    if found is None or not found.is_dir() or (base / folder).is_symlink() or found == base:
        raise ValueError(_NO_FOLDER)
    return found


def _case_folder(config: ConsoleConfig, case: str) -> Path:
    return _category_folder(config, "risk-issues", case)


def list_case_files(config: ConsoleConfig, case: str) -> list[dict[str, Any]]:
    return list_files(config, "risk-issues", case)


def list_files(config: ConsoleConfig, category: str, folder_name: str) -> list[dict[str, Any]]:
    folder = _category_folder(config, category, folder_name)
    out: list[dict[str, Any]] = []
    for entry in imports._children(folder, config):
        ext = entry.suffix.lower()
        if not entry.is_file() or ext not in ALLOWED_EXTENSIONS:
            continue
        if category == "monthly" and imports.month_of(entry.name) != folder_name:
            continue
        out.append(
            {
                "name": entry.name,
                "type": ext.lstrip("."),
                "modified": imports._mtime(entry),
                "app": app_for(entry),
                "can_open_in_chrome": ext in IMAGES,
            }
        )
    return out


def resolve_case_file(config: ConsoleConfig, case: str, name: str) -> Path:
    return resolve_file(config, "risk-issues", case, name)


def resolve_file(config: ConsoleConfig, category: str, folder_name: str, name: str) -> Path:
    folder = _category_folder(config, category, folder_name)
    if (
        not isinstance(name, str)
        or not name
        or name != Path(name).name
        or name in (".", "..")
        or "\\" in name
        or "/" in name
    ):
        raise ValueError("Unsupported file name.")
    candidate = folder / name
    path = confine(candidate, folder)
    workspace = config.resolved_workspace()
    if (
        path is None
        or path.parent != folder
        or candidate.is_symlink()
        or not path.is_file()
        or is_denied(path.relative_to(workspace), config)
    ):
        raise ValueError("That file is not available.")
    if path.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError("That file type cannot be opened from the console.")
    if category == "monthly" and imports.month_of(path.name) != folder_name:
        raise ValueError("That file is not available.")
    return path


def open_case_file(config: ConsoleConfig, case: str, name: str, with_app: str | None = None) -> str:
    return open_file(config, "risk-issues", case, name, with_app)


def open_file(
    config: ConsoleConfig,
    category: str,
    folder_name: str,
    name: str,
    with_app: str | None = None,
) -> str:
    """Open the file locally; returns the app used (chrome/excel/.../default)."""
    return _launch(resolve_file(config, category, folder_name, name), with_app)


def open_relative(config: ConsoleConfig, relative: str) -> str:
    """Compatibility for ``/api/imports/open``: map a workspace-relative path onto a category
    folder + name and open it through the same checks as :func:`open_file`."""
    if not isinstance(relative, str) or "\\" in relative:
        raise ValueError("Unsupported path.")
    parts = relative.split("/")
    root = Path(config.output_roots[0]).as_posix().split("/")
    by_dir = {v: k for k, v in CATEGORY_DIRS.items()}
    n = len(root)
    if len(parts) == n + 2 and parts[:n] == root and parts[n] == imports.MONTHLY_DIR:
        month = imports.month_of(parts[-1])  # flat monthly file
        return open_file(config, "monthly", month, parts[-1])
    if len(parts) == n + 3 and parts[:n] == root and parts[n] in by_dir:
        return open_file(config, by_dir[parts[n]], parts[n + 1], parts[-1])
    raise ValueError("That file is not available.")


def _launch(path: Path, with_app: str | None) -> str:
    app = app_for(path, with_app)
    exe = _find_exe(app) if app != "default" else None
    try:
        if exe:
            subprocess.Popen([exe, str(path)], close_fds=True)  # nosec B603
            return app
        os.startfile(str(path))  # type: ignore[attr-defined]  # nosec B606
    except (OSError, AttributeError) as error:
        raise ValueError("The file could not be opened: " + type(error).__name__) from None
    return "default"
