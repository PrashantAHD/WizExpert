"""Read-only detection of VS Code's native prompts (Windows).

VS Code shows some prompts as native Windows task dialogs, for example
"The MCP Server Definition 'wiz' wants to authenticate to mcp.app.wiz.io."
Extensions cannot see, answer or pre-approve them, so a run can sit waiting while
the prompt is hidden behind other windows. The console only *finds* these dialogs
to tell the user and to bring VS Code to the front. It never clicks a button,
sends input to a dialog or answers a prompt: approving stays with the user.

Finding a dialog is cheap (``EnumWindows``). Task dialogs draw their message
without child window text, so the message is read once per dialog through UI
Automation in a short-lived Windows PowerShell process and then cached. On
other platforms every function returns nothing.
"""

from __future__ import annotations

import json
import os
import re
import subprocess  # nosec B404
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

DIALOG_CLASS = "#32770"
CODE_PROCESSES = frozenset({"code.exe", "code - insiders.exe"})
MCP_AUTH = re.compile(
    r"^The MCP Server Definition '(?P<server>[^'\r\n]{1,100})' wants to authenticate to "
    r"(?P<host>[A-Za-z0-9.\-]{1,253}?)\.?$"
)
MAX_BUTTONS = 4
MAX_TEXTS = 6
MAX_TEXT = 300
READ_TIMEOUT = 15.0

# Fixed UI Automation script; the only input is the integer window handle. It returns the names
# of the dialog's text elements and nothing else.
_UIA_SCRIPT = (
    "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
    "Add-Type -AssemblyName UIAutomationClient,UIAutomationTypes;"
    "$e=[System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]{hwnd});"
    "$c=New-Object System.Windows.Automation.PropertyCondition("
    "[System.Windows.Automation.AutomationElement]::ControlTypeProperty,"
    "[System.Windows.Automation.ControlType]::Text);"
    "@($e.FindAll([System.Windows.Automation.TreeScope]::Descendants,$c)|"
    "ForEach-Object{{$_.Current.Name}})|ConvertTo-Json -Compress"
)


@dataclass(frozen=True)
class Window:
    """A visible native dialog owned by a VS Code process."""

    hwnd: int
    title: str
    buttons: tuple[str, ...]


@dataclass(frozen=True)
class Prompt:
    hwnd: int
    kind: str  # "mcp_auth" (an MCP server asks to sign in) or "dialog" (any other VS Code dialog)
    title: str
    buttons: tuple[str, ...]
    server: str = ""
    host: str = ""

    @property
    def id(self) -> str:
        return str(self.hwnd)

    def public(self) -> dict[str, Any]:
        """What the browser may see: no raw dialog text beyond the parsed server and host."""
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "buttons": list(self.buttons),
            "server": self.server,
            "host": self.host,
        }


def _clip(text: str, limit: int) -> str:
    return " ".join(str(text).split())[:limit]


def classify(window: Window, texts: tuple[str, ...]) -> Prompt:
    """Name the prompt from its message text; unknown messages stay a generic dialog."""
    for text in texts:
        match = MCP_AUTH.match(text.strip())
        if match:
            return Prompt(
                window.hwnd,
                "mcp_auth",
                window.title,
                window.buttons,
                server=match.group("server"),
                host=match.group("host").lower(),
            )
    return Prompt(window.hwnd, "dialog", window.title, window.buttons)


def parse_texts(output: str) -> tuple[str, ...]:
    """Parse the UI Automation script's JSON (a list of names, or one name)."""
    try:
        data = json.loads(output or "null")
    except ValueError:
        return ()
    items = data if isinstance(data, list) else [data]
    texts = [_clip(item, MAX_TEXT) for item in items if isinstance(item, str) and item.strip()]
    return tuple(texts[:MAX_TEXTS])


# -- Windows implementation (imported lazily so the module loads everywhere) ------------------


def _powershell() -> str:
    root = os.environ.get("SYSTEMROOT") or r"C:\Windows"
    return os.path.join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")


def read_texts(hwnd: int) -> tuple[str, ...]:
    """The dialog's message text through UI Automation (Windows only; empty on failure)."""
    if sys.platform != "win32" or not isinstance(hwnd, int) or hwnd <= 0:
        return ()
    script = _UIA_SCRIPT.format(hwnd=int(hwnd))
    try:
        result = subprocess.run(  # nosec B603  (fixed absolute path, fixed script, integer handle)
            [_powershell(), "-NoProfile", "-NonInteractive", "-Command", script],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=READ_TIMEOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return ()
    return parse_texts(result.stdout) if result.returncode == 0 else ()


def enumerate_windows() -> list[Window]:
    """Visible native dialogs owned by VS Code (Windows only)."""
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    names: dict[int, str] = {}

    def text_of(hwnd: Any, getter: Any, size: int = 256) -> str:
        buffer = ctypes.create_unicode_buffer(size)
        getter(hwnd, buffer, size)
        return buffer.value

    def process_name(pid: int) -> str:
        if pid not in names:
            name = ""
            handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if handle:
                try:
                    size = wintypes.DWORD(1024)
                    buffer = ctypes.create_unicode_buffer(size.value)
                    if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                        name = os.path.basename(buffer.value).lower()
                finally:
                    kernel32.CloseHandle(handle)
            names[pid] = name
        return names[pid]

    found: list[Window] = []

    def on_window(hwnd: Any, _param: Any) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        if text_of(hwnd, user32.GetClassNameW, 64) != DIALOG_CLASS:
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if process_name(pid.value) not in CODE_PROCESSES:
            return True
        buttons: list[str] = []

        def on_child(child: Any, _p: Any) -> bool:
            if text_of(child, user32.GetClassNameW, 64) == "Button":
                label = _clip(text_of(child, user32.GetWindowTextW).replace("&", ""), 40)
                if label and len(buttons) < MAX_BUTTONS:
                    buttons.append(label)
            return True

        user32.EnumChildWindows(hwnd, callback_type(on_child), 0)
        title = _clip(text_of(hwnd, user32.GetWindowTextW), 80)
        found.append(Window(int(hwnd), title, tuple(buttons)))
        return True

    user32.EnumWindows(callback_type(on_window), 0)
    return found


def raise_window(hwnd: int) -> bool:
    """Best effort: put the dialog in front, else flash its taskbar button. Never answers it."""
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes

    class FLASHWINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.UINT),
            ("hwnd", wintypes.HWND),
            ("dwFlags", wintypes.DWORD),
            ("uCount", wintypes.UINT),
            ("dwTimeout", wintypes.DWORD),
        ]

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.GetForegroundWindow.restype = wintypes.HWND
    handle = wintypes.HWND(hwnd)
    user32.SetForegroundWindow(handle)
    if user32.GetForegroundWindow() == hwnd:
        return True
    # Windows refuses focus changes from background processes; flashing still shows where to look.
    flash = FLASHWINFO(ctypes.sizeof(FLASHWINFO), handle, 0x3 | 0xC, 0, 0)  # ALL | TIMERNOFG
    user32.FlashWindowEx(ctypes.byref(flash))
    return False


class PromptWatcher:
    """Lists open VS Code prompts; reads each dialog's message once and caches it."""

    def __init__(
        self,
        enumerate_fn: Callable[[], list[Window]] | None = None,
        read_fn: Callable[[int], tuple[str, ...]] | None = None,
        raise_fn: Callable[[int], bool] | None = None,
    ) -> None:
        self._enumerate = enumerate_fn or enumerate_windows
        self._read = read_fn or read_texts
        self._raise = raise_fn or raise_window
        self._texts: dict[int, tuple[str, ...]] = {}
        self._reading: set[int] = set()
        self._lock = threading.Lock()

    def prompts(self) -> list[Prompt]:
        try:
            windows = self._enumerate()
        except OSError:
            return []
        # Decide what to read under the lock, but read (a PowerShell process, up to
        # READ_TIMEOUT) outside it so other requests never wait on a slow read. A dialog being
        # read by another request is reported as a generic dialog until its text is cached.
        with self._lock:
            live = {w.hwnd for w in windows}
            for gone in set(self._texts) - live:
                del self._texts[gone]
            self._reading &= live
            todo = [
                w.hwnd for w in windows if w.hwnd not in self._texts and w.hwnd not in self._reading
            ]
            self._reading.update(todo)
        for hwnd in todo:
            try:
                texts = self._read(hwnd)
            except Exception:  # noqa: BLE001  (a failed read must not break the console)
                texts = ()
            with self._lock:
                self._reading.discard(hwnd)
                self._texts[hwnd] = texts  # cached even when empty: each dialog is read once
        with self._lock:
            out = [classify(w, self._texts.get(w.hwnd, ())) for w in windows]
        # Sign-in prompts first: they are the ones a run is most likely waiting on.
        return sorted(out, key=lambda p: p.kind != "mcp_auth")

    def find(self, prompt_id: str) -> Prompt | None:
        return next((p for p in self.prompts() if p.id == str(prompt_id)), None)

    def bring_to_front(self, prompt: Prompt) -> bool:
        return bool(self._raise(prompt.hwnd))
