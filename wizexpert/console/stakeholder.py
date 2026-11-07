"""Private per-work-item, per-report-date stakeholder responses (console state only)."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from typing import Any

from . import categories
from .config import ConsoleConfig

FILE = "stakeholder-responses.json"


def _path(config: ConsoleConfig):
    return config.state_dir / FILE


def _load(config: ConsoleConfig) -> dict[str, Any]:
    try:
        data = json.loads(_path(config).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def list_responses(config: ConsoleConfig, work_item: Any) -> list[dict[str, str]]:
    item = categories._work_item_text(work_item)
    entries = _load(config).get(item, {})
    return [{"report_date": d, **v} for d, v in sorted(entries.items()) if isinstance(v, dict)]


def save_response(config: ConsoleConfig, body: dict[str, Any]) -> dict[str, str]:
    """Validate and persist one response; raises ValueError (InputError) when invalid."""
    item = categories._work_item_text(body.get("work_item"))
    record = {
        "sender": categories._sender(body.get("sender")),
        "received_date": categories._received_date(body.get("received_date")),
        "text": categories._email(body.get("email_text")),
    }
    data = _load(config)
    data.setdefault(item, {})[record["received_date"]] = record
    config.state_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=config.state_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
        os.replace(tmp, _path(config))
    finally:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
    return record
