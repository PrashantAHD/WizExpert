"""Build and install the VS Code helper extension (no packaging tools needed).

``build_vsix`` zips the bundled extension source with a generated manifest; ``install`` runs
``code --install-extension`` so VS Code registers it. The helper only activates in a standard
VS Code window (not the Agents window); ``open_workspace_window`` opens one for the workspace.
"""

from __future__ import annotations

import json
import shutil
import subprocess  # nosec B404
import zipfile
from pathlib import Path

NAME = "wizexpert-console-helper"
PUBLISHER = "local"
VERSION = "0.1.6"
SOURCE = Path(__file__).resolve().parent / "extension" / "extension.js"

PACKAGE = {
    "name": NAME,
    "displayName": "WizExpert Console Helper",
    "description": "Lets the local WizExpert console open an agent-mode chat and press "
    "Accept/Skip. Local only.",
    "version": VERSION,
    "publisher": PUBLISHER,
    "engines": {"vscode": "^1.90.0"},
    "categories": ["Other"],
    "activationEvents": [
        "onStartupFinished",
        "onUri",
        "workspaceContains:**/*",
        "onCommand:wizexpertConsoleHelper.status",
    ],
    "main": "./extension.js",
    "extensionKind": ["ui"],
    "contributes": {
        "commands": [
            {
                "command": "wizexpertConsoleHelper.status",
                "title": "WizExpert Console Helper: Show Status",
            }
        ]
    },
}
CONTENT_TYPES = """<?xml version="1.0" encoding="utf-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension=".json" ContentType="application/json"/>
  <Default Extension=".js" ContentType="application/javascript"/>
  <Default Extension=".vsixmanifest" ContentType="text/xml"/>
</Types>
"""
MANIFEST = """<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011">
  <Metadata>
    <Identity Language="en-US" Id="{name}" Version="{version}" Publisher="{publisher}"/>
    <DisplayName>{display}</DisplayName>
    <Description xml:space="preserve">{description}</Description>
    <Properties>
      <Property Id="Microsoft.VisualStudio.Code.Engine" Value="{engine}"/>
      <Property Id="Microsoft.VisualStudio.Code.ExtensionKind" Value="ui"/>
    </Properties>
  </Metadata>
  <Installation>
    <InstallationTarget Id="Microsoft.VisualStudio.Code"/>
  </Installation>
  <Dependencies/>
  <Assets>
    <Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json"
      Addressable="true"/>
  </Assets>
</PackageManifest>
"""


def build_vsix(out: Path) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    manifest = MANIFEST.format(
        name=NAME,
        version=VERSION,
        publisher=PUBLISHER,
        display=PACKAGE["displayName"],
        description=PACKAGE["description"],
        engine=PACKAGE["engines"]["vscode"],
    )
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("[Content_Types].xml", CONTENT_TYPES)
        bundle.writestr("extension.vsixmanifest", manifest)
        bundle.writestr("extension/package.json", json.dumps(PACKAGE, indent=2))
        bundle.writestr("extension/extension.js", SOURCE.read_text(encoding="utf-8"))
    return out


EXTENSION_ID = f"{PUBLISHER}.{NAME}"


def _cli(code_command: str) -> str:
    return shutil.which(code_command) or code_command


def installed_version(code_command: str = "code") -> str | None:
    """Version of the helper VS Code has registered, or None (also when the CLI is unusable)."""
    try:
        result = subprocess.run(  # nosec B603 - fixed arguments, user-chosen CLI name
            [_cli(code_command), "--list-extensions", "--show-versions"],
            check=False,
            timeout=60,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    prefix = EXTENSION_ID.lower() + "@"
    for line in result.stdout.splitlines():
        if line.strip().lower().startswith(prefix):
            return line.strip().split("@", 1)[1]
    return None


def open_workspace_window(code_command: str, workspace: Path | str) -> int:
    """Open a standard VS Code window (``code -n <workspace>``) for the configured workspace.

    The VS Code "Agents" window never loads user-installed extensions, so the helper can only
    connect from a standard workbench window. Argument list only (no shell); the single path
    argument is the configured workspace and must be an existing folder.
    """
    folder = Path(workspace)
    if not folder.is_dir():
        return 1
    try:
        return subprocess.run(  # nosec B603 - fixed arguments, configured workspace folder
            [_cli(code_command), "-n", str(folder)],
            check=False,
            timeout=30,
            capture_output=True,
        ).returncode
    except (OSError, subprocess.SubprocessError):
        return 1


def install(out: Path, code_command: str = "code", force: bool = False) -> int:
    """Build the vsix and install it into VS Code. Returns the CLI exit code.

    Idempotent: when this exact version is already registered the install is skipped, because
    ``--force`` re-extracts the folder under a running extension host and makes windows lose it.
    """
    if not force and installed_version(code_command) == VERSION:
        return 0
    vsix = build_vsix(out)
    result = subprocess.run(  # nosec B603 - fixed arguments, user-chosen CLI name
        [_cli(code_command), "--install-extension", str(vsix), "--force"],
        check=False,
        timeout=120,
    )
    return result.returncode
