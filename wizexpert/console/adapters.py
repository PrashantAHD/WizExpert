"""Adapter contract between the generic console and private, client-specific wiring.

A private adapter module lives under ``<private-root>/templates/console_adapters/`` and
exposes ``get_adapters(private_root: Path) -> list[CategoryAdapter]``. The console
never contains client names, evidence, identifiers or private paths: everything
specific (collection plan, data fill, builders, validators, output folders) is behind
this interface.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

ADAPTER_MODULE = Path("templates") / "console_adapters" / "adapters.py"
FIELD_KINDS = ("text", "textarea", "select", "date", "list", "bool", "path")


class AdapterError(Exception):
    """A user-facing problem with inputs or processing; the message is shown to the user."""


@dataclass(frozen=True)
class Field:
    """One form field. ``list`` fields hold rows of ``item_keys`` text values."""

    name: str
    label: str
    kind: str = "text"
    help: str = ""
    required: bool = False
    options: tuple[str, ...] = ()
    item_keys: tuple[str, ...] = ()
    min_items: int = 0
    max_items: int = 0  # 0 means unlimited
    default: Any = None

    def __post_init__(self) -> None:
        if self.kind not in FIELD_KINDS:
            raise ValueError(f"unsupported field kind {self.kind!r}")
        if self.kind == "list" and not self.item_keys:
            raise ValueError("list fields need item_keys")

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "kind": self.kind,
            "help": self.help,
            "required": self.required,
            "options": list(self.options),
            "item_keys": list(self.item_keys),
            "min_items": self.min_items,
            "max_items": self.max_items,
            "default": self.default,
        }


def coerce_fields(specs: list[Field], raw: Mapping[str, Any], *, partial: bool = False) -> dict:
    """Validate submitted values against field specs; unknown names are rejected."""
    by_name = {spec.name: spec for spec in specs}
    unknown = sorted(set(raw) - set(by_name))
    if unknown:
        raise AdapterError("Unknown field(s): " + ", ".join(unknown))
    out: dict[str, Any] = {}
    for spec in specs:
        value = raw.get(spec.name, spec.default)
        if spec.kind == "list":
            value = _coerce_list(spec, value, partial)
        elif spec.kind == "bool":
            value = bool(value)
        else:
            value = "" if value is None else value
            if not isinstance(value, str):
                raise AdapterError(f"{spec.label}: text expected.")
            value = value.strip()
            if len(value) > 20_000:
                raise AdapterError(f"{spec.label}: too long.")
            if spec.kind == "select" and value and value not in spec.options:
                raise AdapterError(f"{spec.label}: choose one of {', '.join(spec.options)}.")
        missing = value in ("", [], None) and spec.kind != "bool"
        if spec.required and missing and not partial:
            raise AdapterError(f"{spec.label} is required.")
        out[spec.name] = value
    return out


def _coerce_list(spec: Field, value: Any, partial: bool = False) -> list[dict[str, str]]:
    if value in (None, ""):
        value = []
    if not isinstance(value, list):
        raise AdapterError(f"{spec.label}: a list of rows is expected.")
    rows: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise AdapterError(f"{spec.label}: each row must be an object.")
        unknown = sorted(set(item) - set(spec.item_keys))
        if unknown:
            raise AdapterError(f"{spec.label}: unknown row key(s): {', '.join(unknown)}")
        row = {}
        for key in spec.item_keys:
            cell = item.get(key, "")
            if not isinstance(cell, str):
                raise AdapterError(f"{spec.label}: row values must be text.")
            row[key] = cell.strip()[:20_000]
        if any(row.values()):  # drop fully blank rows
            rows.append(row)
    if len(rows) < spec.min_items and not partial:
        raise AdapterError(f"{spec.label}: at least {spec.min_items} row(s) required.")
    if spec.max_items and len(rows) > spec.max_items:
        raise AdapterError(f"{spec.label}: at most {spec.max_items} row(s) allowed.")
    return rows


@runtime_checkable
class CategoryAdapter(Protocol):
    """What the console needs from a private category adapter.

    All methods are synchronous; the console runs them in a worker thread. Raise
    ``AdapterError`` for problems the user should read. Wiz access happens only through
    ``ctx.call`` / ``ctx.call_many`` (read-only, logged); never use another channel.
    """

    category_id: str
    title: str
    description: str
    qa_workflow: str | None  # `workflow-qa collection-check --workflow` value, or None
    observation_window_seconds: int | None  # None: no limit (console flag may override)

    def start_fields(self) -> list[Field]:
        """Inputs requested before collection (issue ID, reporting month, ...)."""

    def validate_inputs(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        """Normalise and validate the start inputs; raise AdapterError."""

    def supports_dry_run(self) -> bool:
        """True when ``replay_client`` can replay retained evidence offline."""

    def output_dir(self, inputs: Mapping[str, Any]) -> Path:
        """Private folder (under the deliverables root) that receives the deliverables."""

    def replay_client(self, inputs: Mapping[str, Any]) -> Any:
        """Offline MCP stand-in for dry runs: object with ``execute(tool, parameters)``."""

    def collect(self, ctx: Any) -> dict[str, Any]:
        """Collect via ``ctx.call*`` and save immutable evidence; return the collection manifest
        fragment ``{"reused_sources": [...] | "no_prior_evidence_reason": str,
        "counts": [{"name", "expected", "collected"}], "full_refresh_reason"?: str}``."""

    def narrative_fields(self, ctx: Any) -> list[Field]:
        """Fields the user types/edits after collection (may be empty)."""

    def prefill(self, ctx: Any) -> dict[str, Any]:
        """Values pre-filled from collected data (editable)."""

    def reference(self, ctx: Any) -> list[dict[str, str]]:
        """Read-only ``{"title", "text"}`` blocks shown beside the form."""

    def expected_outputs(self, ctx: Any, fields: Mapping[str, Any]) -> list[Path]:
        """Final paths generation will write (existing ones are archived first)."""

    def generate(self, ctx: Any, fields: Mapping[str, Any]) -> dict[str, Path]:
        """Build every slot deliverable into ``ctx.output_dir``; return ``{slot_id: path}``."""

    def bindings(self, ctx: Any, outputs: Mapping[str, Path]) -> Mapping[str, Any]:
        """Pinned ``SlotBinding`` per slot whose builder returns the generated file."""

    def extra_checks(self, ctx: Any, outputs: Mapping[str, Path]) -> list[str]:
        """Additional actual-output checks (problems list; empty means fine)."""

    def qa_extras(self, ctx: Any) -> dict[str, Any]:
        """Extra ``qa_review`` keys the category requires (e.g. prior_snapshot_retained)."""


def load_adapters(private_root: Path) -> dict[str, CategoryAdapter]:
    """Load private adapters from ``<private_root>/templates/console_adapters/adapters.py``."""
    private_root = Path(private_root).resolve()
    module_path = (private_root / ADAPTER_MODULE).resolve()
    if not module_path.is_file() or private_root not in module_path.parents:
        raise AdapterError(f"No private adapters found under {private_root}.")
    spec = importlib.util.spec_from_file_location("wizexpert_private_adapters", module_path)
    if spec is None or spec.loader is None:
        raise AdapterError("Private adapters could not be loaded.")
    module = importlib.util.module_from_spec(spec)
    folder = str(module_path.parent)
    added = folder not in sys.path
    if added:
        sys.path.insert(0, folder)
    try:
        spec.loader.exec_module(module)
    finally:
        if added and folder in sys.path:
            sys.path.remove(folder)
    factory: Callable[[Path], list[CategoryAdapter]] | None = getattr(module, "get_adapters", None)
    if factory is None:
        raise AdapterError("Private adapter module must define get_adapters(private_root).")
    adapters: dict[str, CategoryAdapter] = {}
    for adapter in factory(private_root):
        if not isinstance(adapter, CategoryAdapter):
            raise AdapterError("A private adapter does not implement the adapter contract.")
        adapters[adapter.category_id] = adapter
    if not adapters:
        raise AdapterError("Private adapter module returned no adapters.")
    return adapters
